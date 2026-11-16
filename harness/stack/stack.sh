#!/usr/bin/env bash
# A throwaway copy of the production stack for the harness, on localhost only.
#
#   harness/stack/stack.sh up [IMAGE:TAG]   start it; default ghcr.io/pmcontrol1/pm-control-erp:main
#   harness/stack/stack.sh logs DIR         save every container's log under DIR
#   harness/stack/stack.sh down             stop it and delete its data
#
# It runs deploy/pmpm/docker-compose.yml (the real production configuration)
# plus harness/stack/docker-compose.harness.yml, under its own project name,
# with generated secrets and only synthetic data. It never reads
# deploy/pmpm/.env, so a real installation's settings cannot leak in.
#
#   App      http://localhost:${HARNESS_PORT:-18080}
#   Mailpit  http://localhost:${HARNESS_MAIL_PORT:-18025}   (every email the app sends)
#   AI       http://localhost:${HARNESS_AI_PORT:-18001}     (stand-in; /_harness/requests)
set -euo pipefail

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd -- "$here/../.." && pwd)"
project="${HARNESS_PROJECT:-pmpm-harness}"
state="${HARNESS_STATE_DIR:-$repo/harness/.state}"
envfile="$state/stack.env"

case "$project" in
  pmpm-harness*) ;;
  *) echo "HARNESS_PROJECT must start with pmpm-harness; got '$project'." >&2; exit 2 ;;
esac

compose() {
  docker compose --project-name "$project" --env-file "$envfile" \
    -f "$repo/deploy/pmpm/docker-compose.yml" -f "$here/docker-compose.harness.yml" "$@"
}

load_env() {
  if [[ ! -f "$envfile" ]]; then
    echo "No test stack is set up here ($envfile is missing)." >&2
    exit 1
  fi
  # Exported, so values a developer's shell happens to carry cannot override them.
  set -a
  # shellcheck disable=SC1090
  source "$envfile"
  set +a
}

set_env() { # set_env NAME VALUE: replace one line of the env file
  local tmp="$envfile.tmp"
  grep -v "^$1=" "$envfile" > "$tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$tmp"
  mv "$tmp" "$envfile"
}

up() {
  local image="${1:-ghcr.io/pmcontrol1/pm-control-erp:main}"
  if [[ "$image" != *:* || "$image" == *@* ]]; then
    echo "Pass an image with an explicit tag, e.g. ghcr.io/pmcontrol1/pm-control-erp:main" >&2
    exit 2
  fi
  if [[ -f "$envfile" ]]; then
    echo "A test stack already exists for $project. Run '$0 down' first." >&2
    exit 1
  fi
  mkdir -p "$state"
  chmod 700 "$state"
  local port="${HARNESS_PORT:-18080}"
  umask 077
  cat > "$envfile" <<EOF
PMPM_IMAGE=${image%:*}
PMPM_IMAGE_TAG=${image##*:}
POSTGRES_PASSWORD=$(openssl rand -hex 32)
JWT_SECRET=$(openssl rand -hex 32)
PMPM_DOMAIN=:80
PMPM_ACME_EMAIL=harness@example.com
PMPM_REGISTRATION_MODE=closed
PMPM_PLATFORM_OWNER_USER_IDS=
PMPM_EMAIL_BACKEND=smtp
SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=harness@example.com
LOG_LEVEL=INFO
HARNESS_PORT=$port
HARNESS_MAIL_PORT=${HARNESS_MAIL_PORT:-18025}
HARNESS_AI_PORT=${HARNESS_AI_PORT:-18001}
EOF
  load_env
  local base="http://127.0.0.1:$port"

  compose config --quiet
  compose up -d --wait --wait-timeout 300
  python3 -I "$here/bootstrap.py" wait "$base"

  # The first account becomes the admin. Workspace AI belongs to accounts
  # pinned by ID, exactly as on the real server, so pin it and restart the app.
  local owner_id
  owner_id="$(python3 -I "$here/bootstrap.py" owner "$base" "$state" | tail -1)"
  set_env PMPM_PLATFORM_OWNER_USER_IDS "$owner_id"
  load_env
  compose up -d --no-deps --force-recreate --wait --wait-timeout 300 app
  python3 -I "$here/bootstrap.py" wait "$base"
  python3 -I "$here/bootstrap.py" ai "$base" "$state"

  echo
  echo "Test stack $project is up."
  echo "  App      http://localhost:$port   (owner: $state/owner.json)"
  echo "  Mailpit  http://localhost:$HARNESS_MAIL_PORT"
  echo "  AI       http://localhost:$HARNESS_AI_PORT/_harness/requests"
}

logs() {
  local dir="${1:?Usage: stack.sh logs DIR}"
  load_env
  mkdir -p "$dir"
  local service
  for service in app postgres caddy mailpit fake-ai; do
    compose logs --no-color --timestamps "$service" > "$dir/$service.log" 2>&1 || true
  done
  compose ps --all > "$dir/containers.txt" 2>&1 || true
  echo "Logs saved to $dir"
}

down() {
  if [[ ! -f "$envfile" ]]; then
    echo "Nothing to stop for $project."
    return 0
  fi
  load_env
  compose down --volumes --remove-orphans
  rm -rf -- "$state"
  echo "Test stack $project removed."
}

case "${1:-}" in
  up) shift; up "$@" ;;
  logs) shift; logs "$@" ;;
  down) down ;;
  *) sed -n '2,15p' "$0" >&2; exit 2 ;;
esac
