#!/usr/bin/env bash
# Exercise the built image with the production Compose configuration and only
# synthetic data. No host ports, live .env, production volumes or AI keys.
# Usage: bash deploy/pmpm/smoke.sh ghcr.io/pmcontrol1/pm-control-erp:sha-<commit>
set -euo pipefail

image=${1:?Usage: smoke.sh IMAGE:TAG}
if [[ "$image" != *:* || "$image" == *@* ]]; then
  echo "Pass an image with an explicit tag." >&2
  exit 2
fi
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
work="$(mktemp -d)"
project="pmpmsmoke${$}${RANDOM}"
proxy="${project}-proxy"
compose=(docker compose --project-name "$project" --env-file "$work/.env" -f "$work/docker-compose.yml")
cleanup() {
  result=$?
  trap - EXIT
  if (( result != 0 )); then
    "${compose[@]}" logs --tail=120 postgres app >&2 || true
    docker logs --tail=120 "$proxy" >&2 2>/dev/null || true
  fi
  docker rm -f "$proxy" >/dev/null 2>&1 || true
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf -- "$work"
  exit "$result"
}
trap cleanup EXIT
umask 077
cp "$here/docker-compose.yml" "$here/Caddyfile" "$work/"

# Explicit exports also override any developer .env values inherited by CI.
export PMPM_IMAGE="${image%:*}" PMPM_IMAGE_TAG="${image##*:}"
export PMPM_DOMAIN=smoke.example.com PMPM_ACME_EMAIL=smoke@example.com
export POSTGRES_PASSWORD="$(openssl rand -hex 32)"
export JWT_SECRET="$(openssl rand -hex 32)"
export SMTP_FROM=smoke@example.com PMPM_REGISTRATION_MODE=closed
export PMPM_EMAIL_BACKEND=console SMTP_HOST= SMTP_PORT=587 SMTP_USER= SMTP_PASSWORD=
export LOG_LEVEL=INFO
: > "$work/.env"

"${compose[@]}" config --quiet
"${compose[@]}" run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
"${compose[@]}" up -d --wait --wait-timeout 300 postgres app

# `compose run` publishes no service ports. HTTP is used only on the isolated
# Docker network to test the actual reverse proxy rules without public DNS or
# an ACME certificate. The server runbook still requires a real HTTPS check.
"${compose[@]}" run --rm -d --no-deps --use-aliases --name "$proxy" \
  -e PMPM_DOMAIN=http://smoke.example.com caddy

"${compose[@]}" exec -T app python - <<'PY'
import json
import secrets
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

base = "http://127.0.0.1:8080"


def request(path, data=None, token=None, origin=base, expected=200):
    headers = {"Host": "smoke.example.com"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(urljoin(origin, path), data=None if data is None else json.dumps(data).encode(), headers=headers)
    try:
        response = urlopen(req, timeout=30)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read()
        assert response.status == expected, (path, response.status, raw[:500])
        return raw, response.headers


def api(path, **kwargs):
    return json.loads(request(path, **kwargs)[0])


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "script" and values.get("type") == "module" and values.get("src", "").startswith("/assets/"):
            self.sources.append(values["src"])


for attempt in range(30):
    try:
        html, headers = request("/", origin="http://caddy")
        break
    except (URLError, AssertionError):
        if attempt == 29:
            raise
        time.sleep(1)
assert "text/html" in headers.get("Content-Type", ""), dict(headers)
assert headers.get("X-Content-Type-Options") == "nosniff", dict(headers)
parser = Scripts()
parser.feed(html.decode())
assert parser.sources, "The production image did not serve a compiled frontend"
javascript, asset_headers = request(parser.sources[0], origin="http://caddy")
assert javascript and "javascript" in asset_headers.get("Content-Type", ""), dict(asset_headers)
assert api("/api/demo/catalog") == [], "Demo projects are offered in production"

email = "pilot-smoke@example.com"
password = "Pilot1!" + secrets.token_hex(24)
user = api("/api/v1/users/auth/register/", data={"email": email, "password": password, "full_name": "Synthetic pilot smoke", "locale": "bg"}, expected=201)
assert user["role"] == "admin", user
api("/api/v1/users/auth/register/", data={"email": "second-smoke@example.com", "password": password, "full_name": "Must be denied"}, expected=403)
token = api("/api/v1/users/auth/login/", data={"email": email, "password": password})["access_token"]
pack = api("/api/v1/partner-pack/current", token=token)
assert pack["active"] is True and pack["manifest"]["slug"] == "bulgaria-bg", pack
assert pack["manifest"]["default_locale"] == "bg", pack
assert pack["manifest"]["default_currency"] == "EUR", pack
assert len(api("/api/v1/users/", token=token)) == 1, "Unexpected demo or secondary accounts"
Path("/data/.pilot-smoke.json").write_text(json.dumps({"email": email, "password": password, "id": user["id"]}))
print("Production frontend, Caddy proxy, closed registration, Bulgarian pack and no-demo checks passed.")
PY

# A restart alone can hide writes to the image layer; force a new container.
"${compose[@]}" up -d --no-deps --force-recreate --wait --wait-timeout 300 app
"${compose[@]}" exec -T app python - <<'PY'
import json
from pathlib import Path
from urllib.request import Request, urlopen

saved = json.loads(Path("/data/.pilot-smoke.json").read_text())
request = Request("http://127.0.0.1:8080/api/v1/users/auth/login/", data=json.dumps({"email": saved["email"], "password": saved["password"]}).encode(), headers={"Content-Type": "application/json"})
with urlopen(request, timeout=30) as response:
    token = json.load(response)["access_token"]
request = Request("http://127.0.0.1:8080/api/v1/users/me/", headers={"Authorization": f"Bearer {token}"})
with urlopen(request, timeout=30) as response:
    assert json.load(response)["id"] == saved["id"]
print("Database and /data files survived container replacement.")
PY
