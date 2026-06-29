"""
List your CDD Vault's protocols and readout names, so the READOUT_MAP in
dmpk_predictor/cdd_config.py can be filled in to match your vault exactly.

Setup (PowerShell):
    $env:CDD_VAULT_ID = "12345"
    $env:CDD_TOKEN    = "your-api-token"
    python examples/cdd_discover.py

Setup (bash):
    export CDD_VAULT_ID=12345 CDD_TOKEN=your-api-token
    python examples/cdd_discover.py

It prints each protocol and its readout columns. Copy the relevant protocol +
readout names into cdd_config.READOUT_MAP. Nothing is written or modified in CDD.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dmpk_predictor.cdd_client import CDDClient
from dmpk_predictor.cdd_config import CDDSettings


def main() -> None:
    client = CDDClient(CDDSettings())
    protocols = client.list_protocols()
    print(f"Found {len(protocols)} protocols in vault {client.s.vault_id}\n")
    for p in protocols:
        print(f"- PROTOCOL: {p.get('name')!r}  (id={p.get('id')})")
        for rd in p.get("readout_definitions", []) or []:
            unit = rd.get("unit_label") or rd.get("unit") or ""
            print(f"      readout: {rd.get('name')!r}  {('['+unit+']') if unit else ''}")
        print()


if __name__ == "__main__":
    main()
