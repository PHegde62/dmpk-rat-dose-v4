"""
Human steady-state volume of distribution (Vdss) prediction.

Three selectable methods (the app exposes all three):
  1. "animal"     - free-fraction-corrected single-species scaling (see allometry.py).
  2. "oie_tozer"  - mechanistic Øie–Tozer model from fu,p and tissue binding fu,t.
  3. "ml"         - a value supplied by an ML model (e.g. from Nucleus); passthrough.

Øie–Tozer (1979), Vss in L/kg:

    Vss = Vp*(1 + Re/i) + fu_p*Vp*(Ve/Vp - Re/i) + Vr*(fu_p / fu_t)

with standard human physiological constants. fu_t (tissue unbound fraction) is
the key unknown: smaller fu_t (more tissue binding) -> larger Vss. If fu_t is not
known it can be approximated (default fu_t = fu_p, i.e. equal tissue/plasma
binding) or estimated from lipophilicity; both are exposed so the user stays in
control of the assumption.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Human physiological volumes (L/kg) and albumin distribution ratio (Øie–Tozer).
VP = 0.0436    # plasma volume
VE = 0.151     # extracellular (extravascular) fluid volume
VR = 0.380     # physical "remainder" (intracellular) volume
RE_I = 1.4     # ratio of extravascular : intravascular albumin


@dataclass
class VdResult:
    vd_human: float        # L/kg
    method: str
    detail: str = ""


def oie_tozer(fu_p: float, fu_t: Optional[float] = None,
              species: str = "human") -> VdResult:
    """Mechanistic Øie–Tozer Vss (L/kg). Defaults fu_t = fu_p if not supplied.

    `species` selects the physiological volumes (config.OIE_TOZER). 'human' uses
    the V1-V3 constants; 'rat' uses the rat volumes for the V4 rat dose. Falls
    back to the module's human constants if the species is unknown.
    """
    if fu_p <= 0:
        raise ValueError("fu_p must be > 0")
    ftissue = fu_t if (fu_t and fu_t > 0) else fu_p
    try:
        from .config import OIE_TOZER
        v = OIE_TOZER[species.strip().lower()]
        vp, ve, vr, re_i = v.vp, v.ve, v.vr, v.re_i
    except (KeyError, ImportError):
        vp, ve, vr, re_i = VP, VE, VR, RE_I
    vss = (vp * (1 + re_i)
           + fu_p * vp * (ve / vp - re_i)
           + vr * (fu_p / ftissue))
    return VdResult(vd_human=vss, method="oie_tozer",
                    detail=f"{species} fu_p={fu_p:.4g}, fu_t={ftissue:.4g}")


def fu_t_from_logp(logp: float, fu_p: float) -> float:
    """Rough fu,t estimate from lipophilicity (more lipophilic -> more tissue binding).

    Transparent placeholder relationship for early use; replace with a fitted
    program-specific model when available. Bounded to (0, fu_p].
    """
    import math
    # heuristic: tissue binding grows ~10x per 2 logP units above 2
    factor = 10 ** (max(0.0, (logp - 2.0)) / 2.0)
    return max(min(fu_p / factor, fu_p), 1e-4)


def predict_vd(
    method: str,
    *,
    # animal single-species
    from_species: Optional[str] = None,
    vd_animal: Optional[float] = None,
    fu_animal: Optional[float] = None,
    fu_human: Optional[float] = None,
    # Øie–Tozer
    fu_p: Optional[float] = None,
    fu_t: Optional[float] = None,
    logp: Optional[float] = None,
    use_logp_for_fut: bool = False,
    # ml passthrough
    ml_value: Optional[float] = None,
    # target species for the Øie–Tozer physiological volumes (V4: 'rat')
    species: str = "human",
) -> VdResult:
    """Unified Vdss selector. method in {'animal','oie_tozer','ml'}."""
    method = method.strip().lower()
    if method == "ml":
        if ml_value is None:
            raise ValueError("ml_value required for ML Vd")
        return VdResult(vd_human=float(ml_value), method="ml", detail="Nucleus ML")
    if method == "oie_tozer":
        ft = fu_t
        if use_logp_for_fut and logp is not None and fu_p:
            ft = fu_t_from_logp(logp, fu_p)
        return oie_tozer(fu_p, ft, species=species)
    if method == "animal":
        if None in (vd_animal, fu_animal, fu_human) or fu_animal <= 0:
            raise ValueError("vd_animal, fu_animal, fu_human required for animal Vd")
        vss = vd_animal / fu_animal * fu_human
        return VdResult(vd_human=vss, method="animal",
                        detail=f"{from_species} free-fraction scaled")
    raise ValueError(f"Unknown Vd method: {method!r}")
