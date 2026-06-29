# smiles-ok-file  (contains only public reference SMILES: aspirin, caffeine, salicylic acid)
"""
Example: hybrid engine on real SMILES with mixed experimental ADME units.

Demonstrates:
  - RDKit-derived MW used to convert solubility (ug/mL -> uM),
  - CLint given in uL/min/mg standardised to mL/min/kg,
  - PPB entered as "% bound" converted to fraction unbound,
  - permeability entered in nm/s,
  - mechanistic E_H, CL_H, F and the projected human AUC dose,
  - graceful handling of a deliberately invalid SMILES and an impossible fu.

Run:  python examples/run_hybrid_example.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from dmpk_predictor import run_pipeline

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 40)

smiles = [
    "CC(=O)Oc1ccccc1C(=O)O",          # aspirin (acidic)
    "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",   # caffeine (neutral)
    "OC(=O)C1=CC=CC=C1O",             # salicylic acid (acidic)
    "not_a_real_smiles",              # -> captured as error, no crash
]

adme = [
    # aspirin: typical mixed-unit experimental panel
    {"clint": {"value": 25.0, "unit": "uL/min/mg", "matrix": "microsome"},
     "fu_p": {"value": 50.0, "unit": "% bound"},          # 50% bound -> fu 0.5
     "blood_plasma_ratio": 0.9,
     "permeability": {"value": 120.0, "unit": "nm/s"},     # 1.2e-5 cm/s
     "solubility": {"value": 3000.0, "unit": "ug/mL"}},
    {"clint": {"value": 8.0, "unit": "uL/min/mg", "matrix": "microsome"},
     "fu_p": {"value": 0.65, "unit": "fraction"},
     "blood_plasma_ratio": 1.0,
     "permeability": {"value": 30.0, "unit": "nm/s"}},
    {"clint": {"value": 5.0, "unit": "uL/min/1e6 cells", "matrix": "hepatocyte"},
     "fu_p": {"value": 0.2, "unit": "fraction"},
     "blood_plasma_ratio": 0.8},
    {"clint": 1.0, "fu_p": 0.1},  # never reached (bad SMILES)
]

df = run_pipeline(
    smiles, adme,
    target_type="AUC", target_free=5000.0, tau_hours=24.0,
    ids=["aspirin", "caffeine", "salicylic_acid", "broken"],
)

cols = ["id", "mw", "ionisation_class", "fu_p", "clint_liver_mL_min_kg",
        "clh_plasma_mL_min_kg", "E_H", "Fa", "Fh", "F_pct", "dose_mg", "error"]
print(df[[c for c in cols if c in df.columns]].to_string(index=False))

# Demonstrate validation of an impossible input value.
print("\n-- impossible fu (> 1) is caught --")
bad = run_pipeline("CCO", {"clint": 5.0, "fu_p": {"value": 1.5, "unit": "fraction"}})
print(bad[["smiles", "error"]].to_string(index=False))

df.to_csv("examples/hybrid_example_output.csv", index=False)
print("\nwrote examples/hybrid_example_output.csv")
