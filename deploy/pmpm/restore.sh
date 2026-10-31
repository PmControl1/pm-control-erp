#!/usr/bin/env bash
# Restore from the off-server backups that backup.sh makes.
#
#   ./restore.sh --list           show the snapshots there are
#   ./restore.sh --test [ID]      prove a snapshot restores, WITHOUT touching
#                                 the live platform: the database goes into a
#                                 throwaway PostgreSQL and its counts are
#                                 compared with the live ones
#   ./restore.sh [ID]             replace the live database and files with the
#                                 snapshot (asks you to type the domain first)
#
# ID defaults to the newest snapshot.
set -euo pipefail
cd "$(dirname "$0")"
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
cleanup() {
  docker rm -f pmpm-restore-test > /dev/null 2>&1 || true
  # The restored files belong to the container's root; remove them the same way.
  docker run --rm -v "$RESTORE_TARGET":/r alpine:3 sh -c 'rm -rf /r/*' > /dev/null 2>&1 || true
  rmdir "$RESTORE_TARGET" 2> /dev/null || true
}
trap cleanup EXIT

echo "== Fetching snapshot '$snapshot'"
restic restore "$snapshot" --host pmpm --target /restore
dump="$RESTORE_TARGET/backup/database/openestimate.dump"
files="$RESTORE_TARGET/backup/files"
[ -s "$dump" ] || { echo "The snapshot has no database dump." >&2; exit 1; }
echo "Database dump: $(du -h "$dump" | cut -f1). Files: $(du -sh "$files" | cut -f1), $(find "$files" -type f | wc -l) files."

counts_sql="select 'users', count(*) from oe_users_user union all select 'projects', count(*) from oe_projects_project order by 1"

if [ "$mode" = "test" ]; then
  echo "== Restoring the database into a throwaway PostgreSQL"
  docker run -d --name pmpm-restore-test -e POSTGRES_USER=oe -e POSTGRES_PASSWORD=restore-test \
    -e POSTGRES_DB=openestimate "$PG_IMAGE" > /dev/null
  for _ in $(seq 1 30); do
    docker exec pmpm-restore-test pg_isready -U oe -d openestimate > /dev/null 2>&1 && break
    sleep 2
  done
  sleep 2
  docker exec -i pmpm-restore-test pg_restore -U oe -d openestimate --no-owner --exit-on-error < "$dump"
  echo ""
  echo "Restored copy:"
  docker exec pmpm-restore-test psql -U oe -d openestimate -At -F ': ' -c "$counts_sql"
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
