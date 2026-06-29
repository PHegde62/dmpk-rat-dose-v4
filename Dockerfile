# Container for deploying the DMPK RAT Dose Predictor V4 UI to Google Cloud Run.
FROM python:3.11-slim

# RDKit wheels run headless, but a couple of shared libs avoid import surprises.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxrender1 libxext6 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Serve the rat worksheet UI by default. Override at deploy time if needed:
#   --set-env-vars APP_ENTRY=app.py   (legacy human worksheet)
ENV APP_ENTRY=app_rat.py
ENV PYTHONPATH=/app

# Cloud Run injects $PORT (default 8080). Streamlit must bind to it, headless.
ENV PORT=8080
EXPOSE 8080
CMD streamlit run ${APP_ENTRY} \
    --server.port=${PORT} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --browser.gatherUsageStats=false
