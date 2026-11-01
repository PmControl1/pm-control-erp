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
umask 077
# A deploy calls backup.sh while holding this same lock. Inherit that ownership
# rather than opening a second lock and deadlocking. Manual/timer runs serialize.
if [ "${PMPM_MAINTENANCE_LOCKED:-}" != "$PWD" ]; then
  PMPM_MAINTENANCE_LOCKED="$PWD" flock -n -E 75 "$PWD/.maintenance.lock" bash "$0" "$@" && exit 0
  status=$?
  [ "$status" -ne 75 ] || echo "Another backup, restore or deployment is running." >&2
  exit "$status"
fi

[ -f .env ] || { echo "No .env here. Copy .env.example to .env and fill it in first." >&2; exit 1; }

set -a; . ./.env; set +a
: "${PMPM_DOMAIN:?Set PMPM_DOMAIN in .env}"

requested_tag="${1:-}"
if [ -n "$requested_tag" ]; then
  [[ "$requested_tag" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || {
    echo "Invalid image tag." >&2; exit 1;
  }
  # Override Compose for this attempt. Persist only after a healthy deployment.
  export PMPM_IMAGE_TAG="$requested_tag"
fi

if [ -n "${RESTIC_REPOSITORY:-}" ] && docker compose ps --status running --services 2>/dev/null | grep -qx postgres; then
  echo "== Backup before updating"
  ./backup.sh
fi

echo "== Pulling ${PMPM_IMAGE:-ghcr.io/pmcontrol1/pm-control-erp}:${PMPM_IMAGE_TAG:-main}"
docker compose pull app

echo "== Starting the private app"
# A previous proxy must not expose the app during bootstrap verification.
docker compose stop caddy
docker compose up -d postgres app
ready=false
for _ in $(seq 1 60); do
  if docker compose exec -T app curl -fsS http://localhost:8080/api/health >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 5
done
[ "$ready" = true ] || { docker compose logs --tail 60 app >&2; exit 1; }

# Never expose a fresh-install registration endpoint to the Internet: its
# first registrant becomes administrator. Bootstrap privately via README first.
if ! docker compose exec -T app python - <<'PYTHON'
import asyncio
from app.database import async_session_factory
from app.modules.users.repository import UserRepository

async def check():
    async with async_session_factory() as session:
        if not await UserRepository(session).has_admin():
            raise SystemExit("No active administrator. Follow the README bootstrap before starting Caddy.")

asyncio.run(check())
PYTHON
then
  docker compose stop caddy
  exit 1
fi

docker compose up -d caddy
echo "== Waiting for the app and public HTTPS endpoint to answer"
for i in $(seq 1 60); do
  if docker compose exec -T app curl -fsS http://localhost:8080/api/health >/dev/null 2>&1 &&
    curl -fsS --connect-timeout 5 --max-time 10 "https://${PMPM_DOMAIN}/api/health" >/dev/null 2>&1; then
    echo "Up after $((i * 5)) s."
    docker compose exec -T app curl -fsS http://localhost:8080/api/health | head -c 300; echo
    if [ -n "$requested_tag" ]; then
      if grep -q '^PMPM_IMAGE_TAG=' .env; then
        sed -i "s/^PMPM_IMAGE_TAG=.*/PMPM_IMAGE_TAG=$requested_tag/" .env
      else
        echo "PMPM_IMAGE_TAG=$requested_tag" >> .env
      fi
    fi
    echo "Open https://${PMPM_DOMAIN}"
    exit 0
  fi
  sleep 5
done

echo "The app or public HTTPS endpoint did not become ready. Last app/Caddy logs:" >&2
docker compose logs --tail 60 app caddy >&2
exit 1
