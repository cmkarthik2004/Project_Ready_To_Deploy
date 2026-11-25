# Deploying FinRAG on a Linux server

Two supported ways: **Docker Compose** (recommended) or **bare metal** (what the development
environment used). GPU services are optional; the core application runs on CPU.

## Server sizing
| Setup | CPU | RAM | Disk |
|---|---|---|---|
| CPU-only with local Qwen3-4B (llama.cpp) | 4+ cores (8+ recommended) | 16 GB | 20 GB + uploads |
| With a remote LLM (NVIDIA NIM hosted / GPU server) | 2–4 cores | 8 GB | 10 GB + uploads |

Measured on 4 vCPU / 15 GB: a 146-page annual report parses in ~2 min and embeds 750 chunks in
~70 s; a RAG answer takes about 1 minute (median 55 s) with the local 4-bit 4B model on the native llama.cpp server.

## A. Docker Compose
```bash
git clone <your repo> finrag && cd finrag
cp .env.example .env            # then edit: JWT_SECRET, POSTGRES_PASSWORD, CORS_ORIGINS, COOKIE_SECURE
python3 -c "import secrets;print(secrets.token_urlsafe(48))"   # paste as JWT_SECRET
mkdir -p models
curl -L -o models/Qwen3-4B-Q4_K_M.gguf https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf
echo "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5  models/Qwen3-4B-Q4_K_M.gguf" | sha256sum -c
docker compose up -d --build
docker compose ps
curl -s http://127.0.0.1:8000/api/health/ready     # {"database":"ok","qdrant":"ok"}
```
Open `http://<server>:3000`, register — **the first account becomes the administrator** — then set
`ALLOW_REGISTRATION=false` in `.env` if sign-up should be closed, and `docker compose up -d`.

* Migrations run automatically when the `api` container starts (`alembic upgrade head`).
* The embedding and reranker models are downloaded from Hugging Face on first use into the `hf_cache`
  volume (outbound access to `huggingface.co` and its CDN is needed once).
* Put a TLS reverse proxy in front of port 3000 (Caddy, nginx, cloud load balancer) and set
  `COOKIE_SECURE=true`. Only the `web` service is published; the API binds to localhost.
* Logs: `docker compose logs -f api worker` (JSON lines).

## B. Bare metal (Ubuntu 24.04)
```bash
sudo apt-get install -y postgresql-16 tesseract-ocr python3-venv nodejs npm
# PostgreSQL
sudo -u postgres psql -c "CREATE ROLE finrag LOGIN PASSWORD '<strong password>';"
sudo -u postgres psql -c "CREATE DATABASE finrag OWNER finrag;"
# Qdrant 1.20 (binary release)
curl -L https://github.com/qdrant/qdrant/releases/download/v1.20.0/qdrant-x86_64-unknown-linux-gnu.tar.gz | tar xz
QDRANT__SERVICE__HOST=127.0.0.1 ./qdrant &
# Backend
cd backend && python3 -m venv .venv && . .venv/bin/activate
pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
cp ../.env.example ../.env   # edit DATABASE_URL, JWT_SECRET, ...
alembic upgrade head
# LLM: native llama.cpp server (build from https://github.com/ggml-org/llama.cpp with
#   cmake -B build -DGGML_NATIVE=ON -DLLAMA_CURL=OFF && cmake --build build --target llama-server -j)
./llama-server -m /opt/models/Qwen3-4B-Q4_K_M.gguf --alias qwen3-4b-q4_k_m -c 8192 --host 127.0.0.1 --port 8080 -t 4 -np 1 --cache-ram 1024 &
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
python -m app.worker &
# Frontend
cd ../frontend && npm ci && npx next build
cp -r .next/static .next/standalone/.next/static
cd .next/standalone && BACKEND_URL=http://127.0.0.1:8000 PORT=3000 node server.js
```
Run each process under systemd (or supervisord) with `Restart=always` in production.

**Use the native `llama-server`, not the Python `llama_cpp.server` wrapper, in production.** Measured
during development with Qwen3-4B Q4_K_M and an 8k context: the Python wrapper's resident memory grew by
~3.7 GB for a single 5k-token request (≈9 GB total, which triggered the kernel OOM killer twice on a
15 GB host), while the native server stayed at ~3.8 GB across repeated requests and reuses its prompt
cache. The Docker Compose `llm` service already uses the native server image.

## Health checks
* `GET /api/health` — liveness.
* `GET /api/health/ready` — database and Qdrant reachable (HTTP 503 otherwise).
* `GET /api/status` (authenticated) — LLM, embeddings, Qdrant collection, job queue, OCR, GPU.

## Backups
`deployment/backup.sh` (PostgreSQL dump + Qdrant snapshot + uploaded files + SHA-256 sums) and
`deployment/restore.sh`. Example cron: `15 2 * * * cd /srv/finrag && deployment/backup.sh /backups`.
The vector index can also be rebuilt from the stored uploads at any time with **Reprocess**.

## Upgrades
`git pull && docker compose up -d --build` — migrations are applied on start. Qdrant only guarantees
storage compatibility across adjacent minor versions; when jumping several versions, start the new
Qdrant on empty storage and reprocess documents (all vectors are reproducible from uploads).

## Optional components
* **Docling tables**: create a separate venv (`pip install -r backend/requirements-docling.txt`), set
  `PDF_TABLE_ENGINE=docling` and `DOCLING_PYTHON=/path/to/venv/bin/python`.
* **NVIDIA GPU / NIM**: see `docs/NVIDIA.md`.
