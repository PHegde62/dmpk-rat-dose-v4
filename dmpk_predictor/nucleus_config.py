"""
Nucleus (ML model store) connection settings + response field mapping.

Pre-synthesis predictions come from Nucleus over a token-authenticated REST API.
Because the exact Nucleus endpoint/JSON differs by deployment, the request shape
and the response->engine-field mapping live here so they can be matched to your
API without touching the client code. Fill in RESPONSE_MAP keys to match the JSON
your endpoint returns (run examples/nucleus_probe.py to see the raw shape).

Environment variables:
    NUCLEUS_BASE_URL   - API base, e.g. https://nucleus.genesistherapeutics.ai/api/v1
    NUCLEUS_TOKEN      - API token
    NUCLEUS_AUTH_HEADER- header name (default "Authorization")
    NUCLEUS_AUTH_SCHEME- scheme prefix (default "Bearer"; set "" for raw token)
    NUCLEUS_ENDPOINT   - path template with {smiles} or {id} (default below)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class NucleusSettings:
    base_url: str = field(default_factory=lambda: os.environ.get("NUCLEUS_BASE_URL", ""))
    token: str = field(default_factory=lambda: os.environ.get("NUCLEUS_TOKEN", ""))
    auth_header: str = field(default_factory=lambda: os.environ.get("NUCLEUS_AUTH_HEADER", "Authorization"))
    auth_scheme: str = field(default_factory=lambda: os.environ.get("NUCLEUS_AUTH_SCHEME", "Bearer"))
    # Path template; {smiles} or {id} is substituted. POST bodies also supported
    # via method="POST" in the client if your API needs it.
    endpoint: str = field(default_factory=lambda: os.environ.get(
        "NUCLEUS_ENDPOINT", "/predictions?smiles={smiles}"))
    timeout_s: int = field(default_factory=lambda: int(os.environ.get("NUCLEUS_TIMEOUT", "60")))

    def validate(self) -> None:
        missing = [k for k, v in (("NUCLEUS_BASE_URL", self.base_url),
                                  ("NUCLEUS_TOKEN", self.token)) if not v]
        if missing:
            raise RuntimeError(f"Missing Nucleus config: {', '.join(missing)}")


# Map each engine input to the JSON key Nucleus returns + its unit.
# >>> EDIT the "key" strings to match your Nucleus prediction payload. <<<
# Set an entry to None to skip it. The model is assumed to predict HUMAN values.
RESPONSE_MAP: dict[str, dict | None] = {
    "clint":        {"key": "pred_human_clint_mic", "unit": "uL/min/mg", "matrix": "microsome"},
    "fu_p":         {"key": "pred_human_fu_p", "unit": "fraction"},
    "blood_plasma_ratio": {"key": "pred_blood_plasma_ratio", "unit": "ratio"},
    "permeability": {"key": "pred_papp", "unit": "1e-6 cm/s"},
    "solubility":   {"key": "pred_solubility_uM", "unit": "uM"},
    # special (not part of the standard ADME dict): used directly by the app
    "vd_ml":        {"key": "pred_vdss_L_kg", "unit": "L/kg"},
    "logd":         {"key": "pred_logd", "unit": ""},
}

# Optional: a model-quality / applicability flag Nucleus may return, surfaced in
# the UI so users heed Erica's "is this method valid for this program?" caveat.
CONFIDENCE_KEY = "applicability_score"
