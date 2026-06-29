"""
CDD Vault REST API client.

Resolves a GEN-ID or SMILES to a CDD molecule, pulls the ADME readouts named in
cdd_config.READOUT_MAP, collapses multiple measurements per the configured
aggregation (default: most recent run), and assembles an ADME dict in the engine
schema (the same dict hybrid.predict_human_dose / pipeline expect).

Auth uses the CDD API token (header ``X-CDD-Token``) from CDDSettings.

NOTE: CDD's exact endpoint paths and JSON field names can vary by API version
and vault configuration. The HTTP calls and response parsing are isolated in the
clearly-marked methods below and written defensively; confirm them against your
vault with cdd_discover.py and adjust the few parse spots if needed.
"""
from __future__ import annotations

import datetime as _dt
import statistics
from typing import Any, Optional

try:
    import requests
    _HAS_REQUESTS = True
except Exception:  # pragma: no cover
    _HAS_REQUESTS = False

from . import units
from .cdd_config import CDDSettings, READOUT_MAP


class CDDError(RuntimeError):
    pass


# Flexible species matching for protocols that store all species in one place
# (matched as a substring, case-insensitive, against the row's Species value).
_SPECIES_ALIASES = {
    "human": ("human", "homo", "hu "),
    "rat": ("rat", "rattus"),
    "dog": ("dog", "canine", "beagle"),
    "cyno": ("cyno", "cynomolgus", "monkey", "macaque", "nhp"),
    "mouse": ("mouse", "murine", "cd1", "cd-1"),
}


def _species_matches(value, target: str) -> bool:
    if value is None:
        return False
    v = str(value).strip().lower()
    return any(alias in v for alias in _SPECIES_ALIASES.get(target, (target,)))


def _row_readouts(row) -> dict:
    """Normalise a readout row into {readout_name: value}, tolerating the
    common CDD shapes (dict keyed by name, dict of {value:..}, or list)."""
    ro = row.get("readouts", row) if isinstance(row, dict) else {}
    out: dict = {}
    if isinstance(ro, dict):
        for k, v in ro.items():
            out[k] = v.get("value") if isinstance(v, dict) and "value" in v else v
    elif isinstance(ro, list):
        for item in ro:
            if isinstance(item, dict):
                name = item.get("name") or item.get("readout") or item.get("readout_name")
                if name is not None:
                    out[name] = item.get("value", item.get("modifier"))
    return out


class CDDClient:
    def __init__(self, settings: Optional[CDDSettings] = None):
        if not _HAS_REQUESTS:
            raise CDDError("The 'requests' package is required: pip install requests")
        self.s = settings or CDDSettings()
        self.s.validate()
        self._headers = {"X-CDD-Token": self.s.token, "Accept": "application/json"}
        self._protocol_cache: Optional[list[dict]] = None
        self._defs_cache: dict[int, dict] = {}   # protocol_id -> {readout_name: id}
        # Row caches avoid re-hitting CDD's slow readout_rows endpoint once per
        # field. _mol_rows_cache holds *all* rows for a molecule (one call);
        # _rows_cache holds the per-protocol slice. _mol_rows_cache[id] is set to
        # None if rows don't carry a protocol id (then we fall back per-protocol).
        self._mol_rows_cache: dict[int, Optional[list[dict]]] = {}
        self._rows_cache: dict[tuple[int, int], list[dict]] = {}

    # ------------------------------------------------------------------ #
    # Low-level HTTP
    # ------------------------------------------------------------------ #
    def _url(self, path: str) -> str:
        return f"{self.s.base_url}/vaults/{self.s.vault_id}/{path.lstrip('/')}"

    def _get(self, path: str, **params) -> Any:
        last_exc = None
        for attempt in range(3):
            try:
                r = requests.get(self._url(path), headers=self._headers,
                                 params=params or None, timeout=self.s.timeout_s)
            except (requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError) as exc:
                last_exc = exc
                continue  # transient; retry
            if r.status_code == 401:
                raise CDDError("CDD auth failed (401). Check CDD_TOKEN / vault access.")
            if not r.ok:
                raise CDDError(f"CDD GET {path} failed: {r.status_code} {r.text[:200]}")
            return r.json()
        raise CDDError(f"CDD GET {path} timed out after 3 attempts "
                       f"(timeout={self.s.timeout_s}s). Try again or raise CDD_TIMEOUT.") from last_exc

    # ------------------------------------------------------------------ #
    # Discovery
    # ------------------------------------------------------------------ #
    def _get_all(self, path: str, page_size: int = 50, **params) -> list[dict]:
        """Fetch every page of a paginated CDD list endpoint."""
        out: list[dict] = []
        offset = 0
        while True:
            data = self._get(path, page_size=page_size, offset=offset, **params)
            if isinstance(data, list):
                objs = data
            else:
                objs = data.get("objects", [])
            out.extend(objs)
            if len(objs) < page_size:
                break
            offset += page_size
        return out

    def list_protocols(self) -> list[dict]:
        """Return ALL protocols (every page) with their readout definitions (cached)."""
        if self._protocol_cache is None:
            self._protocol_cache = self._get_all("protocols", page_size=1000)
        return self._protocol_cache

    # ------------------------------------------------------------------ #
    # Molecule resolution (GEN-ID first, SMILES fallback)
    # ------------------------------------------------------------------ #
    def resolve_molecule(self, identifier: str, *, is_smiles: bool = False) -> dict:
        """Return the best-matching molecule object for a GEN-ID or SMILES.

        Tries name/synonym search first; if nothing is found and a SMILES is
        available, falls back to an exact structure search.
        """
        if not is_smiles:
            data = self._get("molecules", names=identifier)
            objs = data.get("objects", []) if isinstance(data, dict) else data
            if objs:
                return objs[0]
        # structure search fallback (identifier treated as SMILES)
        data = self._get("molecules", structure=identifier,
                         structure_search_type="exact", no_structures="false")
        objs = data.get("objects", []) if isinstance(data, dict) else data
        if not objs:
            raise CDDError(f"No CDD molecule found for {identifier!r}.")
        return objs[0]

    # ------------------------------------------------------------------ #
    # Readout retrieval
    # ------------------------------------------------------------------ #
    def _protocol_id(self, protocol_name: str) -> Optional[int]:
        for p in self.list_protocols():
            if str(p.get("name", "")).strip().lower() == protocol_name.strip().lower():
                return p.get("id")
        return None

    @staticmethod
    def _row_protocol_id(row: dict):
        """Best-effort extraction of a row's protocol id across CDD shapes."""
        for k in ("protocol_id", "protocol"):
            v = row.get(k) if isinstance(row, dict) else None
            if isinstance(v, dict):
                v = v.get("id")
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return v
        return None

    def _all_rows_for_molecule(self, molecule_id: int) -> Optional[list[dict]]:
        """Fetch EVERY readout row for one molecule in a single paginated call
        (cached). Returns None if rows don't expose a protocol id, signalling the
        caller to fall back to per-protocol fetches."""
        if molecule_id not in self._mol_rows_cache:
            rows = self._get_all("readout_rows", page_size=1000, molecules=molecule_id)
            if rows and all(self._row_protocol_id(r) is None for r in rows):
                self._mol_rows_cache[molecule_id] = None      # no protocol id -> can't slice
            else:
                self._mol_rows_cache[molecule_id] = rows
        return self._mol_rows_cache[molecule_id]

    def _readout_rows(self, molecule_id: int, protocol_id: int) -> list[dict]:
        """All readout rows for one molecule within one protocol.

        Pulls the molecule's full row set once (one HTTP call for the whole
        compound) and slices it per protocol, instead of a separate slow
        readout_rows request for every field. Falls back to a targeted
        per-protocol fetch if rows lack a protocol id. Results are cached.

        CDD rows carry `readouts` keyed by readout-definition ID, e.g.
        {"readouts": {"779578": {"value": 0.9, "outlier": false}, ...}}.
        """
        key = (molecule_id, protocol_id)
        if key in self._rows_cache:
            return self._rows_cache[key]
        all_rows = self._all_rows_for_molecule(molecule_id)
        if all_rows is not None:
            rows = [r for r in all_rows if self._row_protocol_id(r) == protocol_id]
        else:
            rows = self._get_all("readout_rows", page_size=1000,
                                 molecules=molecule_id, protocols=protocol_id)
        self._rows_cache[key] = rows
        return rows

    def _readout_def_map(self, protocol_id: int) -> dict:
        """Return {readout_name: readout_definition_id} for a protocol (cached)."""
        if protocol_id not in self._defs_cache:
            mapping = {}
            for p in self.list_protocols():
                if p.get("id") == protocol_id:
                    for rd in p.get("readout_definitions", []) or []:
                        if rd.get("name") is not None:
                            mapping[rd["name"]] = rd.get("id")
                    break
            self._defs_cache[protocol_id] = mapping
        return self._defs_cache[protocol_id]

    @staticmethod
    def _row_date(row: dict):
        for k in ("run_date", "created_at", "modified_at"):
            if row.get(k):
                try:
                    return _dt.datetime.fromisoformat(str(row[k]).replace("Z", "+00:00"))
                except Exception:
                    pass
        return _dt.datetime.min

    def _aggregate(self, values: list[float], rows: list[dict]) -> Optional[float]:
        if not values:
            return None
        how = self.s.aggregation
        if how == "latest":
            latest_row = max(rows, key=self._row_date)
            return latest_row["_value"]
        if how == "mean":
            return statistics.fmean(values)
        if how == "median":
            return statistics.median(values)
        if how == "geomean":
            prod = 1.0
            for v in values:
                prod *= v
            return prod ** (1.0 / len(values))
        return values[0]

    def _value_for(self, molecule_id: int, spec: dict) -> Optional[float]:
        """Pull one readout's aggregated value for a molecule.

        Honours an optional `species` filter (matched against the row's
        `species_readout`, default 'Species') and an optional `filter` dict
        {readout_name: accepted value(s)} (e.g. Route=IV).
        """
        pid = self._protocol_id(spec["protocol"])
        if pid is None:
            return None
        defs = self._readout_def_map(pid)               # readout_name -> def id
        rid = defs.get(spec["readout"])
        if rid is None:
            return None
        species = spec.get("species")
        sid = defs.get(spec.get("species_readout", "Species")) if species else None
        extra_ids = {defs.get(k): v for k, v in (spec.get("filter") or {}).items()}

        def cell_value(readouts: dict, def_id):
            """readouts is keyed by def id (as str); cell may be {'value':..} or scalar."""
            if def_id is None:
                return None
            cell = readouts.get(str(def_id))
            if isinstance(cell, dict):
                return cell.get("value")
            return cell

        rows = self._readout_rows(molecule_id, pid)
        picked_all = []     # species-matched rows with a numeric value
        picked_filt = []    # subset that also matches the extra filter (e.g. Route=IV)
        for row in rows:
            readouts = row.get("readouts", {}) if isinstance(row, dict) else {}
            if species and not _species_matches(cell_value(readouts, sid), species):
                continue
            val = cell_value(readouts, rid)
            if val is None:
                continue
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue
            r2 = dict(row)
            r2["_value"] = fval
            picked_all.append((fval, r2))
            ok = True
            for fid, vals in extra_ids.items():
                accepted = {str(x).strip().lower()
                            for x in (vals if isinstance(vals, (list, tuple)) else [vals])}
                if str(cell_value(readouts, fid)).strip().lower() not in accepted:
                    ok = False
                    break
            if ok:
                picked_filt.append((fval, r2))
        # extra filter (e.g. IV route) is a soft preference: use it when it matches
        # any rows, otherwise fall back to all species-matched rows (so unpopulated
        # Route fields don't wipe out valid CL/Vss data).
        picked = picked_filt if picked_filt else picked_all
        if not picked:
            return None
        return self._aggregate([v for v, _ in picked], [r for _, r in picked])

    # ------------------------------------------------------------------ #
    # Public: build the engine ADME dict
    # ------------------------------------------------------------------ #
    def fetch_adme(self, identifier: str, *, is_smiles: bool = False) -> dict:
        """Resolve a compound and return (adme_dict, provenance).

        provenance lists which engine inputs were found vs missing in CDD.
        """
        mol = self.resolve_molecule(identifier, is_smiles=is_smiles)
        mol_id = mol.get("id")
        adme: dict[str, Any] = {}
        invivo: dict[str, dict] = {}
        found, missing = [], []

        for field, spec in READOUT_MAP.items():
            if not spec:
                continue
            value = self._value_for(mol_id, spec)
            if value is None:
                missing.append(field)
                continue
            found.append(field)
            unit = spec.get("unit")

            if field in ("clint",):
                adme["clint"] = {"value": value, "unit": unit,
                                 "matrix": spec.get("matrix", "microsome")}
            elif field == "clint_hep":
                adme["clint_hep"] = {"value": value, "unit": unit, "matrix": "hepatocyte"}
            elif field in ("fu_inc", "fu_hep", "fu_p", "permeability", "solubility"):
                adme[field] = {"value": value, "unit": unit}
            elif field == "logd_meas":
                adme["logd"] = value
            elif field in ("blood_plasma_ratio", "efflux_ratio"):
                adme[field] = value
            elif "_" in field and field.split("_")[0] in ("cl", "vd", "fu", "F") and \
                    field.split("_")[1] in ("rat", "dog", "cyno", "mouse"):
                metric, sp = field.split("_")[0], field.split("_")[1]
                # animal fu is stored as % unbound in CDD -> convert to fraction;
                # F (bioavailability) is a percent, kept as-is.
                if metric == "fu":
                    value = units.convert_fu(value, spec.get("unit", "fraction"))
                invivo.setdefault(sp, {})[metric] = value

        if invivo:
            # only keep species with at least cl + vd
            adme["invivo"] = {sp: d for sp, d in invivo.items()
                              if "cl" in d and "vd" in d}

        provenance = {
            "molecule_id": mol_id,
            "molecule_name": mol.get("name"),
            "smiles": mol.get("smiles") or mol.get("cdd_smiles"),
            "found": found,
            "missing": missing,
        }
        return adme, provenance


def fetch_adme_from_cdd(identifier: str, *, is_smiles: bool = False,
                        settings: Optional[CDDSettings] = None) -> tuple[dict, dict]:
    """Convenience wrapper: returns (adme_dict, provenance)."""
    return CDDClient(settings).fetch_adme(identifier, is_smiles=is_smiles)
