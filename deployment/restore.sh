#!/usr/bin/env bash
# Restore a backup created by backup.sh.  Usage: deployment/restore.sh <backup_dir>
set -euo pipefail
SRC="$1"
# shellcheck disable=SC1091
source .env
sha256sum -c "$SRC/SHA256SUMS"
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists < "$SRC/finrag.pgdump"
docker compose cp "$SRC/finrag_chunks.snapshot" qdrant:/qdrant/snapshots/restore.snapshot
docker compose exec -T qdrant sh -c 'curl -s -X PUT http://localhost:6333/collections/finrag_chunks/snapshots/recover -H "Content-Type: application/json" -d "{\"location\":\"file:///qdrant/snapshots/restore.snapshot\"}"'
docker compose cp "$SRC/uploads/." api:/data/uploads
echo "Restore complete"
