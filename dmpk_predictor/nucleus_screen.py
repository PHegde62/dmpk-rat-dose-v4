"""
Ingest a GEMS / Nucleus **Virtual Screen** ADME export (the "Download CSV" from a
screen results page) and map its columns to the engine's inputs.

Why a file, not an API: GEMS is session-cookie authenticated (no headless token)
and predictions are produced by running a Virtual Screen job. The Nucleus team's
recommended path is to create a Virtual Screen (which preprocesses SMILES for the
models) and export the results — this loader reads that export.

Key point on units: the ADME models output **human clearance already scaled to
mL/min/kg** (Microsomal/Hepatocyte Stability (human)), i.e. a predicted human CL,
NOT µL/min/mg microsomal CLint. So these feed the dose engine as a *direct* human
CL (no further IVIVE scaling). PPB is reported as % unbound.

Column matching is fuzzy (normalised, token-contains) so it tolerates the small
differences between the on-screen labels and the CSV headers.
"""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd

# field -> list of token-sets; a column matches if any token-set is fully contained
_COLS = {
    "fu_p_pct_unbound": [["ppb", "human"], ["ppb", "unbound"], ["plasma", "protein", "unbound"]],
    "cl_micro_mlminkg": [["microsomal", "stability", "human"], ["microsom", "stability"]],
    "cl_hep_mlminkg":   [["hepatocyte", "stability", "human"], ["hepatocyte", "stability"]],
    "papp_caco_1e6":    [["caco", "papp", "b"], ["caco", "a", "b", "papp"], ["caco", "papp"]],
    "papp_mdck_1e6":    [["mdck", "papp"]],
    "efflux":           [["caco", "efflux"], ["efflux", "ratio"]],
    "solubility_uM":    [["solubility"]],
    "logd":             [["clogd"], ["logd"]],
    "logp":             [["clogp"], ["logp"]],
    "mw":               [["mol", "weight"], ["molecular", "weight"], ["mw"]],
    "name":             [["cdd", "name"], ["smallmol", "name"], ["compound", "id"], ["smiles"]],
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def _num(x) -> Optional[float]:
    """Extract the first float from a cell (handles '3.5 × 10⁻⁶', '30.4 mL/min/kg', etc.)."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("×", "x").replace("−", "-").replace("⁻", "-")
    m = re.search(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?", s)
    if not m:
        return None
    val = float(m.group())
    # handle "x 10-6" style scientific notation written out
    exp = re.search(r"x\s*10\s*\^?\s*(-?\d+)", s)
    if exp:
        val *= 10 ** int(exp.group(1))
    return val


def _match_columns(columns) -> dict:
    """Return {engine_field: column_name} by fuzzy token matching."""
    norm = {c: _norm(c) for c in columns}
    out = {}
    for field, token_sets in _COLS.items():
        for c, nc in norm.items():
            toks = set(nc.split())
            if any(set(ts).issubset(toks) for ts in token_sets):
                out[field] = c
                break
    return out


def screen_row_to_inputs(row: dict, colmap: dict) -> dict:
    """Map one screen row -> engine prefill dict (units normalised)."""
    def g(field):
        col = colmap.get(field)
        return _num(row.get(col)) if col else None

    p: dict = {}
    name_col = colmap.get("name")
    if name_col and pd.notna(row.get(name_col)):
        p["id"] = str(row[name_col])
    if g("mw") is not None:
        p["mw"] = g("mw")
    if g("logd") is not None:
        p["logd"] = g("logd")
    if g("logp") is not None:
        p["clogp"] = g("logp")
    fu_pct = g("fu_p_pct_unbound")
    if fu_pct is not None:
        p["fu_human"] = max(min(fu_pct / 100.0, 1.0), 1e-4)   # % unbound -> fraction
    if g("papp_caco_1e6") is not None:
        p["papp"] = g("papp_caco_1e6")
    elif g("papp_mdck_1e6") is not None:
        p["papp"] = g("papp_mdck_1e6")
    if g("solubility_uM") is not None:
        p["sol"] = g("solubility_uM")
    # predicted human CL already in mL/min/kg (direct) — prefer microsomal, keep both
    if g("cl_micro_mlminkg") is not None:
        p["cl_direct"] = g("cl_micro_mlminkg")
        p["cl_micro_mlminkg"] = g("cl_micro_mlminkg")
    if g("cl_hep_mlminkg") is not None:
        p["cl_hep_mlminkg"] = g("cl_hep_mlminkg")
        p.setdefault("cl_direct", g("cl_hep_mlminkg"))
    return p


def load_screen_csv(path_or_df) -> tuple[pd.DataFrame, dict]:
    """Load a Virtual Screen export. Returns (raw_df, colmap)."""
    df = path_or_df if isinstance(path_or_df, pd.DataFrame) else (
        pd.read_csv(path_or_df) if str(path_or_df).lower().endswith(".csv")
        else pd.read_excel(path_or_df))
    return df, _match_columns(df.columns)
