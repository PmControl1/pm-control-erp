#!/usr/bin/env bash
# Restore from the off-server backups that backup.sh makes.
#
#   ./restore.sh --list           show the snapshots there are
#   ./restore.sh --test [ID]      prove a snapshot restores, WITHOUT touching
#                                 the live platform: the database goes into a
#                                 throwaway PostgreSQL and its counts are shown
#                                 beside the live ones for manual comparison
#   ./restore.sh [ID]             replace the live database and files with the
#                                 snapshot (asks you to type the domain first)
#
# ID defaults to the newest snapshot.
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
PG_IMAGE="postgres:16-alpine"
FILES_VOLUME="pmpm_app_data"

mode="live"
case "${1:-}" in
  --list) mode="list"; shift ;;
  --test) mode="test"; shift ;;
esac
snapshot="${1:-latest}"
if [ "$mode" = live ]; then
  : "${PMPM_DOMAIN:?Set PMPM_DOMAIN in .env before a live restore}"
fi

restic() {
  docker run --rm -i \
    -e RESTIC_REPOSITORY -e RESTIC_PASSWORD -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY \
    -v pmpm_restic_cache:/root/.cache/restic \
    ${RESTORE_TARGET:+-v "$RESTORE_TARGET":/restore} \
    "$RESTIC_IMAGE" "$@"
}

if [ "$mode" = "list" ]; then
  restic snapshots --host pmpm
  exit 0
fi

RESTORE_TARGET="$(mktemp -d /var/tmp/pmpm-restore.XXXXXX)"
export RESTORE_TARGET
test_container="pmpm-restore-test-$$"
cleanup() {
  docker rm -fv "$test_container" > /dev/null 2>&1 || true
  # The restored files belong to the container's root; remove them the same way.
  docker run --rm -v "$RESTORE_TARGET":/r alpine:3 sh -c 'find /r -mindepth 1 -delete' > /dev/null 2>&1 || true
  rmdir "$RESTORE_TARGET" 2> /dev/null || true
}
trap cleanup EXIT

echo "== Fetching snapshot '$snapshot'"
restic restore "$snapshot" --host pmpm --target /restore
dump="$RESTORE_TARGET/backup/database/openestimate.dump"
files="$RESTORE_TARGET/backup/files"
[ -s "$dump" ] || { echo "The snapshot has no database dump." >&2; exit 1; }
[ -d "$files" ] || { echo "The snapshot has no files directory." >&2; exit 1; }
echo "Database dump: $(du -h "$dump" | cut -f1). Files: $(du -sh "$files" | cut -f1), $(find "$files" -type f | wc -l) files."

counts_sql="select 'users', count(*) from oe_users_user union all select 'projects', count(*) from oe_projects_project order by 1"

# Fully validate every snapshot in an isolated database before offering to
# replace live data. A readable archive header alone does not prove restore.
echo "== Restoring the database into a throwaway PostgreSQL"
docker run -d --name "$test_container" -e POSTGRES_USER=oe -e POSTGRES_PASSWORD=restore-test \
  -e POSTGRES_DB=openestimate "$PG_IMAGE" > /dev/null
ready=false
for _ in $(seq 1 30); do
  if docker exec "$test_container" pg_isready -U oe -d openestimate > /dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 2
done
[ "$ready" = true ] || { echo "Restore-test PostgreSQL did not become ready." >&2; exit 1; }
docker exec -i "$test_container" pg_restore -U oe -d openestimate --no-owner --exit-on-error < "$dump"

if [ "$mode" = "test" ]; then
  echo ""
  echo "Restored copy:"
  docker exec "$test_container" psql -U oe -d openestimate -At -F ': ' -c "$counts_sql"
  echo "Live platform now:"
  docker compose exec -T postgres psql -U oe -d openestimate -At -F ': ' -c "$counts_sql" || true
  echo "Live files: $(docker run --rm -v "$FILES_VOLUME":/d:ro alpine:3 sh -c 'find /d -type f | wc -l') files."
  echo ""
  echo "RESTORE TEST PASSED: snapshot '$snapshot' restores cleanly. Counts can be a little"
  echo "below the live ones by whatever was added since the backup ran."
  exit 0
fi

echo ""
echo "This REPLACES the live database and all uploaded files with snapshot '$snapshot'."
echo "Anything entered since that backup is lost."
read -r -p "Type the domain (${PMPM_DOMAIN}) to go ahead: " answer
[ "$answer" = "$PMPM_DOMAIN" ] || { echo "Cancelled."; exit 1; }

echo "== Stopping the app"
docker compose stop app

echo "== Replacing the database"
docker compose exec -T postgres dropdb -U oe --if-exists --force openestimate
docker compose exec -T postgres createdb -U oe openestimate
docker compose exec -T postgres pg_restore -U oe -d openestimate --no-owner --exit-on-error < "$dump"

echo "== Replacing the files"
docker run --rm -v "$FILES_VOLUME":/data -v "$files":/src:ro alpine:3 \
  sh -c 'find /data -mindepth 1 -delete && cp -a /src/. /data/'

echo "== Starting the app"
docker compose start app
docker compose exec -T postgres psql -U oe -d openestimate -At -F ': ' -c "$counts_sql"
echo "Restored snapshot '$snapshot'."
