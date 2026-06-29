"""
Single-species allometric scaling (SSS) of in vivo animal PK to human.

Transcribed from `Predicted Human Parameter Calcs` (e.g. rat block B4/B5/B6):

    CL_human (mL/min/kg) =
        ( (CL_animal / fu_animal) * BW_animal * (BW_human/BW_animal)**exp
          / BW_human ) * fu_human

    Vd_human (L/kg) = Vd_animal / fu_animal * fu_human
    kel (1/h)       = CL_human / Vd_human / 1000 * 60
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Optional

from .config import PHYSIOLOGY, Assumptions, DEFAULTS


@dataclass
class AllometryResult:
    from_species: str
    cl_human: float   # mL/min/kg, plasma
    vd_human: float   # L/kg
    kel: float        # 1/h


def scale_single_species(
    *,
    from_species: str,
    cl_animal_plasma: float,
    vd_animal: float,
    fu_animal: float,
    fu_human: float,
    assumptions: Assumptions = DEFAULTS,
) -> AllometryResult:
    """Free-fraction-corrected single-species allometry to human CL and Vd."""
    animal = PHYSIOLOGY[from_species.strip().lower()]
    human = PHYSIOLOGY["human"]
    exp = assumptions.allometric_exponent

    cl_human = (
        (cl_animal_plasma / fu_animal)
        * animal.bw
        * (human.bw / animal.bw) ** exp
        / human.bw
    ) * fu_human

    vd_human = vd_animal / fu_animal * fu_human
    kel = cl_human / vd_human / 1000.0 * 60.0

    return AllometryResult(
        from_species=from_species.strip().lower(),
        cl_human=cl_human, vd_human=vd_human, kel=kel,
    )


# --------------------------------------------------------------------------- #
# Multi-species allometry (simple power-law regression across >= 2 species)
# --------------------------------------------------------------------------- #
@dataclass
class MultiSpeciesResult:
    species_used: list[str]
    cl_human: float            # mL/min/kg
    vd_human: float            # L/kg
    cl_exponent: float         # allometric exponent b for CL ~ a*BW^b
    vd_exponent: float
    cl_r2: float
    vd_r2: float
    fu_corrected: bool


def _loglog_fit(bw: list[float], y_abs: list[float]) -> tuple[float, float, float]:
    """Fit log10(y) = log10(a) + b*log10(BW). Return (a, b, r2)."""
    n = len(bw)
    xs = [math.log10(v) for v in bw]
    ys = [math.log10(v) for v in y_abs]
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    log_a = my - b * mx
    # R^2
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (log_a + b * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return 10 ** log_a, b, r2


def multi_species_allometry(
    species_data: Mapping[str, Mapping[str, float]],
    *,
    fu_human: Optional[float] = None,
    fu_correct: bool = False,
    human_bw: float = PHYSIOLOGY["human"].bw,
) -> MultiSpeciesResult:
    """Predict human CL and Vd from multiple animal species by simple allometry.

    species_data : {species: {"cl": mL/min/kg, "vd": L/kg, "fu": fraction?}}
        Needs >= 2 species. `fu` only required when fu_correct=True.
    fu_correct : if True, regress unbound values (CL/fu, Vd/fu) then re-bind with
        fu_human (a fu-corrected MSA). Default False = classic simple allometry.
    """
    species = [s.strip().lower() for s in species_data]
    if len(species) < 2:
        raise ValueError("Multi-species allometry needs at least 2 species")

    bw, cl_abs, vd_abs = [], [], []
    for sp in species:
        d = species_data[sp]
        w = PHYSIOLOGY[sp].bw
        fu = d.get("fu", 1.0) if fu_correct else 1.0
        bw.append(w)
        cl_abs.append(d["cl"] * w / fu)     # mL/min absolute (unbound if fu_correct)
        vd_abs.append(d["vd"] * w / fu)     # L absolute

    _, b_cl, r2_cl = _loglog_fit(bw, cl_abs)
    a_cl, _, _ = _loglog_fit(bw, cl_abs)
    a_vd, b_vd, r2_vd = _loglog_fit(bw, vd_abs)

    cl_human_abs = a_cl * human_bw ** b_cl
    vd_human_abs = a_vd * human_bw ** b_vd
    cl_human = cl_human_abs / human_bw      # back to per-kg
    vd_human = vd_human_abs / human_bw

    if fu_correct:
        if fu_human is None:
            raise ValueError("fu_human required when fu_correct=True")
        cl_human *= fu_human
        vd_human *= fu_human

    return MultiSpeciesResult(
        species_used=species, cl_human=cl_human, vd_human=vd_human,
        cl_exponent=b_cl, vd_exponent=b_vd, cl_r2=r2_cl, vd_r2=r2_vd,
        fu_corrected=fu_correct,
    )


def predict_all_species(
    invivo: Mapping[str, Mapping[str, float]],
    *,
    fu_human: float,
    assumptions: Assumptions = DEFAULTS,
) -> dict:
    """Run single-species scaling for every provided animal + multi-species allometry.

    invivo : {species: {"cl": mL/min/kg, "vd": L/kg, "fu": fraction}}
    Returns a flat dict of columns suitable for merging into a results row.
    """
    out: dict = {}
    for sp, d in invivo.items():
        sp = sp.strip().lower()
        if "fu" not in d:
            continue
        r = scale_single_species(
            from_species=sp, cl_animal_plasma=d["cl"], vd_animal=d["vd"],
            fu_animal=d["fu"], fu_human=fu_human, assumptions=assumptions,
        )
        out[f"cl_human_{sp}_sss"] = r.cl_human
        out[f"vd_human_{sp}_sss"] = r.vd_human
        out[f"kel_{sp}_sss"] = r.kel

    if len(invivo) >= 2:
        msa = multi_species_allometry(invivo, fu_human=fu_human, fu_correct=False)
        out["cl_human_msa"] = msa.cl_human
        out["vd_human_msa"] = msa.vd_human
        out["msa_cl_exponent"] = msa.cl_exponent
        out["msa_cl_r2"] = msa.cl_r2
    return out
