# smiles-ok-file  (docstring only references a public reference SMILES)
"""
V4 rat dose engine: SMILES + rat ADME -> RAT PK & maintenance dose + profile.

This is the rat analogue of ``hybrid.predict_human_dose``. The key differences
from the human path (V1-V3):

  * NO cross-species allometry. The target species *is* the rat, so rat in vitro
    / in vivo data is used directly - there is nothing to scale "up to".
  * Rat physiology everywhere: hepatic blood flow Qh = 80 mL/min/kg, liver
    weight 40 g/kg, MPPGL 45 mg/g, hepatocellularity 117e6 cells/g (config), and
    body weight 0.25 kg for the dose and the concentration-time profile.
  * Vss: a MEASURED rat Vss (from rat IV PK in CDD) is preferred; if absent, the
    Oie-Tozer model with rat physiological volumes is used as a documented
    fallback.

In-vitro clearance source is selectable (``cl_source``):
  * "microsome"  - scale rat liver-microsome CLint via the well-stirred model.
  * "hepatocyte" - scale rat hepatocyte CLint via the well-stirred model.
  * "direct"     - use a directly supplied rat CL (mL/min/kg), bypassing IVIVE.

When a measured/observed rat CL is supplied (``cl_obs``) the function also returns
the IVIVE correlation: predicted-vs-observed CL and the fold error.

Everything else (well-stirred IVIVE, Austin incubation-binding, mechanistic
F = Fa.Fg.Fh, the AUC/Cmax/Cmin dose forms, the 1-compartment first-order
absorption profile) is the same validated math, evaluated with rat constants.

The function never raises on a bad input; failures land in the ``error`` key so a
batch run is never sunk by one compound.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from . import units
from .binding import resolve_fu_inc
from .bioavailability import fraction_absorbed
from .config import PHYSIOLOGY, TARGET_SPECIES
from .dose import predict_dose
from .features import smiles_to_features, MoleculeFeatures
from .hybrid import standardise_adme
from .ivive import well_stirred
from .simulate import simulate_profile
from .vd_predict import predict_vd

logger = logging.getLogger("dmpk_predictor.rat_dose")

# Accepted spellings for the in-vitro CL source dropdown.
_MICRO = {"microsome", "microsomes", "mic", "rlm", "liver microsomes"}
_HEP = {"hepatocyte", "hepatocytes", "hep", "rh"}
_DIRECT = {"direct", "cl_direct", "predicted rat cl", "direct rat cl", "measured cl"}


def _num(v):
    """Extract a float from a bare number or a {'value': x} spec."""
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def predict_rat_dose(
    smiles: str,
    adme: dict,
    *,
    target_type: str = "Cmin",
    target_free: float = 0.0,
    tau_hours: float = 12.0,
    ka_per_h: float = 1.0,
    cl_source: str = "microsome",
    cl_obs: Optional[float] = None,
    vss_obs: Optional[float] = None,
    logd: Optional[float] = None,
    ionisation_class: Optional[str] = None,
    species: str = TARGET_SPECIES,
    scaling: Optional[units.ScalingFactors] = None,
    sim_t_end_h: float = 48.0,
    sim_dt_h: float = 0.1,
    want_profile: bool = True,
) -> dict:
    """Full rat PK + dose pipeline for one compound.

    Parameters
    ----------
    smiles : str
    adme : dict
        ADME inputs (same schema as ``hybrid.predict_human_dose``). For the rat
        path these should be RAT readouts: rat liver-microsome ``clint`` and/or
        rat hepatocyte ``clint_hep``, rat ``fu_p``, rat ``blood_plasma_ratio``,
        an optional directly-predicted rat CL in ``cl_direct`` (mL/min/kg), and an
        optional measured rat Vss in ``vd_human`` (L/kg).
    cl_source : 'microsome' | 'hepatocyte' | 'direct'
        Which in-vitro clearance to drive the prediction from.
    cl_obs : float, optional
        Observed rat CL (mL/min/kg) for the IVIVE correlation / fold error.
    target_type : 'AUC' | 'Cmax' | 'Cmin'
    target_free : free target concentration (nM) or free AUC (nM.h)
    tau_hours : dosing interval (h)
    ka_per_h : first-order absorption rate for the profile (h^-1)
    species : target species key in config.PHYSIOLOGY (default 'rat')

    Returns
    -------
    dict with descriptors, the IVIVE breakdown, rat CL/Vss/F, the rat dose (mg and
    mg/kg), the IVIVE correlation when ``cl_obs`` is given, profile summary, and -
    when ``want_profile`` - the time/free-conc arrays as lists.
    """
    sp = species.strip().lower()
    phys = PHYSIOLOGY[sp]
    bw = phys.bw
    qh = phys.qh
    if scaling is None:
        scaling = units.scaling_for_species(sp)
    src = (cl_source or "microsome").strip().lower()

    out: dict[str, Any] = {"smiles": smiles, "species": sp,
                           "cl_source": src, "error": None}

    feats: MoleculeFeatures = smiles_to_features(
        smiles, logd=logd, ionisation_class=ionisation_class)
    if feats.error:
        out["error"] = f"SMILES error: {feats.error}"
        return out
    out.update({
        "mw": feats.mw, "clogp": feats.clogp, "logd": feats.logd,
        "ionisation_class": feats.ionisation_class, "tpsa": feats.tpsa,
    })

    # ---- pick the in-vitro clearance source ----
    adme = dict(adme)  # shallow copy so we can remap clint without side effects
    if src in _HEP:
        if "clint_hep" in adme and adme["clint_hep"] is not None:
            hv = adme["clint_hep"]
            spec = dict(hv) if isinstance(hv, dict) else {"value": float(hv)}
            spec.setdefault("unit", "uL/min/1e6 cells")
            spec["matrix"] = "hepatocyte"
            adme["clint"] = spec
            adme["matrix"] = "hepatocyte"
        else:
            adme["clint"] = None
        if "fu_hep" in adme and adme.get("fu_hep") is not None and "fu_inc" not in adme:
            adme["fu_inc"] = adme["fu_hep"]
    elif src in _DIRECT:
        adme.pop("clint", None)  # direct CL bypasses IVIVE

    try:
        std = standardise_adme(adme, mw=feats.mw, scaling=scaling)
    except units.UnitError as exc:
        out["error"] = f"Input error: {exc}"
        return out

    if std.fu_p is None:
        out["error"] = "Missing required rat ADME: fu_p"
        return out

    direct = src in _DIRECT
    clint_scaled = cl_u_int = fu_inc = None

    if direct:
        cl_direct = _num(adme.get("cl_direct"))
        if cl_direct is None:
            out["error"] = "cl_source='direct' requires a rat CL in 'cl_direct' (mL/min/kg)"
            return out
        cl_plasma = cl_direct
        clh_blood = cl_plasma / std.blood_plasma_ratio
        eh = min(max(clh_blood / qh, 0.0), 0.999)
    else:
        if std.clint_liver is None:
            need = "clint_hep" if src in _HEP else "clint"
            out["error"] = f"cl_source='{src}' requires {need} and fu_p"
            return out
        fu_inc = resolve_fu_inc(
            std.fu_inc, matrix=std.matrix,
            logp=feats.clogp, logd=feats.logd, ionisation_class=feats.ionisation_class)
        wsm = well_stirred(
            clint_liver=std.clint_liver, fu_inc=fu_inc, fu_p=std.fu_p,
            blood_plasma_ratio=std.blood_plasma_ratio, qh=qh)
        clint_scaled = std.clint_liver
        cl_u_int = wsm["cl_u_int"]
        clh_blood = wsm["clh_blood"]
        cl_plasma = wsm["clh_plasma"]
        eh = wsm["eh"]

    # Bioavailability F = Fa.Fg.Fh (rat first-pass via rat E_H)
    fa = fraction_absorbed(std.permeability_cm_s, getattr(std, "bcs_class", None))
    fg = 1.0
    fh = 1.0 - eh
    f_pred = fa * fg * fh
    f_pct = std.bioavailability_pct if std.bioavailability_pct is not None else f_pred * 100.0

    # Vss: always compute the Oie-Tozer rat prediction (for the Vss correlation);
    # use a measured rat Vss for dosing when available, else the Oie-Tozer value.
    vss_pred_oie = predict_vd("oie_tozer", fu_p=std.fu_p, species=sp).vd_human
    if std.vd_human is not None:
        vd = std.vd_human
        vd_method = "measured (rat IV)"
    else:
        vd = vss_pred_oie
        vd_method = "Oie-Tozer (rat)"

    # observed rat Vss for the correlation: explicit vss_obs, else the measured Vss
    vss_obs_v = _num(vss_obs)
    if vss_obs_v is None and std.vd_human is not None:
        vss_obs_v = std.vd_human
    vss_fold = vss_por = None
    if vss_obs_v and vss_obs_v > 0 and vss_pred_oie and vss_pred_oie > 0:
        vss_por = vss_pred_oie / vss_obs_v
        vss_fold = max(vss_pred_oie, vss_obs_v) / min(vss_pred_oie, vss_obs_v)

    kel = cl_plasma / vd / 1000.0 * 60.0     # 1/h
    if target_type.strip().upper() != "AUC" and (vd is None or vd <= 0):
        out["error"] = f"target_type={target_type} requires a rat Vss"
        return out

    dose = predict_dose(
        target_type=target_type, target_free=target_free, mw=feats.mw,
        fu_human=std.fu_p, cl_human=cl_plasma, vd_human=vd, kel=kel,
        bioavailability_pct=f_pct, tau_hours=tau_hours, bw_kg=bw)

    # Guard: when the rat half-life is far shorter than the dosing interval the
    # trough decays to ~0, so a Cmin/Cmax maintenance dose blows up.
    t_half = (0.693 / kel) if kel > 0 else None
    flag = None
    if (kel and tau_hours and kel * tau_hours > 5.0
            and target_type.strip().upper() not in ("AUC",)):
        flag = (f"t1/2~{t_half:.2f} h << tau={tau_hours:g} h: drug essentially cleared "
                f"between doses, so the {target_type} maintenance dose is extreme / "
                f"unreliable - shorten tau, target AUC, or treat as not dosable to trough.")

    # IVIVE correlation vs observed rat CL
    cl_obs_v = _num(cl_obs)
    ivive_fold = None
    ivive_pred_over_obs = None
    if cl_obs_v and cl_obs_v > 0 and cl_plasma and cl_plasma > 0:
        ivive_pred_over_obs = cl_plasma / cl_obs_v
        ivive_fold = max(cl_plasma, cl_obs_v) / min(cl_plasma, cl_obs_v)

    out.update({
        "matrix": std.matrix if not direct else "direct",
        "fu_inc": fu_inc,
        "fu_p": std.fu_p,
        "blood_plasma_ratio": std.blood_plasma_ratio,
        "clint_liver_mL_min_kg": clint_scaled,
        "cl_u_int_mL_min_kg": cl_u_int,
        "clh_blood_mL_min_kg": clh_blood,
        "cl_rat_plasma_mL_min_kg": cl_plasma,
        "cl_rat_obs_mL_min_kg": cl_obs_v,
        "ivive_pred_over_obs": ivive_pred_over_obs,
        "ivive_fold_error": ivive_fold,
        "E_H": eh,
        "Fa": fa, "Fg": fg, "Fh": fh, "F_pct": f_pct,
        "vss_rat_L_kg": vd,
        "vd_method": vd_method,
        "vss_pred_oie_L_kg": vss_pred_oie,
        "vss_obs_L_kg": vss_obs_v,
        "vss_pred_over_obs": vss_por,
        "vss_fold_error": vss_fold,
        "kel_per_h": kel,
        "t_half_h": t_half,
        "solubility_uM": std.solubility_uM,
        "permeability_cm_s": std.permeability_cm_s,
        "target_type": dose.target_type,
        "target_free_nM": target_free,
        "tau_h": tau_hours,
        "dose_mg": dose.dose_mg,
        "dose_mg_kg": dose.dose_mg / bw if bw else None,
        "flag": flag,
    })

    # ---- Concentration-time profile (rat body weight) ----
    if want_profile and dose.dose_mg and dose.dose_mg > 0:
        try:
            sim = simulate_profile(
                dose_mg=dose.dose_mg, mw=feats.mw, bioavailability_pct=f_pct,
                ka_per_h=ka_per_h, cl_plasma_mL_min_kg=cl_plasma, vd_L_kg=vd,
                tau_h=tau_hours, fu_p=std.fu_p, bw_kg=bw,
                t_end_h=sim_t_end_h, dt_h=sim_dt_h)
            out["profile_cmax_free_nM"] = sim.cmax_free
            out["profile_cmin_free_nM"] = sim.cmin_free
            out["_profile_t_h"] = [round(float(t), 3) for t in sim.t_h]
            out["_profile_free_nM"] = [round(float(c), 5) for c in sim.free_nM]
            out["_profile_total_nM"] = [round(float(c), 5) for c in sim.total_nM]
        except Exception as exc:  # profile failure shouldn't sink the dose row
            out["profile_error"] = f"{type(exc).__name__}: {exc}"

    return out
