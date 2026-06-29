"""
In vitro -> in vivo extrapolation (IVIVE) of hepatic clearance.

Blood-based well-stirred model, transcribed from the `IVIVE calculations` sheet:

    CLint,scaled (mL/min/kg) = CLint_in_vitro * MPPGL_or_HPGL * (LW/BW) / 1000
    CLu,int                  = CLint,scaled / fu,inc
    fu,b                     = fu,p / (B:P)
    CLh,blood                = (Qh * fu,b * CLu,int) / (Qh + fu,b * CLu,int)
    CLh,plasma               = CLh,blood * (B:P)

The /1000 converts uL -> mL (the image protocol omitted this factor).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .binding import resolve_fu_inc
from .config import PHYSIOLOGY, Assumptions, DEFAULTS


@dataclass
class HepaticCLResult:
    species: str
    matrix: str               # 'microsome' | 'hepatocyte'
    fu_inc: float
    fu_blood: float
    clint_scaled: float       # mL/min/kg (whole liver)
    cl_u_int: float           # mL/min/kg
    clh_blood: float          # mL/min/kg
    clh_plasma: float         # mL/min/kg


def _apply_fup_floor(fup: float, assumptions: Assumptions) -> float:
    if assumptions.fup_floor is not None:
        return max(fup, assumptions.fup_floor)
    return fup


def well_stirred(
    *,
    clint_liver: float,        # mL/min/kg, whole-liver intrinsic clearance
    fu_inc: float,             # fraction unbound in incubation
    fu_p: float,               # fraction unbound in plasma
    blood_plasma_ratio: float,
    qh: float,                 # hepatic blood flow, mL/min/kg
) -> dict:
    """Blood-based well-stirred model from an already-scaled (mL/min/kg) CLint.

    Returns clh_blood, clh_plasma, cl_u_int, fu_blood and the hepatic extraction
    ratio E_H (= clh_blood / qh).
    """
    cl_u_int = clint_liver / fu_inc
    fu_b = fu_p / blood_plasma_ratio
    clh_blood = (qh * fu_b * cl_u_int) / (qh + fu_b * cl_u_int)
    return {
        "cl_u_int": cl_u_int,
        "fu_blood": fu_b,
        "clh_blood": clh_blood,
        "clh_plasma": clh_blood * blood_plasma_ratio,
        "eh": clh_blood / qh,
    }


def predict_hepatic_cl(
    *,
    species: str,
    matrix: str,
    clint_in_vitro: float,
    fu_p: float,
    blood_plasma_ratio: float,
    logp: float,
    logd: float,
    ionisation_class: str,
    fu_inc_measured: Optional[float] = None,
    assumptions: Assumptions = DEFAULTS,
) -> HepaticCLResult:
    """Predict hepatic clearance from in vitro intrinsic clearance via the WSM.

    Parameters
    ----------
    species : str   one of config.PHYSIOLOGY keys
    matrix : str    'microsome' (CLint in uL/min/mg) or 'hepatocyte' (uL/min/1e6 cells)
    clint_in_vitro : float   raw measured intrinsic clearance
    fu_p : float    fraction unbound in plasma
    blood_plasma_ratio : float
    fu_inc_measured : float, optional   measured fu,inc; if None/0 the Austin
        prediction from logP/logD and ionisation class is used.
    """
    phys = PHYSIOLOGY[species.strip().lower()]
    per_liver = phys.mppgl if matrix == "microsome" else phys.hpgl

    fu_inc = resolve_fu_inc(
        fu_inc_measured, matrix=matrix, logp=logp, logd=logd,
        ionisation_class=ionisation_class,
    )

    clint_scaled = clint_in_vitro * per_liver * phys.lw_per_bw / 1000.0
    cl_u_int = clint_scaled / fu_inc

    fup = _apply_fup_floor(fu_p, assumptions)
    fu_b = fup / blood_plasma_ratio

    clh_blood = (phys.qh * fu_b * cl_u_int) / (phys.qh + fu_b * cl_u_int)
    clh_plasma = clh_blood * blood_plasma_ratio

    return HepaticCLResult(
        species=species.strip().lower(), matrix=matrix, fu_inc=fu_inc,
        fu_blood=fu_b, clint_scaled=clint_scaled, cl_u_int=cl_u_int,
        clh_blood=clh_blood, clh_plasma=clh_plasma,
    )
