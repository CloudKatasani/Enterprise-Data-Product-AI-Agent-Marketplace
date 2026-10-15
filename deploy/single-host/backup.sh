#!/usr/bin/env bash
# Nightly logical backup of the database to /var/backups/marketplace (7 days
# kept), and to S3 as well when BACKUP_S3_BUCKET is set in .env.
# Restore: gunzip -c <file> | docker compose exec -T postgres psql -U marketplace marketplace
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
DEST=/var/backups/marketplace
mkdir -p "$DEST"
FILE="$DEST/marketplace-$(date -u +%F).sql.gz"
docker compose exec -T postgres pg_dump -U marketplace marketplace | gzip > "$FILE"
find "$DEST" -name 'marketplace-*.sql.gz' -mtime +7 -delete
echo "$(date -u +%FT%TZ) backup written: $FILE"

BUCKET="$(sed -n 's/^BACKUP_S3_BUCKET=//p' .env)"
if [ -n "$BUCKET" ]; then
  aws s3 cp --only-show-errors "$FILE" "s3://$BUCKET/backups/"
  echo "$(date -u +%FT%TZ) backup copied to s3://$BUCKET/backups/"
fi
