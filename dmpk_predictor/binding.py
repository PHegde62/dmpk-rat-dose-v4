"""
Incubation binding corrections (fu,mic and fu,hep), charge-aware.

Equations transcribed from the `IVIVE calculations` sheet (Austin method block,
cells D25/E25/G25/H25 and the IF switches F25/I25):

Microsomal (Austin 2002 form; protein term = C mg/mL):
    basic         : fu,mic = 1 / (1 + C * 10**(0.56*logP - 1.41))
    acidic/neutral: fu,mic = 1 / (1 + C * 10**(0.56*logD - 1.41))

Hepatocyte (Kilford/Austin form; cell term = VR):
    base/neutral  : fu,hep = 1 / (1 + VR * 10**(0.072*logP**2 + 0.067*logP - 1.126))
    acidic        : fu,hep = 1 / (1 + VR * 10**(0.072*logD**2 + 0.067*logD - 1.126))

The incubation concentrations C (mg microsomal protein / mL) and VR (hepatocyte
cell-volume term) are taken from config so they can be set to the ACTUAL assay
conditions; defaults reproduce the beta-2 workbook (C=0.5, VR=0.3125).

NOTE on lipophilicity input: for BASIC compounds the equations require logP
(not logD). If only logD is available, binding is UNDER-estimated and CL is
correspondingly UNDER-predicted for bases. Supply logP for basic compounds.
"""
from __future__ import annotations

from .config import (
    ACIDIC, BASIC,
    MICROSOME_PROTEIN_MG_PER_ML, HEPATOCYTE_CELL_TERM,
)


def fu_mic(
    logp: float, logd: float, ionisation_class: str,
    protein_mg_per_ml: float = MICROSOME_PROTEIN_MG_PER_ML,
) -> float:
    """Predicted fraction unbound in a microsomal incubation (Austin 2002).

    `protein_mg_per_ml` should equal the microsomal protein concentration used
    in the metabolic-stability assay that produced CLint.
    """
    cls = (ionisation_class or "neutral").strip().lower()
    x = logp if cls == BASIC else logd  # basic uses logP, acid/neutral uses logD
    return 1.0 / (1.0 + protein_mg_per_ml * 10.0 ** (0.56 * x - 1.41))


def fu_hep(
    logp: float, logd: float, ionisation_class: str,
    cell_term: float = HEPATOCYTE_CELL_TERM,
) -> float:
    """Predicted fraction unbound in a hepatocyte incubation (Kilford 2008).

    `cell_term` is the Kilford VR term (= 125 * cell volume fraction); set it to
    match the hepatocyte density used in the assay.
    """
    cls = (ionisation_class or "neutral").strip().lower()
    x = logd if cls == ACIDIC else logp  # acidic uses logD, base/neutral uses logP
    return 1.0 / (1.0 + cell_term * 10.0 ** (0.072 * x ** 2 + 0.067 * x - 1.126))


def resolve_fu_inc(
    measured: float | None,
    *,
    matrix: str,
    logp: float,
    logd: float,
    ionisation_class: str,
    protein_mg_per_ml: float = MICROSOME_PROTEIN_MG_PER_ML,
    cell_term: float = HEPATOCYTE_CELL_TERM,
) -> float:
    """Return measured fu,inc when provided (>0), else the Austin/Kilford prediction.

    Mirrors the workbook IF(input==0, predicted, measured) logic. `matrix` is
    'microsome' or 'hepatocyte'. Prefer a MEASURED fu,inc (CDD "Microsomal
    binding" / "Hepatocyte binding") when one exists.
    """
    if measured is not None and measured > 0:
        return float(measured)
    if matrix == "microsome":
        return fu_mic(logp, logd, ionisation_class, protein_mg_per_ml)
    if matrix == "hepatocyte":
        return fu_hep(logp, logd, ionisation_class, cell_term)
    raise ValueError(f"Unknown matrix: {matrix!r}")
