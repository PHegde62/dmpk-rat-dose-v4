<!-- smiles-ok-file  (contains only a public reference SMILES, aspirin) -->
# DMPK Rat Dose Predictor — V4

V4 retargets the predictor from a **human** dose to a **rat** dose, and makes
**batch** prediction the headline workflow:

> **Many SMILES → pull rat ADME from CDD → rat CL / Vss / F / dose + plasma
> concentration–time profiles → one Excel workbook.**

It is forked from V2. The shared calculation engine (well-stirred IVIVE, Austin
incubation binding, mechanistic F = Fa·Fg·Fh, the AUC/Cmax/Cmin dose forms, and
the one-compartment first-order-absorption profile) is **unchanged math** — it is
simply evaluated with **rat physiology**, and there is **no cross-species
allometry**, because the target species *is* the rat.

> ⚠️ Outputs are *predictions*, not measurements. Use them to prioritise and
> design, not as regulatory values.

---

## What changed vs the human tool (V1–V3)

| Step | Human (V1–V3) | Rat (V4) |
|---|---|---|
| Hepatic blood flow Qh | 20.7 mL/min/kg | **80 mL/min/kg** |
| Liver scalars (LW/BW, MPPGL, HPGL) | human | **rat (40 g/kg, 45 mg/g, 117e6/g)** |
| Body weight (dose & profile) | 70 kg | **0.25 kg** |
| Cross-species scaling | allometry up to human | **none — rat in/rat out** |
| Vss | animal-scaled / Øie–Tozer (human volumes) | **measured rat Vss preferred; else Øie–Tozer with rat volumes** |
| Dose reported | mg | **mg and mg/kg** |
| CDD readouts | human assays | **rat assays (RLM CLint, rat PPB, rat B:P, rat IV PK)** |

All rat constants live in `dmpk_predictor/config.py` (`PHYSIOLOGY["rat"]`,
`OIE_TOZER["rat"]`, `TARGET_SPECIES`). Rat Øie–Tozer `Vr = 0.364 L/kg` is from
Waters & Lombardo, *Drug Metab Dispos* 2010;38(7):1159; `Vp`/`Ve` are standard
rat physiological volumes. These are documented, editable defaults — a **measured
rat Vss** from CDD is always preferred over the Øie–Tozer fallback.

---

## Worksheet UI (single compound)
```bash
# Windows: .\run_rat_app.ps1   ·   macOS/Linux: ./run_rat_app.sh
streamlit run app_rat.py --server.port 8510    # then open http://localhost:8510
```
Runs on port **8510** (its own localhost) so it won't clash with a V1/V2/V3 app on
the default 8501. The page title is **🐀 DMPK Rat Dose Predictor — V4**.
`app_rat.py` is the rat worksheet: auto-fill rat ADME from CDD (or type it in),
choose the **in-vitro CL source** (Microsomes / Hepatocytes / Direct rat CL) and
the **Vss method** (measured rat Vss / Øie–Tozer), pick the target (Cmin/Cmax/AUC,
τ, ka), and get the rat dose (mg & mg/kg), a plasma profile, and a **View IVIVE**
panel with the full breakdown and predicted-vs-observed CL (fold-error). Every run
downloads as the V4 Excel workbook. A second tab runs the batch over an uploaded
CSV.

## Batch usage

### CLI
```bash
# from a CSV/TXT of compounds, pulling rat ADME from CDD by GEN-ID or SMILES
python -m dmpk_predictor.rat_batch compounds.csv -o rat_dose_predictions.xlsx \
       --target-type Cmin --target-free 50 --tau 12 --ka 1.0 --cl-source microsome
#   --cl-source = microsome | hepatocyte | direct   (which in-vitro CL drives IVIVE)

# offline (no CDD): supply ADME columns in the input table and add --no-cdd
python -m dmpk_predictor.rat_batch examples/rat_batch_template.csv --no-cdd -o out.xlsx
```

### Python
```python
from dmpk_predictor import run_rat_batch, rat_batch_to_excel

df, profiles = run_rat_batch(
    ["CC(=O)Oc1ccccc1C(=O)O", "Cn1cnc2c1c(=O)n(C)c(=O)n2C"],   # or a .csv / .txt path
    target_type="Cmin", target_free_nM=50.0, tau_hours=12.0, use_cdd=True)
rat_batch_to_excel(df, profiles, "rat_dose_predictions.xlsx")
```

### Input
A `.csv` with a `smiles` column (and optionally `id` = GEN-ID). When CDD is on,
rat ADME is pulled per compound; any ADME columns present in the file
**override / fill gaps**. Recognised ADME columns (all optional):
`clint` (+`clint_unit`,`matrix`), `fu_p`, `blood_plasma_ratio`, `papp`
(+`permeability_unit`), `sol`, `vd_rat` (measured rat Vss, L/kg), `F_rat` (%).
See `examples/rat_batch_template.csv`.

### Output workbook
- **Rat Dose Predictions** — one row per compound: descriptors, the **CL source**,
  rat CLint→CL, E_H, F, rat Vss (+method), kel, t½, rat dose (mg **and** mg/kg),
  profile Cmax/Cmin, observed rat CL with **IVIVE pred/obs + fold-error**, an
  ADME-source tag, and a **Flag** column.
- **PK Profiles** — every compound’s free-plasma concentration vs time, with an
  overlay line chart and the target line.
- **IVIVE** — the per-compound IVIVE breakdown (in-vitro CLint → scaled → CLu,int
  → CLh,blood → CLh,plasma, E_H) plus a **predicted-vs-observed rat-CL scatter
  chart** (with a y=x unity line) for compounds that have an observed CL.
- **Run Info** — settings, method note and caveats.

A **Flag** fires when the rat half-life is far shorter than the dosing interval
(`kel·τ > 5`): the trough decays to ~0 and a Cmin/Cmax maintenance dose becomes
mathematically extreme — shorten τ, target AUC, or treat the compound as not
dosable to that trough. (The same is true in the human engine; V4 surfaces it.)

---

## CDD setup (rat)
Set credentials as environment variables (never hard-code a token):
```
CDD_VAULT_ID, CDD_TOKEN   (CDD_BASE_URL optional)
```
`dmpk_predictor/cdd_config.py` `READOUT_MAP` is mapped to the **rat** species of
each protocol (Liver Microsomes CLint, Microsomal/Hepatocyte binding, PPB, Blood
Partitioning, plus rat IV `PK (Routine)` for measured Vss/CL and rat PO for F).
Adjust the protocol/readout names there to match your vault (`examples/cdd_discover.py`
lists them).

---

## Module 2 (pre-synthesis) — Nucleus / Sapphire (planned)
In V4 the second module is intended to be a **live Nucleus/Sapphire connection**
(not an ML model). The client scaffold is retained in
`dmpk_predictor/nucleus_client.py` / `nucleus_config.py`; wiring it for rat is a
**TODO pending the Sapphire API token + endpoint**. Until then, the rat batch tool
runs entirely on **CDD measured rat ADME** (or an offline ADME table).

## Status / not yet done
- `app_rat.py` is the **rat worksheet UI** (single-compound + batch tabs). The
  inherited `app.py` is the original *human* worksheet, kept for reference.
- The V2 ML stack (`models/`, `data_pipeline/`) was intentionally **dropped** from
  V4 (module 2 becomes Nucleus/Sapphire, not ML).
- Rat Øie–Tozer `Vp`/`Ve` are standard-physiology defaults; confirm against your
  preferred reference if you rely on the Vss fallback rather than measured Vss.

## Layout
```
dmpk_predictor/
  config.py        rat physiology + Øie–Tozer volumes + TARGET_SPECIES
  ivive.py         well-stirred IVIVE (rat Qh)
  vd_predict.py    species-aware Øie–Tozer Vss
  dose.py          species body-weight dose (mg / mg·kg⁻¹)
  bioavailability.py, binding.py, simulate.py, units.py, features.py
  rat_dose.py      ← V4 rat engine (selectable CL source + IVIVE correlation)
  rat_batch.py     ← V4 batch: SMILES → CDD → rat dose + profile
  rat_export.py    ← V4 Excel writer (predictions + profiles + IVIVE + chart)
  cdd_client.py / cdd_config.py   CDD fetch, rat readout map
app_rat.py         ← V4 rat worksheet UI (Streamlit)
examples/rat_batch_template.csv   input template
```
