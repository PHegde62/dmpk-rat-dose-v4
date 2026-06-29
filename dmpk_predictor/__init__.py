"""
dmpk_predictor (V4): SMILES + experimental ADME -> RAT PK, dose & plasma profile.

V4 retargets the engine from a human dose to a RAT dose. The shared math
(well-stirred IVIVE, Austin incubation binding, mechanistic F = Fa·Fg·Fh, the
AUC/Cmax/Cmin dose forms, the 1-compartment profile) is unchanged; it is now
evaluated with rat physiology (Qh, liver scalars, body weight, Øie–Tozer volumes)
and there is no cross-species allometry — the target species is the rat.

The headline V4 entry points are ``predict_rat_dose`` (one compound) and
``run_rat_batch`` + ``rat_batch_to_excel`` (many SMILES -> CDD -> Excel with
plasma profiles). The original human path (``predict_human_dose``) is retained
unchanged for reference.
"""
from .config import PHYSIOLOGY, Assumptions, DEFAULTS, TARGET_SPECIES, OIE_TOZER
from .features import smiles_to_features, MoleculeFeatures
from .binding import fu_mic, fu_hep, resolve_fu_inc
from .ivive import predict_hepatic_cl, well_stirred, HepaticCLResult
from .allometry import scale_single_species, AllometryResult
from .dose import predict_dose, DoseResult
from .hybrid import predict_human_dose, standardise_adme, StandardADME
from .rat_dose import predict_rat_dose
from .rat_batch import run_rat_batch, load_inputs, assemble_adme
from .rat_export import (rat_batch_to_excel, rat_batch_to_excel_bytes,
                         rat_batch_to_workbook)
from .pipeline import run_pipeline, predict_single, run_table, build_adme_from_row
from .export import results_to_excel_bytes, results_to_workbook
from .cdd_client import fetch_adme_from_cdd, CDDClient, CDDError
from .cdd_config import CDDSettings, READOUT_MAP
from . import units

__all__ = [
    "PHYSIOLOGY", "Assumptions", "DEFAULTS", "TARGET_SPECIES", "OIE_TOZER",
    "smiles_to_features", "MoleculeFeatures",
    "fu_mic", "fu_hep", "resolve_fu_inc",
    "predict_hepatic_cl", "well_stirred", "HepaticCLResult",
    "scale_single_species", "AllometryResult",
    "predict_dose", "DoseResult",
    "predict_human_dose", "standardise_adme", "StandardADME",
    "predict_rat_dose", "run_rat_batch", "load_inputs", "assemble_adme",
    "rat_batch_to_excel", "rat_batch_to_excel_bytes", "rat_batch_to_workbook",
    "run_pipeline", "predict_single", "run_table", "build_adme_from_row",
    "results_to_excel_bytes", "results_to_workbook",
    "fetch_adme_from_cdd", "CDDClient", "CDDError", "CDDSettings", "READOUT_MAP",
    "units",
]
__version__ = "4.0.0"
