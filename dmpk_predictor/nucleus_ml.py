# smiles-ok-file
"""
Nucleus ML client — live in-process ADME predictions from SMILES.

This is the REAL Nucleus access path (not a REST endpoint): it wraps the merged
`predict_smiles` inference API via the `ADMEPredictor` object shown in the NIK
metabolic-stability boilerplate
(logbooks/.../2026-07-16-nik-metabolic-stability-boilerplate/predict_adme.py).

It runs the models *in process*, so it only works where the Genesis inference
stack is importable and authenticated:
  * conda env `deep-affinity`
  * W&B + GCS auth and DB_URL set  (on an agent VM: `source ~/.cursor/env.sh prod`)
The import is guarded — on the public Streamlit deployment (no `da.adme`) the
feature is simply unavailable and the tool falls back to CDD / manual input.

Output units follow ADME_PROPERTIES[task].units:
  * *_stability_* tasks -> mL/min/kg SCALED CLint (physical units, deconvert=True)
  * logd               -> logD (unitless)
  * ppb tasks          -> fraction (or %); confirm per task (see UNIT NOTES)

Because loading a model (W&B read + GCS checkpoint) and standardization (~37 s
fixed Flint cost) are expensive, predictors are cached per (task, alias) and
SMILES are scored in one batched call.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Optional

# --- guarded import of the internal inference stack ---------------------------
try:
    from predict_adme import ADMEPredictor, predict_adme_property  # boilerplate module
    _NUCLEUS_VIA = "predict_adme"
    NUCLEUS_AVAILABLE = True
except Exception:
    try:
        # fall back to the primitives directly if the boilerplate isn't on the path
        from da.adme.inference import load_adme_model_from_wandb          # noqa: F401
        from da.adme.registry import ADME_REGISTRY_PREFIX, resolve_alias  # noqa: F401
        from virtual_screen.constants.adme import ADME_PROPERTIES         # noqa: F401
        _NUCLEUS_VIA = "da.adme"
        NUCLEUS_AVAILABLE = True
    except Exception:
        NUCLEUS_AVAILABLE = False
        _NUCLEUS_VIA = None


# --- which Nucleus task/alias backs each parameter our engine needs ----------
# Keys are ADME_PROPERTIES task names. Confirm the exact strings on your stack
# with `available_tasks()` (below) — only `microsomal_stability_human` and
# `logd` are documented in the boilerplate; the mouse/hepatocyte/PPB names are
# best-guesses and are trivially editable here.
#   alias rule (per boilerplate README):
#     production-NIK-mixed  -> microsomal_stability_human => NIK-local model
#     every other task      -> production-internal-global
NIK_ALIAS = "production-NIK-mixed"
GLOBAL_ALIAS = "production-internal-global"

TASK_MAP = {
    # engine field        (task,                              alias)
    "clint_mic_human":    ("microsomal_stability_human",      NIK_ALIAS),
    "clint_hep_human":    ("hepatocyte_stability_human",      GLOBAL_ALIAS),
    "clint_mic_mouse":    ("microsomal_stability_mouse",      GLOBAL_ALIAS),
    "clint_hep_mouse":    ("hepatocyte_stability_mouse",      GLOBAL_ALIAS),
    "ppb_human":          ("ppb_human",                       GLOBAL_ALIAS),
    "ppb_mouse":          ("ppb_mouse",                       GLOBAL_ALIAS),
    "logd":               ("logd",                            GLOBAL_ALIAS),
    # add when models exist in Nucleus: pka_acidic, pka_basic, logp,
    # solubility, caco2/mdck permeability, rat CLint/PPB.
}

# microsomal-protein / hepatocyte scaling factors (mL/min/kg per uL/min/mg or /1e6cells)
# SF = per-liver-content * (liver g / kg BW) / 1000 ; used to convert Nucleus SCALED
# CLint (mL/min/kg) back to raw in-vitro units the engine re-scales. Matches config.
_SF = {  # (microsome_SF, hepatocyte_SF)
    "human": (40.0 * 21.4 / 1000.0, 139.0 * 21.4 / 1000.0),
    "rat":   (45.0 * 40.0 / 1000.0, 117.0 * 40.0 / 1000.0),
    "mouse": (41.5 * 50.0 / 1000.0, 135.0 * 50.0 / 1000.0),
}


@lru_cache(maxsize=None)
def _get_predictor(task: str, alias: str):
    """Load-once, cache-forever ADMEPredictor for a (task, alias)."""
    if not NUCLEUS_AVAILABLE:
        raise RuntimeError("Nucleus inference stack not importable in this environment.")
    return ADMEPredictor.load(task, alias)


def available_tasks() -> List[str]:
    """Return the real ADME_PROPERTIES task keys on this stack (to verify TASK_MAP)."""
    from virtual_screen.constants.adme import ADME_PROPERTIES
    return sorted(ADME_PROPERTIES.keys())


def predict_field(field: str, smiles: List[str]) -> List[Optional[float]]:
    """Predict one engine field for a batch of SMILES (physical units)."""
    task, alias = TASK_MAP[field]
    preds = _get_predictor(task, alias).predict(list(smiles))  # standardize+deconvert on
    return [None if p != p else float(p) for p in preds]       # NaN -> None


def predict_adme_for_engine(smiles: str, species: str = "human") -> Dict:
    """Build the ADME dict `predict_rat_dose` expects, from live Nucleus ML.

    Fills clint (microsome+hepatocyte), fu_p (from PPB) and logd for `species`.
    CLint is returned by Nucleus already SCALED (mL/min/kg); we divide by the
    species scaling factor so the engine's own scaling reproduces it exactly.
    Missing/failed models are simply omitted (engine handles absent fields).
    """
    if not NUCLEUS_AVAILABLE:
        raise RuntimeError(
            "Nucleus ML unavailable: run inside the deep-affinity env with W&B/GCS "
            "auth (e.g. `source ~/.cursor/env.sh prod`).")
    sp = species.strip().lower()
    sf_mic, sf_hep = _SF.get(sp, _SF["human"])
    adme: Dict = {}

    def _one(field):
        try:
            v = predict_field(field, [smiles])[0]
            return v
        except Exception:
            return None

    clint_mic = _one(f"clint_mic_{sp}")
    if clint_mic is not None:
        adme["clint"] = {"value": clint_mic / sf_mic, "unit": "uL/min/mg", "matrix": "microsome"}
    clint_hep = _one(f"clint_hep_{sp}")
    if clint_hep is not None:
        adme["clint_hep"] = {"value": clint_hep / sf_hep, "unit": "uL/min/1e6 cells", "matrix": "hepatocyte"}
    ppb = _one(f"ppb_{sp}")
    if ppb is not None:
        fu = ppb / 100.0 if ppb > 1.0 else ppb      # accept % or fraction  [UNIT NOTE]
        adme["fu_p"] = {"value": fu, "unit": "fraction"}
    logd = None
    try:
        logd = predict_field("logd", [smiles])[0]
    except Exception:
        pass
    return {"adme": adme, "logd": logd, "species": sp,
            "raw": {"clint_mic_scaled_mL_min_kg": clint_mic,
                    "clint_hep_scaled_mL_min_kg": clint_hep,
                    "ppb": ppb, "logd": logd}}
