"""
Incubation binding corrections (fu,mic and fu,hep), charge-aware.

Equations transcribed from the `IVIVE calculations` sheet (Austin method block,
cells D25/E25/G25/H25 and the IF switches F25/I25):

Microsomal (protein term 0.5 mg/mL, Austin 2002 form):
    basic         : fu,mic = 1 / (1 + 0.5 * 10**(0.56*logP - 1.41))
    acidic/neutral: fu,mic = 1 / (1 + 0.5 * 10**(0.56*logD - 1.41))

Hepatocyte (cell term 125 * 0.0025 = 0.3125; Kilford/Austin form):
    base/neutral  : fu,hep = 1 / (1 + 0.3125 * 10**(0.072*logP**2 + 0.067*logP - 1.126))
    acidic        : fu,hep = 1 / (1 + 0.3125 * 10**(0.072*logD**2 + 0.067*logD - 1.126))
"""
from __future__ import annotations

from .config import ACIDIC, BASIC

_HEP_COEF = 125.0 * 0.0025  # = 0.3125


def fu_mic(logp: float, logd: float, ionisation_class: str) -> float:
    """Predicted fraction unbound in a microsomal incubation."""
    cls = (ionisation_class or "neutral").strip().lower()
    x = logp if cls == BASIC else logd  # basic uses logP, acid/neutral uses logD
    return 1.0 / (1.0 + 0.5 * 10.0 ** (0.56 * x - 1.41))


def fu_hep(logp: float, logd: float, ionisation_class: str) -> float:
    """Predicted fraction unbound in a hepatocyte incubation."""
    cls = (ionisation_class or "neutral").strip().lower()
    x = logd if cls == ACIDIC else logp  # acidic uses logD, base/neutral uses logP
    return 1.0 / (1.0 + _HEP_COEF * 10.0 ** (0.072 * x ** 2 + 0.067 * x - 1.126))


def resolve_fu_inc(
    measured: float | None,
    *,
    matrix: str,
    logp: float,
    logd: float,
    ionisation_class: str,
) -> float:
    """Return measured fu,inc when provided (>0), else the Austin prediction.

    Mirrors the workbook IF(input==0, predicted, measured) logic. `matrix` is
    'microsome' or 'hepatocyte'.
    """
    if measured is not None and measured > 0:
        return float(measured)
    if matrix == "microsome":
        return fu_mic(logp, logd, ionisation_class)
    if matrix == "hepatocyte":
        return fu_hep(logp, logd, ionisation_class)
    raise ValueError(f"Unknown matrix: {matrix!r}")
