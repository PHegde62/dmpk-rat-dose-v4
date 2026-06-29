"""
Hybrid engine: RDKit structure + user-supplied experimental ADME -> human dose.

This is the unified entry point requested in the revised brief. It:
  1. pulls structural descriptors (MW, logP, logD, ionisation class) from RDKit,
  2. standardises every experimental ADME input via `units.py`,
  3. validates inputs (assert / log physically impossible values),
  4. runs the math engine to get E_H, CL_H, F and the predicted human dose.

The ADME inputs are passed as a dict of {parameter: spec}, where spec is either a
bare number (canonical units assumed) or {"value": x, "unit": "...", ...}.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from . import units
from .allometry import predict_all_species
from .binding import resolve_fu_inc
from .dose import predict_dose
from .features import smiles_to_features, MoleculeFeatures
from .ivive import well_stirred
from .config import PHYSIOLOGY

logger = logging.getLogger("dmpk_predictor.hybrid")

_QH_HUMAN = PHYSIOLOGY["human"].qh  # mL/min/kg


# --------------------------------------------------------------------------- #
# Standardised (canonical-unit) ADME container
# --------------------------------------------------------------------------- #
@dataclass
class StandardADME:
    clint_liver: Optional[float] = None     # mL/min/kg
    matrix: str = "microsome"               # 'microsome' | 'hepatocyte'
    fu_inc: Optional[float] = None          # fraction (measured); else predicted
    fu_p: Optional[float] = None            # fraction
    blood_plasma_ratio: float = 1.0
    permeability_cm_s: Optional[float] = None
    efflux_ratio: Optional[float] = None
    solubility_uM: Optional[float] = None
    vd_human: Optional[float] = None        # L/kg (optional; needed for Cmax/Cmin)
    bioavailability_pct: Optional[float] = None  # override; else computed
    warnings: list[str] = field(default_factory=list)


def _spec(d: Any) -> tuple[float, Optional[str], dict]:
    """Normalise a parameter spec into (value, unit, extra)."""
    if d is None:
        return None, None, {}
    if isinstance(d, dict):
        extra = {k: v for k, v in d.items() if k not in ("value", "unit")}
        return d.get("value"), d.get("unit"), extra
    return float(d), None, {}   # bare number -> canonical units assumed


def standardise_adme(
    adme: dict,
    *,
    mw: Optional[float],
    scaling: units.ScalingFactors = units.DEFAULT_SCALING,
) -> StandardADME:
    """Convert a raw ADME input dict into canonical units, validating each value."""
    std = StandardADME()

    # ---- CLint ----
    if "clint" in adme:
        val, unit, extra = _spec(adme["clint"])
        std.matrix = (extra.get("matrix") or adme.get("matrix") or "microsome").lower()
        std.clint_liver = units.convert_clint(
            val, unit or "mL/min/kg", matrix=std.matrix, scaling=scaling
        )

    # ---- fu,inc (incubation) ----
    if "fu_inc" in adme and adme["fu_inc"] is not None:
        val, unit, _ = _spec(adme["fu_inc"])
        std.fu_inc = units.convert_fu(val, unit or "fraction")

    # ---- fu,p (plasma) ----
    if "fu_p" in adme:
        val, unit, _ = _spec(adme["fu_p"])
        std.fu_p = units.convert_fu(val, unit or "fraction")

    # ---- blood:plasma ----
    if "blood_plasma_ratio" in adme and adme["blood_plasma_ratio"] is not None:
        val, _, _ = _spec(adme["blood_plasma_ratio"])
        if val <= 0:
            raise units.UnitError(f"Blood:plasma ratio must be > 0, got {val}")
        std.blood_plasma_ratio = float(val)

    # ---- permeability (Papp) ----
    if "permeability" in adme and adme["permeability"] is not None:
        val, unit, _ = _spec(adme["permeability"])
        if val < 0:
            raise units.UnitError(f"Permeability cannot be negative, got {val}")
        std.permeability_cm_s = units._linear("permeability", val, unit or "cm/s")

    # ---- efflux ratio ----
    if "efflux_ratio" in adme and adme["efflux_ratio"] is not None:
        val, _, _ = _spec(adme["efflux_ratio"])
        std.efflux_ratio = units.convert_efflux_ratio(val)

    # ---- solubility ----
    if "solubility" in adme and adme["solubility"] is not None:
        val, unit, _ = _spec(adme["solubility"])
        std.solubility_uM = units.convert_solubility(val, unit or "uM", mw)

    # ---- optional Vd and F overrides ----
    if "vd_human" in adme and adme["vd_human"] is not None:
        val, _, _ = _spec(adme["vd_human"])
        if val <= 0:
            raise units.UnitError(f"Vd must be > 0, got {val}")
        std.vd_human = float(val)
    if "bioavailability_pct" in adme and adme["bioavailability_pct"] is not None:
        val, _, _ = _spec(adme["bioavailability_pct"])
        if not 0.0 <= val <= 100.0:
            raise units.UnitError(f"Bioavailability must be 0-100%, got {val}")
        std.bioavailability_pct = float(val)

    return std


# --------------------------------------------------------------------------- #
# Bioavailability (mechanistic, image protocol Part 2.4)
# --------------------------------------------------------------------------- #
def fraction_absorbed(permeability_cm_s: Optional[float]) -> float:
    """Fa from Caco-2 permeability. >=1e-6 cm/s -> ~1.0, else crude linear scale."""
    if permeability_cm_s is None:
        return 1.0
    if permeability_cm_s >= 1e-6:
        return 1.0
    return max(0.0, min(1.0, permeability_cm_s / 1e-6))


# --------------------------------------------------------------------------- #
# Unified prediction
# --------------------------------------------------------------------------- #
def predict_human_dose(
    smiles: str,
    adme: dict,
    *,
    target_type: str = "AUC",
    target_free: float = 0.0,
    tau_hours: float = 24.0,
    logd: Optional[float] = None,
    ionisation_class: Optional[str] = None,
    scaling: units.ScalingFactors = units.DEFAULT_SCALING,
) -> dict:
    """Run the full hybrid pipeline for one compound.

    Returns a flat dict of inputs, intermediates (E_H, CL_H, F) and the dose.
    Never raises on a bad SMILES; on failure returns {"error": ...}.
    """
    out: dict = {"smiles": smiles, "error": None}

    feats: MoleculeFeatures = smiles_to_features(
        smiles, logd=logd, ionisation_class=ionisation_class
    )
    if feats.error:
        out["error"] = f"SMILES error: {feats.error}"
        return out
    out.update({
        "mw": feats.mw, "clogp": feats.clogp, "logd": feats.logd,
        "ionisation_class": feats.ionisation_class, "tpsa": feats.tpsa,
    })

    try:
        std = standardise_adme(adme, mw=feats.mw, scaling=scaling)
    except units.UnitError as exc:
        out["error"] = f"Input error: {exc}"
        logger.warning("Input validation failed for %s: %s", smiles, exc)
        return out

    if std.clint_liver is None or std.fu_p is None:
        out["error"] = "Missing required ADME: clint and fu_p"
        return out

    # fu,inc: measured if given, else Austin prediction
    fu_inc = resolve_fu_inc(
        std.fu_inc, matrix=std.matrix,
        logp=feats.clogp, logd=feats.logd, ionisation_class=feats.ionisation_class,
    )

    wsm = well_stirred(
        clint_liver=std.clint_liver, fu_inc=fu_inc, fu_p=std.fu_p,
        blood_plasma_ratio=std.blood_plasma_ratio, qh=_QH_HUMAN,
    )

    fa = fraction_absorbed(std.permeability_cm_s)
    fg = 1.0                       # assumed ~1 for early predictions
    fh = 1.0 - wsm["eh"]           # fraction escaping hepatic first pass
    f_pred = fa * fg * fh
    f_pct = std.bioavailability_pct if std.bioavailability_pct is not None else f_pred * 100.0

    out.update({
        "matrix": std.matrix,
        "fu_inc": fu_inc,
        "fu_p": std.fu_p,
        "blood_plasma_ratio": std.blood_plasma_ratio,
        "clint_liver_mL_min_kg": std.clint_liver,
        "cl_u_int_mL_min_kg": wsm["cl_u_int"],
        "clh_blood_mL_min_kg": wsm["clh_blood"],
        "clh_plasma_mL_min_kg": wsm["clh_plasma"],
        "E_H": wsm["eh"],
        "Fa": fa, "Fg": fg, "Fh": fh, "F_pct": f_pct,
        "solubility_uM": std.solubility_uM,
        "permeability_cm_s": std.permeability_cm_s,
        "efflux_ratio": std.efflux_ratio,
    })

    # Dose (AUC needs only CL; Cmax/Cmin need Vd -> kel)
    cl_h = wsm["clh_plasma"]
    vd = std.vd_human
    kel = (cl_h / vd / 1000.0 * 60.0) if vd else None
    if target_type.strip().upper() != "AUC" and vd is None:
        out["error"] = f"target_type={target_type} requires vd_human"
        return out

    dose = predict_dose(
        target_type=target_type, target_free=target_free, mw=feats.mw,
        fu_human=std.fu_p, cl_human=cl_h, vd_human=vd or 1.0, kel=kel or 0.0,
        bioavailability_pct=f_pct, tau_hours=tau_hours,
    )
    out["target_type"] = dose.target_type
    out["target_free"] = target_free
    out["dose_mg"] = dose.dose_mg

    # ---- Multi-species allometry (optional in vivo animal PK) ----
    invivo = adme.get("invivo")
    if invivo:
        try:
            out.update(predict_all_species(invivo, fu_human=std.fu_p))
        except Exception as exc:  # bad in vivo block shouldn't sink the whole row
            out["allometry_error"] = str(exc)
    return out
