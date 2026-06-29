"""
Oral bioavailability: F = Fa · Fg · Fh.

  Fh (fraction escaping hepatic first pass) = 1 - CLh,blood / Qh   (well-stirred)
  Fa (fraction absorbed)  — permeability-driven, capped by a BCS-class solubility
                            limit for poorly soluble classes (2 and 4).
  Fg (fraction escaping gut metabolism) — assumed 1 unless supplied.

The BCS caps are deliberately simple, documented, and adjustable; they encode the
"absorption-limited" behaviour Erica described for BCS class 2/3/4 compounds, not
a full dissolution/permeation simulation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Default Fa ceiling per BCS class (solubility-limited classes 2 & 4 < 1).
# 1: high sol/high perm, 2: low sol/high perm, 3: high sol/low perm, 4: low sol/low perm.
BCS_FA_CAP = {1: 1.0, 2: 0.75, 3: 1.0, 4: 0.5}
PAPP_HALF_CM_S = 1e-6   # Papp giving Fa(perm)=0.5


@dataclass
class FResult:
    Fa: float
    Fg: float
    Fh: float
    F: float
    detail: str = ""


def fraction_absorbed(papp_cm_s: Optional[float] = None,
                      bcs_class: Optional[int] = None,
                      fa_cap: Optional[float] = None) -> float:
    """Permeability-driven Fa, capped by BCS-class solubility limit."""
    if papp_cm_s is None:
        fa_perm = 1.0
    else:
        fa_perm = papp_cm_s / (papp_cm_s + PAPP_HALF_CM_S)   # 0.5 at 1e-6 cm/s
    cap = fa_cap if fa_cap is not None else BCS_FA_CAP.get(bcs_class, 1.0)
    return max(0.0, min(fa_perm, cap))


def fraction_escaping_hepatic(clh_blood_mL_min_kg: float, qh_mL_min_kg: float = 20.7) -> float:
    if not qh_mL_min_kg:
        return 1.0
    return max(0.0, 1.0 - clh_blood_mL_min_kg / qh_mL_min_kg)


def predict_bioavailability(
    *,
    clh_blood_mL_min_kg: float,
    qh_mL_min_kg: float = 20.7,
    papp_cm_s: Optional[float] = None,
    bcs_class: Optional[int] = None,
    fg: float = 1.0,
    fa_cap: Optional[float] = None,
) -> FResult:
    """Combine Fa·Fg·Fh into an oral bioavailability estimate (fraction, 0-1)."""
    fh = fraction_escaping_hepatic(clh_blood_mL_min_kg, qh_mL_min_kg)
    fa = fraction_absorbed(papp_cm_s, bcs_class, fa_cap)
    f = fa * fg * fh
    return FResult(Fa=fa, Fg=fg, Fh=fh, F=f,
                   detail=f"Fa={fa:.2f}·Fg={fg:.2f}·Fh={fh:.2f}")
