# Deploy V4 (Rat Dose Predictor UI) to Google Cloud Run

This hosts the Streamlit UI in the cloud so anyone at Genesis opens it in a
**browser** — no local Python, no venv, and Smart App Control never applies.
The service is deployed **private** (only people you grant access to can open it),
and the CDD token lives in **Secret Manager** (never in the image or git).

> You only need this set up once; afterwards a redeploy is a single command.

---

## 0. One-time prerequisites
1. Install the Google Cloud SDK: https://cloud.google.com/sdk/docs/install
2. Sign in and pick the project:
   ```powershell
   gcloud auth login
   gcloud config set project <YOUR_PROJECT_ID>      # e.g. the Genesis GCP project
   ```
3. Enable the APIs used:
   ```powershell
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com
   ```
   (If your account can't do these, ask Genesis IT/Cloud admin — they may need to
   grant you `roles/run.admin`, `roles/cloudbuild.builds.editor`,
   `roles/secretmanager.admin`, and `roles/iam.serviceAccountUser`.)

## 1. Edit the deploy script
Open `deploy\deploy_cloudrun.ps1` and set:
- `$PROJECT` — your GCP project id
- `$REGION` — e.g. `us-central1`
- `$CDD_VAULT_ID` — your CDD vault
- `$INVOKER` — the Google group/user allowed to open the app
  (e.g. `group:dmpk-users@genesistherapeutics.ai` or `user:pooja@genesistherapeutics.ai`)

## 2. Deploy
From the project folder:
```powershell
.\deploy\deploy_cloudrun.ps1
```
What it does: prompts once for your CDD token → stores it in Secret Manager;
builds the container from the `Dockerfile` (Cloud Build, no Docker needed
locally); deploys Cloud Run **private** with the token injected as `CDD_TOKEN`;
grants your group permission to invoke it. (macOS/Linux: `./deploy/deploy_cloudrun.sh`.)

## 3. Open the app
Because it's private, browse it through the authenticated proxy (handles Google
login for you):
```powershell
gcloud run services proxy dmpk-rat-dose-v4 --region us-central1 --port 8510
```
Then open **http://localhost:8510** — the title reads **🐀 DMPK Rat Dose
Predictor — V4**. Anyone you added to `$INVOKER` can run the same proxy command.

## 4. Redeploy after code changes
```powershell
gcloud run deploy dmpk-rat-dose-v4 --source . --region us-central1
```

---

## Access options (pick what suits Genesis)
- **Proxy (default above)** — simplest; each user runs `gcloud run services proxy …`.
  Good for a small team. No public URL.
- **IAP + HTTPS Load Balancer** — gives a real internal URL (e.g.
  `https://ratdose.genesistherapeutics.ai`) gated by Google Identity-Aware Proxy,
  so users just click a link. More setup; ask Cloud admin to front the service
  with a load balancer and enable IAP for your group. Recommended if many users.
- Avoid `--allow-unauthenticated` (that makes it public on the internet) for a
  CDD-connected internal tool.

## Notes
- **Secrets:** the CDD token is in Secret Manager as `cdd-token`; rotate with
  `echo -n NEWTOKEN | gcloud secrets versions add cdd-token --data-file=-`.
- **Network to CDD:** Cloud Run egress can reach CDD's public API by default. If
  Genesis restricts egress, allow `app.collaborativedrug.com`.
- **Cost:** Cloud Run scales to zero — you pay only while it's serving; idle ≈ $0.
- **What's deployed:** `app_rat.py` (rat UI). To serve the legacy human worksheet
  instead, add `--set-env-vars APP_ENTRY=app.py` to the deploy command.
- **Image size:** uses the slim `requirements.txt` (no torch), so builds are fast.
```
