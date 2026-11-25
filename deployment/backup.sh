#!/usr/bin/env bash
# Back up PostgreSQL, the Qdrant collection and uploaded files (docker compose stack).
# Usage (from the project root):  deployment/backup.sh [backup_dir]
set -euo pipefail
DEST="${1:-backups}/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$DEST"
# shellcheck disable=SC1091
source .env
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$DEST/finrag.pgdump"
SNAP_JSON=$(docker compose exec -T qdrant sh -c 'curl -s -X POST http://localhost:6333/collections/finrag_chunks/snapshots')
SNAP=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["result"]["name"])' "$SNAP_JSON")
docker compose cp "qdrant:/qdrant/snapshots/finrag_chunks/$SNAP" "$DEST/finrag_chunks.snapshot"
docker compose cp api:/data/uploads "$DEST/uploads"
sha256sum "$DEST/finrag.pgdump" "$DEST/finrag_chunks.snapshot" > "$DEST/SHA256SUMS"
echo "Backup written to $DEST"
