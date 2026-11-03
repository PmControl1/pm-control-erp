"""Workspace AI settings (owner) and the assistant's memory (each user)."""

import time
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.dependencies import CurrentUserPayload, SessionDep
from app.modules.ai import workspace
from app.modules.ai.models import WorkspaceAIConfig

router = APIRouter()

#: Providers the owner can pick. Self-hosted runtimes need a server URL and
#: are configured per user instead.
WORKSPACE_PROVIDERS = (
    "deepseek",
    "anthropic",
    "openai",
    "gemini",
    "openrouter",
    "mistral",
    "groq",
    "xai",
    "kimi",
    "together",
    "fireworks",
)


class WorkspaceAIUpdate(BaseModel):
    provider: str
    model: str = ""
    # Blank keeps the saved key (allowed only when the provider is unchanged).
    api_key: str | None = None
    system_prompt: str = Field(default="", max_length=20000)
    memory_enabled: bool = True


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=workspace.MEMORY_MAX_CHARS)


def _key_hint(row: WorkspaceAIConfig | None) -> str | None:
    if row is None or not row.api_key:
        return None
    from app.core.crypto import decrypt_secret

    plain = decrypt_secret(row.api_key) or ""
    return f"…{plain[-4:]}" if len(plain) >= 8 else ("…" if plain else None)


async def _status(session: SessionDep, payload: dict[str, Any]) -> dict[str, Any]:
    from app.modules.ai.ai_client import default_model_for

    row = await workspace.load_row(session)
    can_manage = await workspace.is_owner(session, payload)
    body: dict[str, Any] = {
        "configured": row is not None,
        "memory_enabled": bool(row.memory_enabled) if row else True,
        "can_manage": can_manage,
    }
    if can_manage:
        body.update(
            {
                "provider": row.provider if row else None,
                "model": (row.model or default_model_for(row.provider)) if row else None,
                "providers": list(WORKSPACE_PROVIDERS),
                "default_models": {p: default_model_for(p) for p in WORKSPACE_PROVIDERS},
                "system_prompt": row.system_prompt if row else "",
                "key_set": bool(row and row.api_key),
                "key_hint": _key_hint(row),
                "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
            }
        )
    return body


async def _require_owner(session: SessionDep, payload: dict[str, Any]) -> None:
    if not await workspace.is_owner(session, payload):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the platform owner can change workspace AI.")


# ── Workspace AI ─────────────────────────────────────────────────────────────


@router.get("/workspace/")
async def get_workspace_ai(session: SessionDep, payload: CurrentUserPayload) -> dict[str, Any]:
    """Return readiness to users; only owners receive provider configuration."""
    return await _status(session, payload)


@router.put("/workspace/")
async def save_workspace_ai(body: WorkspaceAIUpdate, session: SessionDep, payload: CurrentUserPayload) -> dict:
    """Set the provider, key, model and system prompt every user's AI runs on."""
    from app.core.crypto import encrypt_secret

    await _require_owner(session, payload)
    provider = body.provider.strip().lower()
    if provider not in WORKSPACE_PROVIDERS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unsupported provider: {body.provider}")

    row = await workspace.load_row(session)
    new_key = (body.api_key or "").strip()
    if not new_key and (row is None or row.provider != provider or not row.api_key):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter the API key for this provider.")

    if row is None:
        row = WorkspaceAIConfig(provider=provider)
        session.add(row)
    row.provider = provider
    row.model = body.model.strip()
    if new_key:
        row.api_key = encrypt_secret(new_key)
    row.system_prompt = body.system_prompt.strip()
    row.memory_enabled = body.memory_enabled
    row.updated_by = uuid.UUID(str(payload["sub"]))
    await session.flush()
    await session.commit()

    workspace.set_current(workspace.from_row(row))
    return await _status(session, payload)


@router.delete("/workspace/")
async def remove_workspace_ai(session: SessionDep, payload: CurrentUserPayload) -> dict:
    """Stop providing AI for everyone; users fall back to their own keys."""
    await _require_owner(session, payload)
    row = await workspace.load_row(session)
    if row is not None:
        await session.delete(row)
        await session.commit()
    workspace.set_current(None)
    return await _status(session, payload)


@router.post("/workspace/test/")
async def test_workspace_ai(session: SessionDep, payload: CurrentUserPayload) -> dict:
    """Send one tiny request with the saved workspace settings."""
    from app.modules.ai.ai_client import call_ai, default_model_for

    await _require_owner(session, payload)
    ws = workspace.from_row(await workspace.load_row(session))
    if ws is None:
        return {"success": False, "message": "Save the workspace AI settings first.", "latency_ms": None}
    model = ws.model or default_model_for(ws.provider)
    try:
        started = time.monotonic()
        await call_ai(
            provider=ws.provider,
            api_key=ws.require_key(),
            system="You are a connection test.",
            prompt="Reply with exactly: OK",
            max_tokens=10,
            model=ws.model or None,
            timeout=20.0,
        )
    except Exception as exc:  # noqa: BLE001 - the message is the result
        return {"success": False, "message": f"Connection failed: {str(exc)[:300]}", "latency_ms": None, "model": model}
    return {
        "success": True,
        "message": f"Working ({ws.provider}, {model}).",
        "latency_ms": int((time.monotonic() - started) * 1000),
        "model": model,
    }


# ── Memory ───────────────────────────────────────────────────────────────────


def _memory_out(m: Any) -> dict[str, Any]:
    created: datetime | None = getattr(m, "created_at", None)
    return {
        "id": str(m.id),
        "content": m.content,
        "source": m.source,
        "created_at": created.isoformat() if created else None,
    }


@router.get("/memory/")
async def list_memory(session: SessionDep, payload: CurrentUserPayload) -> dict:
    """What the assistant remembers about the signed-in user."""
    items = await workspace.list_memories(session, uuid.UUID(str(payload["sub"])))
    return {"enabled": workspace.memory_enabled(), "items": [_memory_out(m) for m in items]}


@router.post("/memory/", status_code=status.HTTP_201_CREATED)
async def add_memory(body: MemoryCreate, session: SessionDep, payload: CurrentUserPayload) -> dict:
    try:
        memory = await workspace.add_memory(session, uuid.UUID(str(payload["sub"])), body.content, source="user")
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return _memory_out(memory)


@router.delete("/memory/{memory_id}")
async def delete_memory(memory_id: uuid.UUID, session: SessionDep, payload: CurrentUserPayload) -> dict:
    if not await workspace.delete_memory(session, uuid.UUID(str(payload["sub"])), memory_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Memory not found.")
    return {"deleted": 1}


@router.delete("/memory/")
async def clear_memory(session: SessionDep, payload: CurrentUserPayload) -> dict:
    return {"deleted": await workspace.clear_memories(session, uuid.UUID(str(payload["sub"])))}
