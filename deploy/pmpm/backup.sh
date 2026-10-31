#!/usr/bin/env bash
# Back up everything the platform keeps, to the off-server repository in .env.
#
#   1. a pg_dump of the database (checked readable before it is kept)
#   2. the app's files volume: uploaded documents, drawings, generated PDFs
#
# Both go into one encrypted restic snapshot, then old snapshots are thinned to
# 14 daily, 8 weekly and 12 monthly. On Sundays a sample of the stored data is
# re-read to prove the repository is intact.
#
# Run nightly by the pmpm-backup.timer systemd unit (see README.md), and by
# deploy.sh before every update. Safe to run by hand at any time.
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a

: "${RESTIC_REPOSITORY:?Set RESTIC_REPOSITORY in .env}"
: "${RESTIC_PASSWORD:?Set RESTIC_PASSWORD in .env}"

RESTIC_IMAGE="restic/restic:0.18.0"
STAGING="${BACKUP_STAGING:-/var/backups/pmpm}"
FILES_VOLUME="pmpm_app_data"

ping() {
  [ -n "${BACKUP_PING_URL:-}" ] || return 0
  curl -fsS -m 10 --retry 3 -o /dev/null "${BACKUP_PING_URL}$1" || true
}
trap 'ping /fail; echo "BACKUP FAILED" >&2' ERR

restic() {
  docker run --rm -i \
    -e RESTIC_REPOSITORY -e RESTIC_PASSWORD -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
    -v pmpm_restic_cache:/root/.cache/restic \
    -v "$STAGING":/backup/database:ro \
    -v "$FILES_VOLUME":/backup/files:ro \
    "$RESTIC_IMAGE" "$@"
}

mkdir -p "$STAGING"
chmod 700 "$STAGING"

echo "== $(date -u +%FT%TZ) Dumping the database"
docker compose exec -T postgres pg_dump -U oe -d openestimate --format=custom --compress=6 \
  > "$STAGING/openestimate.dump.tmp"
# A failed pg_dump has already stopped the script (set -e, pipefail). This
# also refuses a file whose header cannot be read, before it replaces the
# last good dump.
docker compose exec -T postgres pg_restore --list < "$STAGING/openestimate.dump.tmp" > /dev/null
mv "$STAGING/openestimate.dump.tmp" "$STAGING/openestimate.dump"
ls -lh "$STAGING/openestimate.dump"

echo "== Opening the backup repository"
if ! restic cat config > /dev/null 2>&1; then
  echo "No repository at $RESTIC_REPOSITORY yet: creating it."
  restic init
fi

echo "== Uploading"
restic backup /backup --host pmpm --tag nightly

echo "== Thinning old snapshots"
restic forget --host pmpm --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune

if [ "$(date +%u)" = "7" ]; then
  echo "== Sunday: re-reading 5 % of the stored data"
  restic check --read-data-subset=5%
fi

restic snapshots --host pmpm --latest 3
ping ""
echo "== $(date -u +%FT%TZ) Backup done"
