"""
Diagnose how this CDD Vault returns assay/readout data, so cdd_client._readout_rows
can be pointed at the right endpoint/shape.

Run (PowerShell), with CDD_VAULT_ID/CDD_TOKEN set, for a compound that HAS DMPK data:
    python examples/cdd_probe.py GEN-00XXXXX

It prints: how many protocols resolve, the molecule id, and the raw response from
several candidate data endpoints. Paste the output back. Nothing is modified in CDD.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from dmpk_predictor.cdd_client import CDDClient
from dmpk_predictor.cdd_config import CDDSettings

ident = sys.argv[1] if len(sys.argv) > 1 else None
if not ident:
    sys.exit("Usage: python examples/cdd_probe.py GEN-00XXXXX")

c = CDDClient(CDDSettings())
base = f"{c.s.base_url}/vaults/{c.s.vault_id}"
h = c._headers


def show(label, url, **params):
    try:
        r = requests.get(url, headers=h, params=params or None, timeout=90)
        print(f"\n=== {label}  [{r.status_code}] {r.url}")
        print(r.text[:900])
    except Exception as exc:
        print(f"\n=== {label}  ERROR: {exc}")


# 1) protocols resolve?
protos = c.list_protocols()
print(f"protocols resolved: {len(protos)}")
pid_caco = c._protocol_id("Caco-2 Permeability")
pid_ppb = c._protocol_id("PPB")
pid_ms = c._protocol_id("Metabolic Stability in Liver Microsomes")
print("protocol ids -> Caco-2:", pid_caco, "| PPB:", pid_ppb, "| Microsomes:", pid_ms)

# 2) molecule resolves?
mol = c.resolve_molecule(ident)
mid = mol.get("id")
print("\nmolecule id:", mid, "| name:", mol.get("name"))
print("molecule top-level keys:", list(mol.keys()))

# 3) candidate data endpoints (PPB chosen; swap if the compound lacks PPB)
pid = pid_ppb or pid_caco or pid_ms
show("A readout_rows", f"{base}/readout_rows", molecules=mid, protocols=pid)
show("B protocols/{id}/data", f"{base}/protocols/{pid}/data", molecules=mid)
show("C runs", f"{base}/runs", molecules=mid, protocols=pid)
show("D protocol-data", f"{base}/protocol-data", molecules=mid, protocols=pid)
show("E molecules detail", f"{base}/molecules", molecules=mid,
     include_original_structures="false")
show("F protocols/{id}", f"{base}/protocols/{pid}")
