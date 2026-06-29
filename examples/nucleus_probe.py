"""
Probe the Nucleus REST API to see the raw prediction JSON for one SMILES, so the
RESPONSE_MAP keys in dmpk_predictor/nucleus_config.py can be matched exactly.

Setup (PowerShell):
    $env:NUCLEUS_BASE_URL = "https://nucleus.genesistherapeutics.ai/api/v1"
    $env:NUCLEUS_TOKEN    = "your-token"
    # optional, if your path differs from the default:
    # $env:NUCLEUS_ENDPOINT = "/predictions?smiles={smiles}"
    python examples/nucleus_probe.py "CCO"

Paste the printed JSON back and the field mapping can be finalised. Read-only.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from dmpk_predictor.nucleus_config import NucleusSettings

smiles = sys.argv[1] if len(sys.argv) > 1 else "CCO"
s = NucleusSettings()
s.validate()
token = f"{s.auth_scheme} {s.token}".strip() if s.auth_scheme else s.token
url = s.base_url.rstrip("/") + "/" + s.endpoint.format(smiles=smiles, id=smiles).lstrip("/")
print("GET", url)
r = requests.get(url, headers={s.auth_header: token, "Accept": "application/json"}, timeout=s.timeout_s)
print("status:", r.status_code)
try:
    print(json.dumps(r.json(), indent=2)[:3000])
except Exception:
    print(r.text[:2000])
