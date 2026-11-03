"""The owner-managed provider for one PM company installation.

The synchronous provider resolver and the API workers share one transactional
record in the installation's private data directory. No credential is stored
in user settings. The operator's immutable account ID authorizes management.
"""

import os
import sqlite3
from contextlib import closing
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.core.crypto import decrypt_secret, encrypt_secret, is_encrypted
from app.dependencies import get_current_user_payload
from app.modules.ai.internal_pilot import company_store_path

Provider = Literal["openai", "deepseek"]


class CompanyStatus(BaseModel):
    provider: Provider
    model: str
    key_set: bool


class CompanySettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Provider
    model: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    api_key: SecretStr | None = None


def is_company_owner(user_id: object, role: object) -> bool:
    from app.modules.ai.internal_pilot import internal_pilot_enabled

    if role != "admin" or not internal_pilot_enabled():
        return False
    try:
        return UUID(str(user_id)) == UUID(os.environ.get("PMPM_AI_OWNER_USER_ID", "").strip())
    except ValueError:
        return False


def require_company_owner(payload: Annotated[dict[str, Any], Depends(get_current_user_payload)]) -> None:
    if not is_company_owner(payload.get("sub"), payload.get("role")):
        raise HTTPException(403, "Only the configured company AI owner can manage these settings.")


def _selected() -> tuple[Provider, str, str | None]:
    """Read fresh on every request. Only a genuinely new install may use the legacy key."""
    from app.modules.ai.ai_client import default_model_for
    from app.modules.ai.internal_pilot import internal_pilot_enabled

    empty: tuple[Provider, str, None] = ("deepseek", default_model_for("deepseek"), None)
    if not internal_pilot_enabled():
        return empty
    path = company_store_path()
    try:
        path.stat()
    except FileNotFoundError:
        return empty[0], empty[1], os.environ.get("PMPM_INTERNAL_DEEPSEEK_API_KEY", "").strip() or None
    except OSError:
        return empty

    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
            row = db.execute("SELECT provider, model, ciphertext FROM company_ai WHERE id = 1").fetchone()
    except (OSError, sqlite3.Error):
        return empty
    if row is None or row[0] not in ("openai", "deepseek"):
        return empty
    # Once owner management has been used, removing the environment binding
    # must not make the saved credential available through legacy access grants.
    try:
        UUID(os.environ.get("PMPM_AI_OWNER_USER_ID", "").strip())
    except ValueError:
        return empty
    return row[0], row[1], decrypt_secret(row[2]) if is_encrypted(row[2]) else None


def company_credential() -> tuple[Provider, str, str] | None:
    provider, model, key = _selected()
    return (provider, key, model) if key else None


def company_status() -> CompanyStatus:
    provider, model, key = _selected()
    return CompanyStatus(provider=provider, model=model, key_set=bool(key))


def _persist(data: CompanySettingsUpdate | None) -> CompanyStatus:
    from app.modules.ai.ai_client import default_model_for

    path = company_store_path()
    key = data.api_key.get_secret_value().strip() if data is not None and data.api_key is not None else None
    if key is not None and (not key or len(key) > 4096 or not key.isascii() or not key.isprintable()):
        raise HTTPException(422, "Enter a valid provider API key.")
    legacy = (
        os.environ.get("PMPM_INTERNAL_DEEPSEEK_API_KEY", "").strip() if data and data.provider == "deepseek" else ""
    )
    try:
        if data is not None and key is None and not legacy and not path.exists():
            raise HTTPException(422, "Enter an API key when configuring a provider or changing provider.")
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Do not depend on a process-wide umask to protect the store.
        os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "CREATE TABLE IF NOT EXISTS company_ai "
                "(id INTEGER PRIMARY KEY CHECK(id=1), provider TEXT NOT NULL, model TEXT NOT NULL, ciphertext TEXT)"
            )
            row = db.execute("SELECT provider, model, ciphertext FROM company_ai WHERE id=1").fetchone()
            provider, model, old_ciphertext = row or ("deepseek", default_model_for("deepseek"), None)
            ciphertext = None
            if data is not None:
                if key is not None:
                    ciphertext = encrypt_secret(key)
                elif row is None and legacy:
                    # The owner can keep the pilot's existing DeepSeek key on the
                    # first model change. A row with a cleared key never enters here.
                    ciphertext = encrypt_secret(legacy)
                elif data.provider == provider and is_encrypted(old_ciphertext) and decrypt_secret(old_ciphertext):
                    ciphertext = old_ciphertext
                else:
                    raise HTTPException(422, "Enter an API key when configuring a provider or changing provider.")
                provider, model = data.provider, data.model

            db.execute(
                "INSERT INTO company_ai(id, provider, model, ciphertext) VALUES (1, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET provider=excluded.provider, model=excluded.model, "
                "ciphertext=excluded.ciphertext",
                (provider, model, ciphertext),
            )
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(503, "The company AI settings store is unavailable.") from exc
    return CompanyStatus(provider=provider, model=model, key_set=bool(ciphertext))


router = APIRouter(prefix="/company/settings", dependencies=[Depends(require_company_owner)])


@router.get("/")
def get_company_settings() -> CompanyStatus:
    return company_status()


@router.put("/")
def save_company_settings(data: CompanySettingsUpdate) -> CompanyStatus:
    return _persist(data)


@router.delete("/")
def clear_company_key() -> CompanyStatus:
    # Persist an empty key, so a retired environment key never reappears.
    return _persist(None)


@router.post("/test/")
async def test_company_connection() -> dict:
    import httpx

    from app.modules.ai.ai_client import call_openai, call_openai_compatible

    credential = company_credential()
    if not credential:
        return {"success": False, "message": "No usable company API key is configured."}
    provider, key, model = credential
    # Test the exact saved model. The normal feature dispatcher can recover to
    # another model, which would yield a misleading success for this action.
    args = dict(api_key=key, model=model, system="Connectivity test.", prompt="Reply OK.", max_tokens=32, timeout=15.0)
    try:
        if provider == "openai":
            await call_openai(**args)
        else:
            await call_openai_compatible(provider, **args)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        # Upstream errors can contain reflected authorization or request data.
        return {"success": False, "message": "Connection failed. Check the saved key, model and provider availability."}
    return {"success": True, "message": "The saved provider and model responded."}
