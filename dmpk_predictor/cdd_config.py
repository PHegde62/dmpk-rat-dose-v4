"""
CDD Vault connection settings + the readout->engine-input mapping.

Two things live here:
  1. CDDSettings  - connection (base URL, vault id, API token) read from env vars.
  2. READOUT_MAP  - maps each engine input to the CDD *protocol name* and
                    *readout (column) name* that holds it, with the source unit.

CDD organises assay data by protocol + readout, and those names are specific to
YOUR vault. Fill in the names below to match your vault (run cdd_discover.py to
list them). Entries left as None are simply skipped (that input stays manual).

Security: never hard-code the API token here. Set environment variables:
    CDD_TOKEN      - your CDD API token (My Account -> API Token)
    CDD_VAULT_ID   - the numeric vault id
    CDD_BASE_URL   - optional; defaults to the US region endpoint
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CDDSettings:
    base_url: str = field(default_factory=lambda: os.environ.get(
        "CDD_BASE_URL", "https://app.collaborativedrug.com/api/v1"))
    vault_id: str = field(default_factory=lambda: os.environ.get("CDD_VAULT_ID", ""))
    token: str = field(default_factory=lambda: os.environ.get("CDD_TOKEN", ""))
    # How to collapse multiple measurements of one readout -> one value.
    # Default 'mean' = average across repeat studies (per user request).
    aggregation: str = "mean"   # 'latest' | 'mean' | 'median' | 'geomean'
    timeout_s: int = field(default_factory=lambda: int(os.environ.get("CDD_TIMEOUT", "90")))

    def validate(self) -> None:
        missing = [k for k, v in (("CDD_VAULT_ID", self.vault_id),
                                   ("CDD_TOKEN", self.token)) if not v]
        if missing:
            raise RuntimeError(
                f"Missing CDD credentials: {', '.join(missing)}. "
                "Set them as environment variables before fetching from CDD.")


# --------------------------------------------------------------------------- #
# Readout map.  Key = engine field; value = how to find it in CDD.
#   protocol : the assay protocol name in your vault
#   readout  : the readout (result column) name within that protocol
#   unit     : the unit the CDD value is in (the engine converts via units.py)
#   matrix   : for CLint only ('microsome' | 'hepatocyte')
#
# >>> EDIT the protocol/readout strings to match your vault. Use cdd_discover.py
#     to print the exact names. Set an entry's value to None to skip it.
# --------------------------------------------------------------------------- #
# Mapped to the real Genesis vault-5629 protocols. Several protocols hold MULTIPLE
# species in one place, distinguished by a "Species" readout column, so those
# entries carry a `species` filter (matched flexibly; see cdd_client aliases).
#
# `_IV` restricts PK (Routine) CL/Vss to intravenous rows (CL and Vss are only
# meaningful from IV dosing); accepts the common spellings of the Route value.
_IV = {"Route": ["IV", "Intravenous", "i.v.", "iv"]}
# `_PO` restricts the bioavailability readout F to oral-dosing rows.
_PO = {"Route": ["PO", "Oral", "oral", "po", "p.o."]}

# V4 RAT readout map. Every in vitro/binding readout is pulled for the RAT
# species so the dose engine receives rat CLint, rat fu,p and rat B:P directly
# (no cross-species scaling). Measured rat Vss / CL / F come from the rat IV/PO
# rows of PK (Routine); the measured rat Vss is preferred over the Øie–Tozer
# fallback, and measured rat CL is reported as an observed cross-check on IVIVE.
READOUT_MAP: dict[str, Optional[dict]] = {
    # --- intrinsic clearance (RAT liver microsomes) ---
    "clint": {"protocol": "Metabolic Stability in Liver Microsomes",
              "readout": "in vitro CLint", "unit": "uL/min/mg",
              "matrix": "microsome", "species": "rat"},
    # microsomal binding -> fu,mic (rat)
    "fu_inc": {"protocol": "Microsomal binding", "readout": "Fu microsome",
               "unit": "fraction", "species": "rat", "matrix": "microsome"},

    # --- hepatocyte route (RAT) ---
    "clint_hep": {"protocol": "Metabolic Stability in Liver Hepatocytes",
                  "readout": "in vitro CLint", "unit": "uL/min/1e6 cells",
                  "matrix": "hepatocyte", "species": "rat"},
    "fu_hep": {"protocol": "Hepatocyte binding", "readout": "Fu hepatocyte",
               "unit": "fraction", "species": "rat"},

    # --- measured lipophilicity (overrides RDKit estimate when present) ---
    "logd_meas": {"protocol": "LogD", "readout": "LogD", "unit": ""},

    # --- plasma protein binding (RAT) ---
    "fu_p": {"protocol": "PPB", "readout": "% Unbound",
             "unit": "% unbound", "species": "rat"},

    # --- blood:plasma (RAT) ---
    "blood_plasma_ratio": {"protocol": "Blood Partitioning (in vitro)",
                           "readout": "Blood to plasma ratio (Kb/p)",
                           "unit": "ratio", "species": "rat"},

    # --- permeability & solubility (species-agnostic) ---
    "permeability": {"protocol": "Caco-2 Permeability",
                     "readout": "Papp (A-B) 10E-06", "unit": "1e-6 cm/s"},
    "efflux_ratio": {"protocol": "Caco-2 Permeability",
                     "readout": "Efflux Ratio", "unit": "ratio"},
    "solubility": {"protocol": "Kinetic Solubility", "readout": "Solubility",
                   "unit": "uM"},

    # --- measured RAT in vivo PK (PK (Routine), IV rows) ---
    "cl_rat": {"protocol": "PK (Routine)", "readout": "Cl_obs (mean)",
               "unit": "mL/min/kg", "species": "rat", "filter": _IV},
    "vd_rat": {"protocol": "PK (Routine)", "readout": "Vss_obs (mean)",
               "unit": "L/kg", "species": "rat", "filter": _IV},
    "fu_rat": {"protocol": "PPB", "readout": "% Unbound",
               "unit": "% unbound", "species": "rat"},

    # --- measured RAT oral bioavailability F (PO rows of PK (Routine)) ---
    "F_rat": {"protocol": "PK (Routine)", "readout": "F (mean)",
              "unit": "%", "species": "rat", "filter": _PO},
}

# Notes / alternatives present in the vault, swap in if preferred:
#   - Hepatocyte CLint: "Metabolic Stability in Liver Hepatocytes" /
#     "in vitro CLint" [uL/min/Mcell] (set matrix="hepatocyte").
#   - Already-scaled CLint: "...Scale-up CLint" [mL/min/kg] (unit "mL/min/kg").
#   - Thermodynamic solubility: "Thermodynamic Solubility" / "Solubility (uM)".
#   - PK (Routine) mixes IV/PO via a "Route" readout; CL/Vss should be IV. A
#     route filter can be added if PO rows contaminate the latest-run pick.
