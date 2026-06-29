"""
Nucleus REST client — pre-synthesis ML ADME predictions by SMILES (or compound id).

Mirrors the CDD client pattern: token auth, defensive parsing, returns an ADME
dict in the same schema the engine/pipeline expect, plus extras (ML Vdss, logD,
applicability/confidence) and a provenance report of found vs missing fields.

The exact endpoint/JSON is configured in nucleus_config.py, so this code does not
assume a particular Nucleus API beyond "GET a token-authenticated URL that returns
JSON of predictions for one molecule".
"""
from __future__ import annotations

from typing import Any, Optional

try:
    import requests
    _HAS_REQUESTS = True
except Exception:  # pragma: no cover
    _HAS_REQUESTS = False

from .nucleus_config import NucleusSettings, RESPONSE_MAP, CONFIDENCE_KEY


class NucleusError(RuntimeError):
    pass


def _dig(obj: Any, key: str):
    """Fetch key from a dict, supporting dotted paths and {'value':..} cells."""
    cur = obj
    for part in key.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    if isinstance(cur, dict) and "value" in cur:
        return cur["value"]
    return cur


class NucleusClient:
    def __init__(self, settings: Optional[NucleusSettings] = None):
        if not _HAS_REQUESTS:
            raise NucleusError("The 'requests' package is required: pip install requests")
        self.s = settings or NucleusSettings()
        self.s.validate()
        token = f"{self.s.auth_scheme} {self.s.token}".strip() if self.s.auth_scheme else self.s.token
        self._headers = {self.s.auth_header: token, "Accept": "application/json"}

    def _get(self, path: str) -> Any:
        url = self.s.base_url.rstrip("/") + "/" + path.lstrip("/")
        last = None
        for _ in range(3):
            try:
                r = requests.get(url, headers=self._headers, timeout=self.s.timeout_s)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last = exc
                continue
            if r.status_code in (401, 403):
                raise NucleusError(f"Nucleus auth failed ({r.status_code}). Check NUCLEUS_TOKEN.")
            if not r.ok:
                raise NucleusError(f"Nucleus GET failed: {r.status_code} {r.text[:200]}")
            return r.json()
        raise NucleusError(f"Nucleus request timed out after retries") from last

    def fetch_predictions(self, identifier: str, *, is_smiles: bool = True) -> tuple[dict, dict]:
        """Return (adme_dict, info). info has vd_ml, logd, confidence, found, missing."""
        path = self.s.endpoint.format(smiles=identifier, id=identifier)
        payload = self._get(path)
        # endpoints may wrap the record in a list or under a key
        rec = payload
        if isinstance(payload, dict):
            for k in ("prediction", "predictions", "result", "results", "data"):
                if k in payload:
                    rec = payload[k]
                    break
        if isinstance(rec, list):
            rec = rec[0] if rec else {}

        adme: dict[str, Any] = {}
        info: dict[str, Any] = {"id": identifier, "found": [], "missing": [], "vd_ml": None,
                                "logd": None, "confidence": _dig(rec, CONFIDENCE_KEY)}
        for field_name, spec in RESPONSE_MAP.items():
            if not spec:
                continue
            val = _dig(rec, spec["key"])
            if val is None:
                info["missing"].append(field_name)
                continue
            try:
                fval = float(val)
            except (TypeError, ValueError):
                info["missing"].append(field_name)
                continue
            info["found"].append(field_name)
            if field_name == "vd_ml":
                info["vd_ml"] = fval
            elif field_name == "logd":
                info["logd"] = fval
            elif field_name == "clint":
                adme["clint"] = {"value": fval, "unit": spec["unit"],
                                 "matrix": spec.get("matrix", "microsome")}
            elif field_name in ("fu_p", "permeability", "solubility"):
                adme[field_name] = {"value": fval, "unit": spec.get("unit")}
            elif field_name == "blood_plasma_ratio":
                adme[field_name] = fval
        if is_smiles:
            info["smiles"] = identifier
        return adme, info


def fetch_from_nucleus(identifier: str, *, is_smiles: bool = True,
                       settings: Optional[NucleusSettings] = None) -> tuple[dict, dict]:
    """Convenience wrapper: returns (adme_dict, info)."""
    return NucleusClient(settings).fetch_predictions(identifier, is_smiles=is_smiles)
