# DMPK Rat Dose Predictor V4 — Setup & GitHub Guide

This sheet covers (1) what this version does, (2) how to run it on your Windows PC,
and (3) how to put it on GitHub. Keep it with the project.

---

## 1. About this version (V4)

**Purpose.** Turn one or many SMILES into a predicted **rat** dose with a plasma
concentration–time profile, pulling rat ADME from CDD Vault. V4 is forked from V2
and re-targets the engine from a human dose to a rat dose — same validated math
(well-stirred IVIVE, Austin incubation binding, F = Fa·Fg·Fh, AUC/Cmax/Cmin dose
forms, one-compartment profile), evaluated with **rat physiology** and **no
cross-species allometry** (rat in → rat out).

**What V4 adds**

| Capability | Where |
|---|---|
| Rat physiology (Qh 80 mL/min/kg, rat liver scalars, BW 0.25 kg) | `dmpk_predictor/config.py` |
| Rat Vss: measured (preferred) or Øie–Tozer with rat volumes (Vr 0.364 L/kg) | `config.py`, `vd_predict.py` |
| Selectable in-vitro CL source: **microsomes / hepatocytes / direct rat CL** | `rat_dose.py` (`cl_source`) |
| Rat dose in **mg and mg/kg** + short-t½ guard flag | `rat_dose.py`, `dose.py` |
| **IVIVE correlation** — predicted vs observed rat **CL** and **Vss** (fold-error) | `rat_dose.py`, Excel `IVIVE` sheet |
| Batch SMILES → CDD → Excel (predictions + PK Profiles + IVIVE + Run Info) | `rat_batch.py`, `rat_export.py` |
| Worksheet UI with dropdowns + "View IVIVE" panel + Excel download | `app_rat.py` |
| CDD readout map pointed at **rat** assays | `cdd_config.py` |

**Excel output sheets:** *Rat Dose Predictions* (one row/compound), *PK Profiles*
(overlay chart), *IVIVE* (breakdown + predicted-vs-observed CL and Vss scatter
charts), *Run Info*.

**Not in V4 (by design / pending):** Module 2 is intended to be a live
**Nucleus/Sapphire** connection (scaffold only; pending API token/endpoint). The
V2 ML stack was dropped. The legacy human worksheet `app.py` is kept for reference.

> ⚠️ Outputs are predictions, not measurements. Hepatic-CL only (no renal/biliary/
> transporter clearance). Validate per program.

---

## 2. Run it on your PC (Windows)

**One-time install**

1. **Install Python 3.10–3.12** from https://www.python.org/downloads/ — on the
   first installer screen tick **“Add python.exe to PATH”**. Verify in PowerShell:
   ```powershell
   python --version
   ```
2. **Open PowerShell in the project folder:**
   ```powershell
   cd "C:\Users\pooja_genesistherape\Claude\Projects\PK and modeling\dmpk-predictor-v4"
   ```
3. **Create and activate a virtual environment** (keeps deps isolated):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
   If activation is blocked, run once:
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` then retry.
4. **Install dependencies:**
   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
   (RDKit installs as a normal wheel on Python 3.10–3.12; no conda needed.)

**Set CDD credentials** (only needed to auto-pull rat ADME; skip for offline use):
```powershell
$env:CDD_VAULT_ID = "5629"          # your numeric vault id
$env:CDD_TOKEN    = "your-api-token" # CDD → My Account → API Token
```
To set them permanently, use Windows “Edit environment variables for your account”.

**Launch the worksheet UI** (runs on its **own port 8510** so it never collides
with a V1/V2/V3 app on the default 8501):
```powershell
.\run_rat_app.ps1
```
Then open **http://localhost:8510** — the title reads **🐀 DMPK Rat Dose
Predictor — V4**. (Equivalent manual command: `streamlit run app_rat.py --server.port 8510`.)
Pick the in-vitro CL source and Vss method, fetch from CDD or type ADME, click
**Predict rat dose**, expand **View IVIVE**, and **Download Excel**.

> If you still see “Human Dose Predictor V3”, that’s an *older app still running*
> on http://localhost:8501 — it’s a separate process. Close that tab/terminal (or
> just use the 8510 URL above); each Streamlit app holds its own port until stopped
> (Ctrl+C in its terminal).

**Run a batch from the command line**
```powershell
python -m dmpk_predictor.rat_batch examples\rat_batch_template.csv `
       -o rat_dose_predictions.xlsx --target-type Cmin --target-free 50 `
       --tau 12 --cl-source microsome
# offline (no CDD): add --no-cdd and put ADME columns in the CSV
```

**Each new session:** `cd` to the folder, run `.\.venv\Scripts\Activate.ps1`, then
`streamlit run app_rat.py`.

### Troubleshooting — "RDKit not installed" / Windows install errors

The app shows "RDKit is not installed" when the Python running Streamlit has no
working RDKit. Three usual causes and fixes:

1. **Unsupported Python version/bitness.** RDKit ships pip wheels for CPython
   **3.10–3.12, 64-bit**. Python **3.13** or a **32-bit** Python often have no
   wheel, so pip errors with *"Could not find a version that satisfies the
   requirement rdkit"*. Check:
   ```powershell
   python --version
   python -c "import struct; print(struct.calcsize('P')*8, 'bit')"
   ```
   If it's 3.13 / 32-bit, install **Python 3.12 (64-bit)** and rebuild the venv:
   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```
2. **Installed into the wrong Python.** Always use `python -m pip` (not bare
   `pip`) inside the activated venv, then verify in the *same* shell:
   ```powershell
   python -m pip install --upgrade pip
   python -m pip install rdkit
   python -c "import rdkit; print('rdkit', rdkit.__version__)"
   ```
   Launch via `.\run_rat_app.ps1` (it activates `.venv`) so Streamlit uses the
   interpreter that has RDKit.
3. **pip just won't cooperate → use conda (most reliable):**
   ```powershell
   conda create -n ratdose python=3.12 -y
   conda activate ratdose
   conda install -c conda-forge rdkit -y
   pip install streamlit pandas numpy openpyxl requests
   streamlit run app_rat.py --server.port 8510
   ```

---

## 3. Put it on GitHub

> **Never commit secrets or large/licensed data.** Don’t commit your CDD token,
> `.streamlit/secrets.toml`, the literature PDFs, or `*.sqlite`/big data files.

**Install Git** (https://git-scm.com/download/win), then set your identity once:
```powershell
git config --global user.name  "Pooja"
git config --global user.email "pooja@genesistherapeutics.ai"
```

**Option A — push just this V4 folder as its own repo**
```powershell
cd "C:\Users\pooja_genesistherape\Claude\Projects\PK and modeling\dmpk-predictor-v4"
git init
git add .
git commit -m "DMPK Rat Dose Predictor V4: rat dose + IVIVE CL/Vss + batch Excel + UI"
```
Create an **empty** repo on github.com (no README), then:
```powershell
git branch -M main
git remote add origin https://github.com/<org-or-user>/dmpk-predictor-v4.git
git push -u origin main
```

**Option B — add it to the existing `logbooks` repo** (as V1/V2 were)
```powershell
cd "C:\path\to\logbooks"
# copy the dmpk-predictor-v4 folder into e.g. personal\Pooja\ , then:
git add personal/Pooja/dmpk-predictor-v4
git commit -m "Add DMPK Rat Dose Predictor V4"
git push
```

**Recommended `.gitignore`** (create in the folder before `git add` if one isn’t
already there):
```
.venv/
__pycache__/
*.pyc
.streamlit/secrets.toml
.env
*.xlsx
*.sqlite
*.pdf
```
> Tip: if you *want* to ship the example workbook, force-add it:
> `git add -f examples\rat_dose_predictions_demo.xlsx`

**Updating later**
```powershell
git add -A
git commit -m "describe your change"
git push
```

**Tag this release** (handy reference point):
```powershell
git tag v4.0.0
git push origin v4.0.0
```

---

## 4. File map
```
dmpk-predictor-v4/
  app_rat.py                  rat worksheet UI (Streamlit)
  requirements.txt            runtime deps (no torch)
  README.md                   overview + usage
  V4_SETUP_AND_GITHUB.md      this sheet
  dmpk_predictor/
    config.py                 rat physiology, Øie–Tozer volumes, TARGET_SPECIES
    rat_dose.py               rat engine: CL source + IVIVE CL/Vss correlation
    rat_batch.py              batch: SMILES → CDD → rat dose + profile
    rat_export.py             Excel writer (predictions + profiles + IVIVE)
    ivive.py / vd_predict.py / dose.py / bioavailability.py / binding.py
    simulate.py / units.py / features.py
    cdd_client.py / cdd_config.py   CDD fetch + rat readout map
  examples/
    rat_batch_template.csv          input template (with ADME + observed CL/Vss)
    rat_dose_predictions_demo.xlsx  example output
```
