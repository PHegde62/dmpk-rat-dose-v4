#!/usr/bin/env bash
# Run the DMPK tool locally with live Nucleus ML autofill.
# Requires the deep-affinity conda env with the internal inference stack.
set -euo pipefail

ENV_NAME="${NUCLEUS_ENV:-deep-affinity}"
PORT="${PORT:-8510}"

# 1) activate the env that has da.adme / virtual_screen
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

# 2) W&B + GCS auth + DB_URL (prod just satisfies the import chain; no DB queries run)
if [ -f "$HOME/.cursor/env.sh" ]; then
  source "$HOME/.cursor/env.sh" prod
else
  echo "WARN: ~/.cursor/env.sh not found — set W&B/GCS auth and DB_URL manually." >&2
fi

# 3) sanity-check the Nucleus stack before launching
python - <<'PY'
try:
    import da.adme, virtual_screen.constants.adme  # noqa
    print("Nucleus stack import: OK")
except Exception as e:
    print("Nucleus stack import FAILED:", repr(e))
    print("  -> the autofill will show 'unavailable' until this import works.")
PY

# 4) UI deps only if missing (don't perturb the pinned inference env)
python -m pip install --no-deps -q streamlit pandas openpyxl matplotlib 2>/dev/null || true

# 5) launch
exec streamlit run app_rat.py --server.port "$PORT"
