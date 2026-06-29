#!/usr/bin/env bash
# Launch the V4 RAT Dose Predictor UI on its own port (8510) so it does NOT
# collide with any V1/V2/V3 app on the default 8501.
set -e
cd "$(dirname "$0")"
[ -f ".venv/bin/activate" ] && source .venv/bin/activate
PORT=8510
echo "Starting DMPK RAT Dose Predictor V4 at http://localhost:$PORT"
python -m streamlit run app_rat.py --server.port "$PORT"
