# smiles-ok-file  (handles user-supplied SMILES; ships no proprietary structures)
"""
V4 batch rat-dose pipeline: many SMILES -> CDD ADME -> rat dose + plasma profile
-> formatted Excel workbook.

Workflow
--------
1. Read a list of compounds (a list of SMILES, a .txt of SMILES, or a .csv with
   ``smiles``/``id`` columns and optional ADME columns).
2. For each compound, pull its RAT ADME from CDD Vault by GEN-ID or SMILES
   (rat liver-microsome CLint, rat fu,p, rat B:P, measured rat Vss/F). Any ADME
   columns supplied in the input table override / fill gaps in the CDD data, so
   the tool also runs fully offline from a spreadsheet.
3. Run the rat dose engine (``rat_dose.predict_rat_dose``) -> rat CL, Vss, F,
   maintenance dose (mg and mg/kg) and a multiple-dose free-plasma profile.
4. Write an Excel workbook: a "Rat Dose Predictions" sheet (one row/compound),
   a "PK Profiles" sheet with every compound's profile + an overlay chart, and a
   "Run Info" sheet.

Use from Python (``run_rat_batch`` / ``rat_batch_to_excel``) or the CLI at the
bottom (``python -m dmpk_predictor.rat_batch ...``).
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional, Sequence, Union

import pandas as pd

from . import units
from .cdd_client import CDDClient, CDDError
from .cdd_config import CDDSettings
from .config import TARGET_SPECIES
from .rat_dose import predict_rat_dose

logger = logging.getLogger("dmpk_predictor.rat_batch")

# Columns the input table may carry to supply / override ADME directly (offline
# use, or to patch gaps in CDD). Mirrors pipeline.build_adme_from_row but adds the
# rat-specific Vss / F slots that the rat engine consumes.
_VALUE_UNIT_COLS = {
    "clint": ("clint_unit", "matrix"),
    "fu_p": ("fu_p_unit", None),
    "fu_inc": ("fu_inc_unit", None),
    "permeability": ("permeability_unit", None),
    "solubility": ("solubility_unit", None),
}
_SCALAR_COLS = ["blood_plasma_ratio", "efflux_ratio", "vd_human", "bioavailability_pct"]
# friendly aliases -> engine ADME keys
_ALIASES = {
    "vd_rat": "vd_human", "vss_rat": "vd_human", "vss": "vd_human",
    "f_rat": "bioavailability_pct", "f_pct": "bioavailability_pct", "f": "bioavailability_pct",
    "bp": "blood_plasma_ratio", "papp": "permeability", "sol": "solubility",
    "clint_mic": "clint",
}


# --------------------------------------------------------------------------- #
# Input loading
# --------------------------------------------------------------------------- #
def load_inputs(source: Union[str, Sequence[Any], pd.DataFrame]) -> pd.DataFrame:
    """Resolve the input into a DataFrame with at least a ``smiles`` column.

    Accepts: a path to .csv/.txt; a DataFrame; a list of SMILES strings; or a
    list of dicts (each with ``smiles``/``id`` + optional ADME columns).
    """
    if isinstance(source, pd.DataFrame):
        df = source.copy()
    elif isinstance(source, str):
        low = source.strip().lower()
        if low.endswith(".csv"):
            df = pd.read_csv(source)
        elif low.endswith((".txt", ".smi")):
            with open(source) as fh:
                df = pd.DataFrame({"smiles": [ln.strip() for ln in fh if ln.strip()]})
        else:  # a single bare SMILES string
            df = pd.DataFrame({"smiles": [source]})
    elif isinstance(source, Sequence):
        rows = list(source)
        if rows and isinstance(rows[0], Mapping):
            df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame({"smiles": [str(s) for s in rows]})
    else:
        raise TypeError(f"Unsupported input type: {type(source)!r}")

    # normalise column names and locate the smiles column
    df.columns = [str(c).strip() for c in df.columns]
    if "smiles" not in {c.lower() for c in df.columns}:
        cand = next((c for c in df.columns if c.lower() in ("smi", "structure")), None)
        if cand:
            df = df.rename(columns={cand: "smiles"})
        else:
            df = df.rename(columns={df.columns[0]: "smiles"})
    # canonicalise the smiles/id column case
    rename = {c: c.lower() for c in df.columns if c.lower() in ("smiles", "id", "smi")}
    return df.rename(columns=rename)


def _adme_from_row(row: Mapping[str, Any]) -> dict:
    """Build an engine ADME dict from any ADME columns present in the input row."""
    def present(key):
        return key in row and pd.notna(row[key]) and str(row[key]).strip() != ""

    # apply aliases (case-insensitive) into a working dict
    norm = {str(k).lower(): v for k, v in row.items()}
    for alias, target in _ALIASES.items():
        if alias in norm and target not in norm:
            norm[target] = norm[alias]
        # carry an alias' unit column too (e.g. clint_mic_unit -> clint_unit)

    adme: dict[str, Any] = {}
    for key, (unit_col, extra_col) in _VALUE_UNIT_COLS.items():
        if key in norm and pd.notna(norm[key]) and str(norm[key]).strip() != "":
            spec: dict[str, Any] = {"value": float(norm[key])}
            if unit_col and norm.get(unit_col):
                spec["unit"] = str(norm[unit_col])
            if extra_col and norm.get(extra_col):
                spec["matrix"] = str(norm[extra_col]).lower()
            adme[key] = spec
    for key in _SCALAR_COLS:
        if key in norm and pd.notna(norm[key]) and str(norm[key]).strip() != "":
            adme[key] = float(norm[key])
    return adme


# --------------------------------------------------------------------------- #
# CDD ADME assembly (rat)
# --------------------------------------------------------------------------- #
def assemble_adme(
    row: Mapping[str, Any],
    *,
    client: Optional[CDDClient],
    prefer_cdd: bool = True,
) -> tuple[dict, dict]:
    """Return (adme, provenance) for one compound.

    Pulls rat ADME from CDD (when a client is given), then folds the measured rat
    in vivo block into the engine slots the rat dose path uses:
      invivo['rat']['vd'] -> vd_human   (preferred rat Vss)
      invivo['rat']['F']  -> bioavailability_pct
      invivo['rat']['fu'] -> fu_p       (only if plasma fu,p wasn't returned)
    ADME columns in the input row override / fill any CDD gaps.
    """
    prov: dict[str, Any] = {"found": [], "missing": [], "source": "input-table",
                            "cl_rat_obs": None}
    adme: dict[str, Any] = {}

    if client is not None:
        ident = None
        is_smiles = False
        rid = row.get("id")
        if rid is not None and str(rid).strip():
            ident, is_smiles = str(rid).strip(), False
        else:
            ident, is_smiles = str(row.get("smiles", "")).strip(), True
        try:
            cdd_adme, cdd_prov = client.fetch_adme(ident, is_smiles=is_smiles)
            adme.update(cdd_adme)
            prov.update(cdd_prov)
            prov["source"] = "CDD"
            invivo = cdd_adme.get("invivo", {}).get("rat", {})
            if "vd" in invivo:
                adme.setdefault("vd_human", invivo["vd"])
            if "F" in invivo:
                adme.setdefault("bioavailability_pct", invivo["F"])
            if "fu" in invivo and "fu_p" not in adme:
                adme["fu_p"] = {"value": invivo["fu"], "unit": "fraction"}
            prov["cl_rat_obs"] = invivo.get("cl")
        except CDDError as exc:
            prov["cdd_error"] = str(exc)

    # input-table ADME overrides / fills gaps
    row_adme = _adme_from_row(row)
    if row_adme:
        adme.update(row_adme)
        if prov["source"] == "input-table":
            prov["found"] = sorted(row_adme.keys())
    return adme, prov


# --------------------------------------------------------------------------- #
# Batch run
# --------------------------------------------------------------------------- #
def run_rat_batch(
    source: Union[str, Sequence[Any], pd.DataFrame],
    *,
    target_type: str = "Cmin",
    target_free_nM: float = 0.0,
    tau_hours: float = 12.0,
    ka_per_h: float = 1.0,
    cl_source: str = "microsome",
    use_cdd: bool = True,
    settings: Optional[CDDSettings] = None,
    sim_t_end_h: float = 48.0,
    species: str = TARGET_SPECIES,
) -> tuple[pd.DataFrame, list[dict]]:
    """Run the rat dose pipeline over many compounds.

    Returns (results_df, profiles) where profiles is a list of per-compound dicts
    {id, smiles, t_h, free_nM} for the compounds that produced a profile.
    """
    df = load_inputs(source)
    client: Optional[CDDClient] = None
    if use_cdd:
        try:
            client = CDDClient(settings)
        except (CDDError, RuntimeError) as exc:
            logger.warning("CDD unavailable, falling back to input-table ADME: %s", exc)
            client = None

    rows: list[dict] = []
    profiles: list[dict] = []
    for i, r in df.iterrows():
        rd = r.to_dict()
        cid = str(rd.get("id") or f"cmpd_{i + 1}")
        smi = str(rd.get("smiles", "")).strip()
        adme, prov = assemble_adme(rd, client=client)
        # observed rat CL for the IVIVE correlation: prefer CDD, else an input column
        cl_obs = prov.get("cl_rat_obs")
        if cl_obs is None:
            for k in ("cl_obs", "cl_rat_obs", "cl_rat"):
                if k in rd and pd.notna(rd[k]) and str(rd[k]).strip() != "":
                    try:
                        cl_obs = float(rd[k]); break
                    except (TypeError, ValueError):
                        pass
        vss_obs = None
        for k in ("vss_obs", "vss_rat_obs"):
            if k in rd and pd.notna(rd[k]) and str(rd[k]).strip() != "":
                try:
                    vss_obs = float(rd[k]); break
                except (TypeError, ValueError):
                    pass
        res = predict_rat_dose(
            smi, adme, target_type=target_type, target_free=target_free_nM,
            tau_hours=tau_hours, ka_per_h=ka_per_h, cl_source=cl_source,
            cl_obs=cl_obs, vss_obs=vss_obs, species=species, sim_t_end_h=sim_t_end_h)
        res = {"id": cid, **res}
        res["adme_source"] = prov.get("source")
        # split the profile arrays out of the flat results row
        t = res.pop("_profile_t_h", None)
        free = res.pop("_profile_free_nM", None)
        res.pop("_profile_total_nM", None)
        if t and free:
            profiles.append({"id": cid, "smiles": smi, "t_h": t, "free_nM": free})
        rows.append(res)

    return pd.DataFrame(rows), profiles


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _main(argv=None):
    import argparse
    from .rat_export import rat_batch_to_excel

    ap = argparse.ArgumentParser(description="Batch rat-dose prediction from SMILES + CDD.")
    ap.add_argument("input", help="SMILES, or path to .csv/.txt of compounds")
    ap.add_argument("-o", "--output", default="rat_dose_predictions.xlsx")
    ap.add_argument("--target-type", default="Cmin", choices=["AUC", "Cmax", "Cmin"])
    ap.add_argument("--target-free", type=float, default=50.0,
                    help="free target concentration in nM (or free AUC nM*h)")
    ap.add_argument("--tau", type=float, default=12.0, help="dosing interval (h)")
    ap.add_argument("--ka", type=float, default=1.0, help="absorption rate ka (1/h)")
    ap.add_argument("--cl-source", default="microsome",
                    choices=["microsome", "hepatocyte", "direct"],
                    help="in-vitro clearance source for IVIVE")
    ap.add_argument("--no-cdd", action="store_true", help="ignore CDD; use input ADME only")
    args = ap.parse_args(argv)

    df, profiles = run_rat_batch(
        args.input, target_type=args.target_type, target_free_nM=args.target_free,
        tau_hours=args.tau, ka_per_h=args.ka, cl_source=args.cl_source,
        use_cdd=not args.no_cdd)
    rat_batch_to_excel(df, profiles, args.output, meta={
        "Target": f"{args.target_type} = {args.target_free} nM (free)",
        "Dosing interval (h)": args.tau, "ka (1/h)": args.ka})
    n_ok = int(df["error"].isna().sum()) if "error" in df else len(df)
    print(f"Wrote {args.output}: {len(df)} compounds ({n_ok} succeeded), "
          f"{len(profiles)} profiles.")


if __name__ == "__main__":
    _main()
