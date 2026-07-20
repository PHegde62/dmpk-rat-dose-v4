# Running the tool locally with live Nucleus ML (Streamlit)

The Nucleus autofill loads the ADME models **in process**, so Streamlit has to run
inside the same environment where the internal inference stack (`da.adme`,
`virtual_screen.constants.adme`) is importable and authenticated. This is the
`deep-affinity` env used across the Genesis modeling repos — you can't `pip install`
it from public PyPI; you get it from the internal setup. Once you have it, the tool
"just works": the guarded import in `nucleus_ml.py` lights the feature up.

## Prerequisites (once)
1. A working **`deep-affinity`** conda env with the inference stack (the same env the
   NIK boilerplate says to run from). Confirm with:
   ```bash
   conda activate deep-affinity
   python -c "import da.adme, virtual_screen.constants.adme; print('nucleus stack OK')"
   ```
   If that import fails, fix the env first (talk to the ML/infra team) — nothing else
   below will work until it passes.
2. Local clones of the tool repo and (optionally) the logbooks repo:
   ```bash
   git clone https://github.com/PHegde62/dmpk-rat-dose-v4.git
   # optional (only if you want to reuse predict_adme.ADMEPredictor instead of the
   # self-contained path): git -C ~/logbooks pull
   ```

## Every session
```bash
conda activate deep-affinity
# W&B + GCS auth + DB_URL in one shot (prod just satisfies the import chain; no DB queries run):
source ~/.cursor/env.sh prod
# Streamlit + our tool's own deps into this env (only if missing — don't clobber the env):
python -m pip install --no-deps streamlit pandas openpyxl matplotlib
cd dmpk-rat-dose-v4
streamlit run app_rat.py --server.port 8510
```
Open http://localhost:8510 → Worksheet tab → **"Auto-fill from Nucleus ML (SMILES)"**.
Paste a SMILES, pick the species in the sidebar, click **Predict ADME from Nucleus ML** →
CLint / fu / LogD fill in and the mechanistic engine computes the dose.

Optional: `run_local_nucleus.sh` (in this folder) does the activate + auth + run steps.

## Notes / gotchas
- **First prediction is slow (~40 s).** Standardization re-initialises Flint per call
  (UniMol load + protomer/tautomer/3D). Predictions are batched and the model is cached
  per (task, alias), so subsequent scores are ~1–2 s. Score a list, not one-at-a-time.
- **Confirm task keys.** Only `microsomal_stability_human` and `logd` are documented.
  In a Python shell in the env: `import nucleus_ml as n; print(n.available_tasks())`
  and edit `TASK_MAP` in `dmpk_predictor/nucleus_ml.py` to the real mouse/hepatocyte/PPB
  names. Check `n.task_units("ppb_human")` to confirm PPB is % vs fraction (the client
  accepts either, but confirm).
- **Streamlit Community Cloud can't do this.** That host has no `da.adme`/GPU/auth, so the
  autofill will show "unavailable" there. Live Nucleus only works on a machine/VM with the
  deep-affinity env — your laptop (if the env is set up) or an internal/agent VM.
- **Don't rebuild the env with our `requirements.txt`.** Install only the few UI deps you
  actually lack (`--no-deps`) so you don't perturb the pinned inference stack.
