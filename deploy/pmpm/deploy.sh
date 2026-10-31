#!/usr/bin/env bash
# Pull the newest image CI built and restart the platform on it.
#
#   ./deploy.sh            update to the tag in .env (normally :main)
#   ./deploy.sh sha-abc123 update to one specific build
#
# Takes a backup first when backups are configured, so a bad release can be
# rolled back with ./restore.sh.
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { echo "No .env here. Copy .env.example to .env and fill it in first." >&2; exit 1; }

if [ "${1:-}" != "" ]; then
  sed -i "s/^PMPM_IMAGE_TAG=.*/PMPM_IMAGE_TAG=$1/" .env
  echo "Image tag set to $1 in .env"
fi

set -a; . ./.env; set +a

if [ -n "${RESTIC_REPOSITORY:-}" ] && docker compose ps --status running --services 2>/dev/null | grep -qx postgres; then
  echo "== Backup before updating"
  ./backup.sh
fi

echo "== Pulling ${PMPM_IMAGE:-ghcr.io/pmcontrol1/pm-control-erp}:${PMPM_IMAGE_TAG:-main}"
docker compose pull app

echo "== Starting"
docker compose up -d

echo "== Waiting for the app to answer"
for i in $(seq 1 60); do
  if docker compose exec -T app curl -fsS http://localhost:8080/api/health >/dev/null 2>&1; then
    echo "Up after $((i * 5)) s."
    docker compose exec -T app curl -fsS http://localhost:8080/api/health | head -c 300; echo
    echo "Open https://${PMPM_DOMAIN}"
    exit 0
  fi
  sleep 5
done

echo "The app did not answer within 5 minutes. Its last log lines:" >&2
docker compose logs --tail 60 app >&2
exit 1
