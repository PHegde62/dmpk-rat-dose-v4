# smiles-ok-file
"""
Nucleus ML client — live in-process ADME predictions from SMILES.

Self-contained on the internal inference primitives (`da.adme` + the Virtual
Screen ADME constants), mirroring the ADMEPredictor pattern from the NIK
metabolic-stability boilerplate
(logbooks/.../2026-07-16-nik-metabolic-stability-boilerplate/predict_adme.py).
You do NOT need that personal boilerplate file on your path — only the
`deep-affinity` env where `da.adme` and `virtual_screen.constants.adme` live.

Runs the models IN PROCESS, so it only works where the Genesis inference stack
is importable and authenticated:
  * conda env `deep-affinity`
  * W&B + GCS auth and DB_URL set   (on an agent VM: `source ~/.cursor/env.sh prod`)
The import is guarded — if the stack is absent (e.g. Streamlit Cloud), the
feature is simply unavailable and the tool falls back to CDD / manual input.

See LOCAL_SETUP_NUCLEUS.md for how to run this on your machine via Streamlit.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from typing import Dict, List, Optional

# --- guarded import of the internal inference stack --------------------------
# Optionally add the logbooks boilerplate dir to sys.path (if you prefer to reuse
# its predict_adme.ADMEPredictor). Not required — we implement the predictor here.
_BP = os.environ.get("NUCLEUS_BOILERPLATE_DIR")
if _BP and _BP not in sys.path:
    sys.path.insert(0, _BP)

try:
    from da.adme.inference import load_adme_model_from_wandb
    from da.adme.registry import ADME_REGISTRY_PREFIX, resolve_alias
    from virtual_screen.constants.adme import ADME_PROPERTIES, safe_deconvert
    NUCLEUS_AVAILABLE = True
    _IMPORT_ERROR = None
except Exception as _exc:                     # pragma: no cover (env-dependent)
    NUCLEUS_AVAILABLE = False
    _IMPORT_ERROR = repr(_exc)


# --- which Nucleus task/alias backs each parameter our engine needs ----------
# Keys are ADME_PROPERTIES task names. Only `microsomal_stability_human` and
# `logd` are documented in the boilerplate; verify the mouse/hepatocyte/PPB
# names on your stack with `available_tasks()` and edit here as needed.
#   alias rule (boilerplate README):
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
    # add when models exist: pka_acidic, pka_basic, logp, solubility,
    # caco2/mdck permeability, rat CLint/PPB.
}

# microsome / hepatocyte scaling factors (mL/min/kg per uL/min/mg or /1e6 cells).
# SF = per-liver-content * (liver g/kg BW) / 1000. Nucleus returns SCALED CLint
# (mL/min/kg); we divide by SF so the engine's own scaling reproduces it exactly.
_SF = {  # (microsome_SF, hepatocyte_SF)
    "human": (40.0 * 21.4 / 1000.0, 139.0 * 21.4 / 1000.0),
    "rat":   (45.0 * 40.0 / 1000.0, 117.0 * 40.0 / 1000.0),
    "mouse": (41.5 * 50.0 / 1000.0, 135.0 * 50.0 / 1000.0),
}


def why_unavailable() -> Optional[str]:
    """Return the import error string if the Nucleus stack could not be loaded."""
    return _IMPORT_ERROR


def available_tasks() -> List[str]:
    """Real ADME_PROPERTIES task keys on this stack (use to verify TASK_MAP)."""
    if not NUCLEUS_AVAILABLE:
        raise RuntimeError("Nucleus stack unavailable: " + str(_IMPORT_ERROR))
    return sorted(ADME_PROPERTIES.keys())


@lru_cache(maxsize=None)
def _get_model(task: str, alias: str):
    """Load-once, cache-forever ADME model for (task, alias). Resolves virtual
    aliases in code (a raw virtual alias would 404 against W&B)."""
    if not NUCLEUS_AVAILABLE:
        raise RuntimeError("Nucleus stack unavailable: " + str(_IMPORT_ERROR))
    resolved = resolve_alias(task, alias)                       # e.g. -> production-NIK-local
    registry_path = f"{ADME_REGISTRY_PREFIX}/{task}:{resolved}"
    return load_adme_model_from_wandb(registry_path)


def _deconvert(preds, task: str) -> List[Optional[float]]:
    """Map model space (log10 for stability) to physical units via the task's
    deconversion; NaN / non-finite -> None."""
    deconv = ADME_PROPERTIES[task].deconversion
    out = [safe_deconvert(deconv, None if v != v else v) for v in preds]
    return [None if p is None else float(p) for p in out]


def predict_field(field: str, smiles: List[str],
                  standardize: bool = True, deconvert: bool = True) -> List[Optional[float]]:
    """Predict one engine field for a batch of SMILES (physical units by default).

    Keep standardize=True for raw SMILES (reproduces training-time ligand prep;
    ~37 s fixed Flint cost per call, so batch your molecules).
    """
    task, alias = TASK_MAP[field]
    model = _get_model(task, alias)
    preds = model.predict_smiles(list(smiles), standardize=standardize)   # model space
    return _deconvert(preds, task) if deconvert else [float(x) for x in preds]


def task_units(field: str) -> Optional[str]:
    """Physical units for a mapped field (ADME_PROPERTIES[task].units)."""
    return ADME_PROPERTIES[TASK_MAP[field][0]].units if NUCLEUS_AVAILABLE else None


def predict_adme_for_engine(smiles: str, species: str = "human") -> Dict:
    """Build the ADME dict `predict_rat_dose` expects, from live Nucleus ML.

    Fills clint (microsome+hepatocyte), fu_p (from PPB) and logd for `species`.
    Nucleus CLint is already SCALED (mL/min/kg); we divide by the species scaling
    factor so the engine's own scaling reproduces it exactly. Missing/failed
    models are omitted (the engine handles absent fields).
    """
    if not NUCLEUS_AVAILABLE:
        raise RuntimeError(
            "Nucleus ML unavailable (" + str(_IMPORT_ERROR) + "). Run inside the "
            "deep-affinity env with W&B/GCS auth (e.g. `source ~/.cursor/env.sh prod`).")
    sp = species.strip().lower()
    sf_mic, sf_hep = _SF.get(sp, _SF["human"])
    adme: Dict = {}

    def _one(field):
        try:
            return predict_field(field, [smiles])[0]
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
        fu = ppb / 100.0 if ppb > 1.0 else ppb          # accept % or fraction  [UNIT NOTE]
        adme["fu_p"] = {"value": fu, "unit": "fraction"}
    try:
        logd = predict_field("logd", [smiles])[0]
    except Exception:
        logd = None
    return {"adme": adme, "logd": logd, "species": sp,
            "raw": {"clint_mic_scaled_mL_min_kg": clint_mic,
                    "clint_hep_scaled_mL_min_kg": clint_hep,
                    "ppb": ppb, "logd": logd}}
