# syntax=docker/dockerfile:1
# FinRAG backend (API + worker). CPU image; see Dockerfile.gpu for CUDA.
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/models/hf
# Debian packages over HTTPS. Optional CA bundle for TLS-intercepting proxies (see below).
RUN --mount=type=secret,id=ca_bundle,required=false,mode=0444 \
    sh -c 'sed -i "s|http://deb.debian.org|https://deb.debian.org|g" /etc/apt/sources.list.d/debian.sources; \
    OPT=""; if [ -f /run/secrets/ca_bundle ]; then OPT="-o Acquire::https::CAInfo=/run/secrets/ca_bundle"; fi; \
    apt-get $OPT update && apt-get $OPT install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng curl \
    && rm -rf /var/lib/apt/lists/*'
WORKDIR /app
COPY requirements.txt .
# Optional: behind a TLS-intercepting proxy pass its CA with  --secret id=ca_bundle,src=/path/ca.crt
RUN --mount=type=secret,id=ca_bundle,required=false,mode=0444 \
    sh -c 'if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu && pip install -r requirements.txt'
COPY . .
RUN useradd --create-home --uid 10001 finrag && mkdir -p /data/uploads /models/hf && chown -R finrag /app /data /models
USER finrag
ENV UPLOAD_DIR=/data/uploads
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD curl -fs http://localhost:8000/api/health || exit 1
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
