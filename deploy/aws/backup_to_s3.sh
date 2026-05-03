#!/usr/bin/env bash
set -euo pipefail
APP_DIR=${APP_DIR:-/opt/worklog}
BACKUP_DIR="$APP_DIR/backups/manual"
STAMP=$(date +%Y%m%d_%H%M%S)
OUT="$BACKUP_DIR/worklog_${STAMP}.tar.gz"
mkdir -p "$BACKUP_DIR"
cd "$APP_DIR"
tar -czf "$OUT" data uploads .env || true
if [[ -n "${S3_BUCKET:-}" ]]; then
  aws s3 cp "$OUT" "s3://${S3_BUCKET}/${S3_PREFIX:-worklog-backups}/$(basename "$OUT")"
fi
echo "Backup generado: $OUT"
