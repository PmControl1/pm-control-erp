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
umask 077
# A deploy calls backup.sh while holding this same lock. Inherit that ownership
# rather than opening a second lock and deadlocking. Manual/timer runs serialize.
if [ "${PMPM_MAINTENANCE_LOCKED:-}" != "$PWD" ]; then
  PMPM_MAINTENANCE_LOCKED="$PWD" flock -n -E 75 "$PWD/.maintenance.lock" bash "$0" "$@" && exit 0
  status=$?
  [ "$status" -ne 75 ] || echo "Another backup, restore or deployment is running." >&2
  exit "$status"
fi
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
resume_app=false
cleanup() {
  status=$?
  trap - EXIT
  if [ "$resume_app" = true ]; then
    echo "== Restarting the app"
    docker compose start app || status=1
  fi
  if [ "$status" -ne 0 ]; then
    ping /fail
    echo "BACKUP FAILED" >&2
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

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

# Prepare network access and images before taking the app offline.
docker volume inspect "$FILES_VOLUME" > /dev/null
docker pull "$RESTIC_IMAGE" > /dev/null
echo "== Opening the backup repository"
if ! restic cat config > /dev/null 2>&1; then
  echo "No repository at $RESTIC_REPOSITORY yet: creating it."
  restic init
fi

# The DB and files must describe the same point in time. No app writers may
# run between pg_dump and the end of the files snapshot. Keep this pilot
# maintenance window at night; EXIT also restarts the app if a command fails.
if docker compose ps --status running --services | grep -qx app; then
  resume_app=true
  echo "== Stopping the app for a consistent database/files snapshot"
  docker compose stop app
fi

echo "== $(date -u +%FT%TZ) Dumping the database"
docker compose exec -T postgres pg_dump -U oe -d openestimate --format=custom --compress=6 \
  > "$STAGING/openestimate.dump.tmp"
# A failed pg_dump has already stopped the script (set -e, pipefail). This
# also refuses a file whose header cannot be read, before it replaces the
# last good dump.
docker compose exec -T postgres pg_restore --list < "$STAGING/openestimate.dump.tmp" > /dev/null
mv "$STAGING/openestimate.dump.tmp" "$STAGING/openestimate.dump"
ls -lh "$STAGING/openestimate.dump"

echo "== Uploading"
restic backup /backup --host pmpm --tag nightly
if [ "$resume_app" = true ]; then
  docker compose start app
  resume_app=false
fi

echo "== Thinning old snapshots"
restic forget --host pmpm --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune

if [ "$(date +%u)" = "7" ]; then
  echo "== Sunday: re-reading 5 % of the stored data"
  restic check --read-data-subset=5%
fi

restic snapshots --host pmpm --latest 3
ping ""
echo "== $(date -u +%FT%TZ) Backup done"
