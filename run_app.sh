#!/usr/bin/env bash
# Launch the DMPK predictor app. Works locally or inside a GitHub Codespace.
# Usage:  bash run_app.sh
set -e
cd "$(dirname "$0")"
python -m pip install --quiet -r requirements.txt
exec streamlit run app.py --server.port "${PORT:-8501}" --server.address 0.0.0.0
