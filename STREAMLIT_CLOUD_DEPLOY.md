# Deploy V4 to Streamlit Community Cloud (no GCP, no admin, no secrets)

The fastest way to get the rat-dose UI in a browser. Runs on Streamlit's Linux
servers, so your Windows / Smart App Control / venv problems don't apply. CDD
credentials are entered **in the app** at runtime, so nothing sensitive is stored.

**Prereqs:** a GitHub account, and a free account at https://share.streamlit.io
(sign in with GitHub).

**Checklist**
1. Push **this `dmpk-predictor-v4` folder as the repo root** to GitHub (private is
   fine). `app_rat.py`, `requirements.txt`, and `packages.txt` must be at the root —
   they already are. (Steps in `V4_SETUP_AND_GITHUB.md`.)
2. Go to https://share.streamlit.io → **Create app** → **Deploy a public app from GitHub**.
3. Select your repo and branch `main`; set **Main file path** = `app_rat.py`
   (or `dmpk-predictor-v4/app_rat.py` if you pushed a parent folder).
4. Open **Advanced settings** → set **Python version 3.11** (or 3.12). Leave
   **Secrets empty** — not needed.
5. Click **Deploy**. First build takes a few minutes (it installs `requirements.txt`
   and the `packages.txt` system libs for RDKit). You get a URL like
   `https://<name>.streamlit.app`.
6. (Optional) App → **Settings → Sharing** → restrict viewers to specific Genesis
   emails so it isn't open to anyone with the link.

**Using it:** open the URL → enter rat ADME by hand or upload a CSV (template in
`examples/`). To auto-fill from CDD, tick **Connect to CDD** in the sidebar and
paste your Vault ID + token — they live only in your session, never stored.

**If RDKit fails to import on first deploy:** confirm `packages.txt`
(`libxrender1`, `libxext6`, `libgomp1`) is in the repo root and reboot the app
(Manage app → Reboot). That's the usual fix.
