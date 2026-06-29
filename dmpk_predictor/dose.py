"""
Human maintenance-dose projection.

Transcribed from the `Dosage Calcs` sheet. The efficacy target is entered as a
FREE concentration; it is converted to total, then to ng/mL using MW, then to a
dose. Three target modes are supported, matching the workbook rows:

    AUC    : Dose = E * CL * 60 * BW / 1e6 / (F/100)
    Cmax   : Dose = E * Vd * 1000 * BW * (1 - exp(-kel*tau)) / (F/100) / 1e6
    Cmin   : Dose = Cmax-form / exp(-kel*tau)

where  E = (target_free / fu_human) * MW / 1000   (total ng/mL, or ng/mL*h for AUC).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .config import PHYSIOLOGY

_BW_HUMAN = PHYSIOLOGY["human"].bw  # 70 kg


@dataclass
class DoseResult:
    target_type: str
    target_free: float
    dose_mg: float


def _total_ngml(target_free: float, fu_human: float, mw: float) -> float:
    """Free conc (nM or nM*h) -> total in ng/mL (or ng/mL*h)."""
    return (target_free / fu_human) * mw / 1000.0


def predict_dose(
    *,
    target_type: str,            # 'AUC' | 'Cmax' | 'Cmin'
    target_free: float,          # free target conc (nM) or free AUC (nM*h)
    mw: float,                   # g/mol
    fu_human: float,             # fraction unbound in plasma (target species)
    cl_human: float,             # mL/min/kg, plasma (target species)
    vd_human: float,             # L/kg (target species)
    kel: float,                  # 1/h
    bioavailability_pct: float,  # F, %
    tau_hours: float,            # dosing interval, h
    bw_kg: float = _BW_HUMAN,    # body weight of the target species (kg)
) -> DoseResult:
    """Compute the maintenance dose (mg) for one efficacy target.

    `bw_kg` selects the target species' body weight. It defaults to 70 kg (human,
    the V1-V3 behaviour); pass 0.25 for the V4 rat dose. The free→total
    conversion, CL/Vd and kel must all be for that same species.
    """
    tt = target_type.strip().upper()
    f_frac = bioavailability_pct / 100.0
    e = _total_ngml(target_free, fu_human, mw)

    if tt == "AUC":
        dose = e * cl_human * 60.0 * bw_kg / 1e6 / f_frac
    elif tt in ("CMAX", "CSS,MAX", "CSSMAX"):
        accum = 1.0 - math.exp(-kel * tau_hours)
        dose = e * vd_human * 1000.0 * bw_kg * accum / f_frac / 1e6
    elif tt in ("CMIN", "CSS,TROUGH", "CSSTROUGH", "CTROUGH"):
        accum = 1.0 - math.exp(-kel * tau_hours)
        decay = math.exp(-kel * tau_hours)
        dose = e * vd_human * 1000.0 * bw_kg * accum / decay / f_frac / 1e6
    else:
        raise ValueError(f"Unknown target_type: {target_type!r}")

    return DoseResult(target_type=tt, target_free=target_free, dose_mg=dose)
