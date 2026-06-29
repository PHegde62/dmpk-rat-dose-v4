"""
Batch orchestration -> pandas DataFrame.

Accepts a single SMILES, a list of SMILES, or a CSV/TXT file, plus per-compound
experimental ADME inputs, and returns a tidy DataFrame. A failure on one compound
(bad SMILES, impossible input value) is captured in the `error` column instead of
crashing the whole run.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence, Union

import pandas as pd

from . import units
from .hybrid import predict_human_dose

SmilesInput = Union[str, Sequence[str]]


def _load_smiles(source: SmilesInput) -> list[str]:
    """Resolve input into a list of SMILES strings."""
    if isinstance(source, str):
        lowered = source.strip().lower()
        if lowered.endswith((".txt", ".csv")):
            if lowered.endswith(".csv"):
                df = pd.read_csv(source)
                col = next((c for c in df.columns if c.lower() in ("smiles", "smi")), df.columns[0])
                return df[col].astype(str).tolist()
            with open(source) as fh:
                return [ln.strip() for ln in fh if ln.strip()]
        return [source]
    return [str(s) for s in source]


def run_pipeline(
    smiles: SmilesInput,
    adme: Union[Mapping[str, Any], Sequence[Mapping[str, Any]], None] = None,
    *,
    target_type: str = "AUC",
    target_free: float = 0.0,
    tau_hours: float = 24.0,
    scaling: units.ScalingFactors = units.DEFAULT_SCALING,
    ids: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    """Run the hybrid engine over one or many compounds.

    Parameters
    ----------
    smiles : str | list[str]
        A single SMILES, list of SMILES, or path to a .txt/.csv of SMILES.
    adme : dict | list[dict] | None
        ADME inputs. A single dict is reused for every compound; a list must align
        1:1 with the SMILES. See hybrid.predict_human_dose for the schema.
    target_type, target_free, tau_hours : dosing target & interval.
    ids : optional compound identifiers (aligned with SMILES).
    """
    smiles_list = _load_smiles(smiles)
    n = len(smiles_list)

    if adme is None:
        adme_list: list[Mapping[str, Any]] = [{}] * n
    elif isinstance(adme, Mapping):
        adme_list = [adme] * n
    else:
        adme_list = list(adme)
        if len(adme_list) != n:
            raise ValueError(f"adme list length ({len(adme_list)}) != n SMILES ({n})")

    if ids is not None and len(ids) != n:
        raise ValueError("ids length must match number of SMILES")

    rows = []
    for i, (smi, adme_i) in enumerate(zip(smiles_list, adme_list)):
        try:
            res = predict_human_dose(
                smi, dict(adme_i), target_type=target_type, target_free=target_free,
                tau_hours=tau_hours, scaling=scaling,
            )
        except Exception as exc:  # last-resort guard so the batch never crashes
            res = {"smiles": smi, "error": f"Unhandled: {type(exc).__name__}: {exc}"}
        if ids is not None:
            res = {"id": ids[i], **res}
        rows.append(res)

    return pd.DataFrame(rows)


def predict_single(smiles: str, adme: Mapping[str, Any], **kwargs) -> dict:
    """Convenience wrapper for a single compound, returning a plain dict."""
    return predict_human_dose(smiles, dict(adme), **kwargs)


# Columns recognised in an uploaded table. value + optional unit/matrix column.
_VALUE_UNIT_COLS = {
    "clint": ("clint_unit", "matrix"),
    "fu_p": ("fu_p_unit", None),
    "fu_inc": ("fu_inc_unit", None),
    "permeability": ("permeability_unit", None),
    "solubility": ("solubility_unit", None),
}
_SCALAR_COLS = ["blood_plasma_ratio", "efflux_ratio", "vd_human", "bioavailability_pct"]


def build_adme_from_row(row: Mapping[str, Any]) -> dict:
    """Turn one flat table row into an ADME dict for the engine.

    Recognised columns: clint (+clint_unit,+matrix), fu_p (+fu_p_unit),
    fu_inc (+fu_inc_unit), permeability (+permeability_unit),
    solubility (+solubility_unit), blood_plasma_ratio, efflux_ratio, vd_human,
    bioavailability_pct. Missing/blank columns are skipped.
    """
    def present(key):
        return key in row and pd.notna(row[key]) and str(row[key]).strip() != ""

    adme: dict[str, Any] = {}
    for key, (unit_col, extra_col) in _VALUE_UNIT_COLS.items():
        if present(key):
            spec: dict[str, Any] = {"value": float(row[key])}
            if unit_col and present(unit_col):
                spec["unit"] = str(row[unit_col])
            if extra_col and present(extra_col):
                spec["matrix"] = str(row[extra_col]).lower()
            adme[key] = spec
    for key in _SCALAR_COLS:
        if present(key):
            adme[key] = float(row[key])

    # in vivo animal PK for allometry: columns like cl_rat, vd_rat, fu_rat
    invivo: dict[str, dict] = {}
    for sp in ("mouse", "rat", "dog", "cyno"):
        if present(f"cl_{sp}") and present(f"vd_{sp}"):
            entry = {"cl": float(row[f"cl_{sp}"]), "vd": float(row[f"vd_{sp}"])}
            if present(f"fu_{sp}"):
                entry["fu"] = float(row[f"fu_{sp}"])
            invivo[sp] = entry
    if invivo:
        adme["invivo"] = invivo
    return adme


def run_table(
    df: pd.DataFrame,
    *,
    smiles_col: Optional[str] = None,
    id_col: Optional[str] = None,
    **kwargs,
) -> pd.DataFrame:
    """Run the engine over an uploaded DataFrame of SMILES + ADME columns."""
    if smiles_col is None:
        smiles_col = next((c for c in df.columns if c.lower() in ("smiles", "smi")),
                          df.columns[0])
    smiles = df[smiles_col].astype(str).tolist()
    adme = [build_adme_from_row(r) for _, r in df.iterrows()]
    ids = df[id_col].astype(str).tolist() if id_col and id_col in df.columns else None
    return run_pipeline(smiles, adme, ids=ids, **kwargs)
