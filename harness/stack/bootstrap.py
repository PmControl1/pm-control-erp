"""Prepare a fresh test stack the way a firm's first day would: one owner, AI on.

  python3 -I bootstrap.py wait   BASE_URL                wait until /api/health is healthy
  python3 -I bootstrap.py owner  BASE_URL STATE_DIR      register the first account (it becomes admin)
  python3 -I bootstrap.py ai     BASE_URL STATE_DIR      save the workspace AI as the owner

Standard library only. The owner's credentials go to STATE_DIR/owner.json,
which the Playwright tests read.
"""

from __future__ import annotations

import json
import secrets
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OWNER_EMAIL = "harness-owner@example.com"


def call(base: str, path: str, data: object | None = None, token: str | None = None, method: str | None = None):
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(
        base.rstrip("/") + path,
        data=None if data is None else json.dumps(data).encode(),
        headers=headers,
        method=method,
    )
    try:
        with urlopen(req, timeout=30) as response:
            raw = response.read()
            status = response.status
    except HTTPError as error:
        raw = error.read()
        status = error.code
    try:
        body = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        body = raw.decode(errors="replace")[:500]
    return status, body


def wait(base: str, timeout: float = 300) -> None:
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        try:
            status, body = call(base, "/api/health")
            if status == 200 and isinstance(body, dict) and body.get("status") == "healthy":
                print(f"Healthy: {body}")
                return
            last = (status, body)
        except (URLError, ConnectionError, TimeoutError, OSError) as error:
            last = error
        time.sleep(2)
    sys.exit(f"The app did not become healthy in {timeout:.0f}s. Last answer: {last}")


def owner(base: str, state: Path) -> None:
    password = "Harness1!" + secrets.token_hex(16)
    status, body = call(
        base,
        "/api/v1/users/auth/register/",
        {"email": OWNER_EMAIL, "password": password, "full_name": "Собственик Тестов", "locale": "bg"},
    )
    if status != 201 or not isinstance(body, dict) or body.get("role") != "admin":
        sys.exit(f"Registering the first account failed: {status} {body}")
    state.mkdir(parents=True, exist_ok=True)
    (state / "owner.json").write_text(json.dumps({"email": OWNER_EMAIL, "password": password, "id": body["id"]}))
    print(body["id"])


def login(base: str, state: Path) -> str:
    saved = json.loads((state / "owner.json").read_text())
    status, body = call(base, "/api/v1/users/auth/login/", {"email": saved["email"], "password": saved["password"]})
    if status != 200 or not isinstance(body, dict) or "access_token" not in body:
        sys.exit(f"The owner could not sign in: {status} {body}")
    return body["access_token"]


def ai(base: str, state: Path) -> None:
    token = login(base, state)
    status, body = call(
        base,
        "/api/v1/ai/workspace/",
        {
            "provider": "deepseek",
            "model": "",
            "api_key": "harness-stand-in",
            "system_prompt": "",
            "memory_enabled": True,
        },
        token=token,
        method="PUT",
    )
    if status != 200 or not isinstance(body, dict) or not body.get("configured"):
        sys.exit(f"Saving the workspace AI failed (is PLATFORM_OWNER_USER_IDS set?): {status} {body}")
    print(f"Workspace AI: {body.get('provider')} / {body.get('model')}")


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in {"wait", "owner", "ai"}:
        sys.exit(__doc__)
    command, base_url = sys.argv[1], sys.argv[2]
    if command == "wait":
        wait(base_url)
    else:
        if len(sys.argv) < 4:
            sys.exit(__doc__)
        {"owner": owner, "ai": ai}[command](base_url, Path(sys.argv[3]))
