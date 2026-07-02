"""
Configuration: physiological constants and modelling assumptions.

All physiological constants are transcribed directly from the
`Animal Scaling Factors` sheet of `Prediction Worksheet_with IVIVE_beta 2.xlsx`
so the Python engine reproduces the workbook exactly. Edit values here rather
than in the code so every assumption lives in one place.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class SpeciesPhysiology:
    """Per-species physiological scaling factors."""
    bw: float          # body weight, kg
    lw_per_bw: float   # liver weight / body weight, g liver / kg BW
    qh: float          # hepatic blood flow, mL/min/kg
    mppgl: float       # microsomal protein / liver weight, mg / g liver
    hpgl: float        # hepatocellularity, 1e6 cells / g liver


# Values taken verbatim from `Animal Scaling Factors` (rows 5-9).
PHYSIOLOGY: Dict[str, SpeciesPhysiology] = {
    "mouse": SpeciesPhysiology(bw=0.025, lw_per_bw=50.0, qh=90.0, mppgl=41.5, hpgl=135.0),
    "rat":   SpeciesPhysiology(bw=0.25,  lw_per_bw=40.0, qh=80.0, mppgl=45.0, hpgl=117.0),
    "dog":   SpeciesPhysiology(bw=10.0,  lw_per_bw=32.0, qh=33.0, mppgl=43.0, hpgl=215.0),
    "cyno":  SpeciesPhysiology(bw=3.5,   lw_per_bw=32.0, qh=43.4, mppgl=45.0, hpgl=120.0),
    "human": SpeciesPhysiology(bw=70.0,  lw_per_bw=21.4, qh=20.7, mppgl=40.0, hpgl=139.0),
}


@dataclass
class Assumptions:
    """
    Toggles for the open modelling decisions identified during mapping.
    Defaults reproduce the `beta 2` workbook behaviour.
    """
    # Allometric exponent for single-species scaling (workbook uses 0.75).
    allometric_exponent: float = 0.75
    # Floor on fu,p inside the well-stirred model (image protocol suggested 0.01;
    # the workbook applies NO floor, so default is None to match it).
    fup_floor: float | None = None
    # Heps dose in the workbook uses BLOOD CL while mics uses PLASMA CL.
    # Set True to faithfully reproduce that quirk; False uses plasma CL for both.
    reproduce_heps_blood_cl_quirk: bool = True
    # Number of hours in a dosing interval by regimen.
    tau_hours: Dict[str, float] = field(default_factory=lambda: {"QD": 24.0, "BID": 12.0})


DEFAULTS = Assumptions()

# Recognised ionisation classes (matched case-insensitively, trailing space tolerated).
ACIDIC = "acidic"
BASIC = "basic"
NEUTRAL = "neutral"


# --------------------------------------------------------------------------- #
# In vitro incubation conditions for the Austin/Kilford fu,inc predictions.
# IMPORTANT: set these to the ACTUAL concentrations used in the assay that
# generated CLint, so the binding correction matches the experiment. Defaults
# reproduce the beta-2 workbook (0.5 mg/mL microsomes; 0.3125 hepatocyte term).
# --------------------------------------------------------------------------- #
MICROSOME_PROTEIN_MG_PER_ML: float = 0.5     # mg microsomal protein / mL
HEPATOCYTE_CELL_TERM: float = 125.0 * 0.0025  # = 0.3125 (Kilford cell-volume term)

# Optional empirical IVIVE recovery factor applied to the predicted UNBOUND
# intrinsic clearance to correct residual systematic under-prediction of CL.
# 1.0 = OFF (default, no change). If you enable it, anchor it on a reference set
# of compounds with known in-vivo CL; do NOT fit it on the compounds you are
# predicting (that would be data leakage). Rat NIK+PI3K (mouse-ML inputs) showed
# a residual ~1.3x under-prediction on the microsome path, i.e. a factor ~1.3.
IVIVE_RECOVERY_FACTOR: float = 1.0


# --------------------------------------------------------------------------- #
# V4 - target species for dose prediction.
# V1-V3 predicted a HUMAN dose (scaling animal data up to human). V4 predicts a
# RAT dose directly: rat in vitro / in vivo data -> rat CL, Vss, F, dose, with NO
# cross-species allometry (the target species IS rat). Change TARGET_SPECIES to
# scale the whole tool to another species; every constant below is keyed by it.
# --------------------------------------------------------------------------- #
TARGET_SPECIES = "mouse"   # V6: evaluate MOUSE PK (mouse ML models -> mouse PK, same-species)


@dataclass(frozen=True)
class OieTozerVolumes:
    """Per-species physiological volumes for the Oie-Tozer Vss model (L/kg)."""
    vp: float        # plasma volume
    ve: float        # extravascular (extracellular) fluid volume
    vr: float        # physical "remainder" (intracellular) volume
    re_i: float      # ratio of extravascular : intravascular albumin


# Human values are the originals used in V1-V3 (Oie & Tozer 1979).
# Rat values: Vr = 0.364 L/kg from Waters & Lombardo, Drug Metab Dispos 2010;
# 38(7):1159 (Oie-Tozer applied across species); Vp and Ve are standard rat
# physiological volumes (plasma ~0.0312 L/kg; extracellular ~0.20 L/kg). Re/i is
# held at 1.4 (albumin distribution is not strongly species-dependent). These are
# documented, adjustable defaults - PREFER a measured rat Vss when one exists.
# Pre-synthesis Vss: the tissue unbound fraction fu,t is derived MECHANISTICALLY
# from lipophilicity via the Austin/Kilford incubation-binding curve (binding.py),
# then scaled to whole tissue by a single calibrated constant:
#     fu,t = FUT_FUINC_SCALAR[species] * fu,inc(logP/logD)
# Calibrate ONCE on a training set (back-calculate fu,t from observed Vss, take the
# geometric-mean ratio fu,t / fu,inc) and deploy on new compounds - this keeps the
# pre-synthesis module ML-only (no measured binding needed). Re-fit per species /
# program. Rat (NIK+PI3K, microsome route, LOO): ~0.010 -> AFE 1.0, GMFE 1.95.
FUT_FUINC_SCALAR: Dict[str, float] = {"mouse": 0.008, "rat": 0.010, "human": 0.010}


OIE_TOZER: Dict[str, OieTozerVolumes] = {
    "human": OieTozerVolumes(vp=0.0436, ve=0.151, vr=0.380, re_i=1.4),
    "rat":   OieTozerVolumes(vp=0.0312, ve=0.200, vr=0.364, re_i=1.4),
    # Mouse volumes (L/kg): plasma ~0.05, interstitial ~0.23, remainder ~0.42
    # (sum ~0.70 = mouse total body water); Re/i held at 1.4.
    "mouse": OieTozerVolumes(vp=0.05, ve=0.23, vr=0.42, re_i=1.4),
}
