#!/usr/bin/env bash
# Deploy the DMPK RAT Dose Predictor V4 UI to Google Cloud Run (private/internal).
# Prereqs: gcloud SDK, `gcloud auth login`, project set, APIs enabled
#   gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com
set -euo pipefail

# -------- EDIT THESE --------
PROJECT="genesis-REPLACE-ME"
REGION="us-central1"
SERVICE="dmpk-rat-dose-v4"
CDD_VAULT_ID="5629"
INVOKER="group:dmpk-users@genesistherapeutics.ai"
# ----------------------------

cd "$(dirname "$0")/.."
gcloud config set project "$PROJECT"

# 1) CDD token -> Secret Manager (once; re-run to rotate)
if ! gcloud secrets describe cdd-token >/dev/null 2>&1; then
  echo "Paste your CDD API token, then Ctrl-D:"
  gcloud secrets create cdd-token --data-file=- --replication-policy=automatic
fi

# 2) Build + deploy PRIVATE, token from Secret Manager
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --no-allow-unauthenticated \
  --ingress internal \
  --memory 2Gi --cpu 1 --timeout 900 \
  --set-env-vars "CDD_VAULT_ID=${CDD_VAULT_ID},CDD_BASE_URL=https://app.collaborativedrug.com/api/v1" \
  --set-secrets "CDD_TOKEN=cdd-token:latest"

# 3) Allow the group/user to open it
gcloud run services add-iam-policy-binding "$SERVICE" --region "$REGION" \
  --member="$INVOKER" --role="roles/run.invoker"

echo
echo "Deployed (private). Open it with:"
echo "  gcloud run services proxy $SERVICE --region $REGION --port 8510"
echo "then browse http://localhost:8510"
