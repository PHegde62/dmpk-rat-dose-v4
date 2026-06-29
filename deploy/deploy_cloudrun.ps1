# Deploy the DMPK RAT Dose Predictor V4 UI to Google Cloud Run (private/internal).
#
# Prereqs (one time):
#   - Install Google Cloud SDK: https://cloud.google.com/sdk/docs/install
#   - gcloud auth login
#   - gcloud config set project <YOUR_PROJECT_ID>
#   - Enable APIs:  gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com
#
# Run from the project folder:  .\deploy\deploy_cloudrun.ps1
$ErrorActionPreference = "Stop"

# -------- EDIT THESE --------
$PROJECT  = "genesis-REPLACE-ME"          # gcloud config get-value project
$REGION   = "us-central1"
$SERVICE  = "dmpk-rat-dose-v4"
$CDD_VAULT_ID = "5629"                      # your CDD vault id
# Group/user(s) allowed to open the app (least-privilege). Comma-separate if many.
$INVOKER  = "group:dmpk-users@genesistherapeutics.ai"
# ----------------------------

Set-Location -Path (Split-Path $PSScriptRoot -Parent)
gcloud config set project $PROJECT

# 1) Put the CDD API token in Secret Manager (run once; re-run to rotate).
#    You'll be prompted to paste the token (it is NOT stored in this script).
$exists = (gcloud secrets describe cdd-token --format="value(name)" 2>$null)
if (-not $exists) {
    Write-Host "Paste your CDD API token, then press Enter:" -ForegroundColor Cyan
    $tok = Read-Host -AsSecureString
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($tok))
    $plain | gcloud secrets create cdd-token --data-file=- --replication-policy=automatic
}

# 2) Build the container and deploy, PRIVATE (no public access), CDD token from Secret Manager.
gcloud run deploy $SERVICE `
    --source . `
    --region $REGION `
    --no-allow-unauthenticated `
    --ingress internal `
    --memory 2Gi --cpu 1 --timeout 900 `
    --set-env-vars "CDD_VAULT_ID=$CDD_VAULT_ID,CDD_BASE_URL=https://app.collaborativedrug.com/api/v1" `
    --set-secrets "CDD_TOKEN=cdd-token:latest"

# 3) Grant the allowed group/user permission to invoke (open) the service.
gcloud run services add-iam-policy-binding $SERVICE --region $REGION `
    --member="$INVOKER" --role="roles/run.invoker"

Write-Host ""
Write-Host "Deployed (private). To open it in your browser, run:" -ForegroundColor Green
Write-Host "  gcloud run services proxy $SERVICE --region $REGION --port 8510" -ForegroundColor Green
Write-Host "then open http://localhost:8510  (the proxy handles Google auth for you)."
