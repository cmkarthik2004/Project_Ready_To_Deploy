#!/usr/bin/env bash
# Start the FinRAG development stack on a single Linux host without Docker.
# Assumes: PostgreSQL 16 installed as a system service, a Qdrant binary, a native
# llama.cpp `llama-server` binary and a GGUF model, backend/.venv and a built frontend.
# Override paths with environment variables. Logs go to $LOG_DIR.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QDRANT_BIN="${QDRANT_BIN:-/opt/qdrant120/qdrant}"
QDRANT_STORAGE="${QDRANT_STORAGE:-/opt/qdrant120/storage}"
LLAMA_SERVER="${LLAMA_SERVER:-/opt/llama/llama-server}"
GGUF="${GGUF:-/opt/models/Qwen3-4B-Q4_K_M.gguf}"
LOG_DIR="${LOG_DIR:-/tmp/finrag_logs}"
mkdir -p "$LOG_DIR"

start() { # name, command...
  local name="$1"; shift
  # running? (ignore this script and the shells that launched it, whose command lines may contain $name)
  local ancestors=" $$ " p=$$
  while [ "$p" -gt 1 ]; do p=$(ps -o ppid= -p "$p" | tr -d ' '); ancestors+="$p "; done
  for pid in $(pgrep -f "$name"); do
    case "$ancestors" in *" $pid "*) ;; *) echo "· $name already running"; return;; esac
  done
  setsid nohup "$@" > "$LOG_DIR/$(echo "$name" | tr -c 'a-zA-Z0-9' _).log" 2>&1 < /dev/null &
  echo "✓ started $name"
}

service postgresql start >/dev/null && echo "✓ postgresql"
(cd "$(dirname "$QDRANT_BIN")" && start "$QDRANT_BIN" env QDRANT__STORAGE__STORAGE_PATH="$QDRANT_STORAGE" QDRANT__SERVICE__HOST=127.0.0.1 "$QDRANT_BIN")
start "llama-server -m" env LD_LIBRARY_PATH="$(dirname "$LLAMA_SERVER")" "$LLAMA_SERVER" -m "$GGUF" --alias qwen3-4b-q4_k_m -c 8192 --host 127.0.0.1 --port 8080 -t "${LLM_THREADS:-4}" -np 1 --cache-ram "${LLM_CACHE_RAM_MB:-1024}"
cd "$ROOT/backend"
.venv/bin/alembic upgrade head >/dev/null && echo "✓ migrations applied"
start "uvicorn app.main" .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
start "app.worker" .venv/bin/python -m app.worker
cd "$ROOT/frontend/.next/standalone"
start "next-server" env PORT=3000 HOSTNAME=127.0.0.1 BACKEND_URL=http://127.0.0.1:8000 node server.js
echo "Web: http://127.0.0.1:3000   API docs: http://127.0.0.1:8000/api/docs"
