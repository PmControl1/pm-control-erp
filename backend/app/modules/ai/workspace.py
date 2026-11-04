"""Workspace AI: one provider, key, model and system prompt, set by the platform owner.

When the owner has saved a configuration, every AI feature in the app uses it
for every signed-in user. Nobody else enters or sees a key.

The configuration lives in ``oe_ai_workspace_config``. Each server worker keeps
a decrypted copy in memory, because the key resolver in ``ai_client`` is
synchronous and is called from dozens of places, and refreshes it every few
seconds so a change saved through one worker reaches the others.

The same module holds the assistant's per-user memory.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.ai.models import AIMemory, WorkspaceAIConfig

logger = logging.getLogger(__name__)

#: How often each worker re-reads the configuration from the database.
REFRESH_SECONDS = 10.0

#: Memory limits per user: stored entries, characters per entry, and how many
#: of the newest entries go into the assistant's prompt.
MEMORY_MAX_ITEMS = 200
MEMORY_MAX_CHARS = 1000
MEMORY_PROMPT_ITEMS = 60

WORKSPACE_PROMPT_HEADER = (
    "## Instructions from the workspace owner\n"
    "Follow these in every answer. If the task below asks for a specific output "
    "format (for example JSON), keep that format exactly.\n"
)


@dataclass(frozen=True)
class WorkspaceAI:
    """The decrypted configuration every AI call uses."""

    provider: str
    api_key: str
    model: str
    system_prompt: str
    memory_enabled: bool

    def require_key(self) -> str:
        if not self.api_key:
            raise ValueError(
                "The workspace AI key could not be read (the server's encryption key changed). "
                "The workspace owner needs to enter it again in Settings > AI."
            )
        return self.api_key


_current: WorkspaceAI | None = None
_refresh_task: asyncio.Task[None] | None = None


def current() -> WorkspaceAI | None:
    """The workspace configuration, or None when the owner has not set one up."""
    return _current


def set_current(value: WorkspaceAI | None) -> None:
    global _current
    _current = value


PUBLIC_AI_ERROR = "AI could not complete this request. Please try again or contact your workspace administrator."


def public_error(message: str | None) -> str | None:
    """Keep upstream credentials, endpoints and model diagnostics on the server.

    Personal-provider installations retain their actionable configuration
    messages. Workspace users get operational status; the owner diagnoses the
    provider through the protected workspace connection test and server logs.
    """
    if not message or _current is None:
        return message
    return PUBLIC_AI_ERROR


def from_row(row: WorkspaceAIConfig | None) -> WorkspaceAI | None:
    if row is None:
        return None
    from app.core.crypto import decrypt_secret

    return WorkspaceAI(
        provider=row.provider,
        api_key=(decrypt_secret(row.api_key) or "") if row.api_key else "",
        model=(row.model or "").strip(),
        system_prompt=row.system_prompt or "",
        memory_enabled=bool(row.memory_enabled),
    )


async def load_row(session: AsyncSession) -> WorkspaceAIConfig | None:
    from sqlalchemy import select

    from app.modules.ai.models import WorkspaceAIConfig

    return await session.scalar(select(WorkspaceAIConfig).order_by(WorkspaceAIConfig.created_at).limit(1))


async def refresh() -> WorkspaceAI | None:
    """Re-read the configuration from the database into this worker."""
    from app.database import async_session_factory

    async with async_session_factory() as session:
        row = await load_row(session)
    set_current(from_row(row))
    return _current


async def _refresh_forever() -> None:
    while True:
        await asyncio.sleep(REFRESH_SECONDS)
        try:
            await refresh()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Workspace AI refresh failed; keeping the last settings", exc_info=True)


async def start() -> None:
    """Load the configuration now and keep it fresh for the life of the worker."""
    global _refresh_task
    try:
        await refresh()
    except Exception:
        logger.warning("Workspace AI could not be loaded at startup; retrying in the background", exc_info=True)
    if _refresh_task is None or _refresh_task.done():
        _refresh_task = asyncio.get_running_loop().create_task(_refresh_forever(), name="workspace-ai-refresh")


# ── Who may change it ────────────────────────────────────────────────────────


def owner_user_ids() -> set[uuid.UUID]:
    """Explicit, immutable account IDs allowed to manage this installation's AI.

    Missing or malformed configuration grants nobody access. Email addresses
    cannot establish ownership: a staff administrator can erase an account and
    recreate its email address, but cannot choose the new account's UUID.
    """
    raw = os.environ.get("PLATFORM_OWNER_USER_IDS", "").strip()
    if not raw:
        return set()
    try:
        return {uuid.UUID(part.strip()) for part in raw.split(",")}
    except ValueError:
        return set()


async def is_owner(session: AsyncSession, payload: dict[str, Any]) -> bool:
    """Require an allowlisted, active administrator from the live database.

    Token role/email claims and the legacy email setting confer no ownership.
    The first administrator still registers through the private bootstrap;
    the operator then pins that account ID before enabling public access.
    """
    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (TypeError, ValueError):
        return False
    return await is_owner_user(session, user_id)


async def is_owner_user(session: AsyncSession, user_id: str | uuid.UUID) -> bool:
    """Resolve owner access for services whose caller is a user ID, not a JWT."""
    try:
        uid = uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return False
    if uid not in owner_user_ids():
        return False

    from app.core.permissions import Role, _resolve_role
    from app.modules.users.models import User

    user = await session.get(User, uid)
    return bool(user and user.is_active and user.deleted_at is None and _resolve_role(user.role) == Role.ADMIN)


# ── System prompt ────────────────────────────────────────────────────────────


def with_workspace_instructions(system: str | None) -> str:
    """Put the owner's system prompt in front of a feature's own system prompt."""
    system = system or ""
    ws = _current
    text = ws.system_prompt.strip() if ws else ""
    if not text:
        return system
    block = f"{WORKSPACE_PROMPT_HEADER}{text}\n\n"
    if system.startswith(block):
        return system
    return block + system


# ── Memory ───────────────────────────────────────────────────────────────────


def memory_enabled() -> bool:
    """Memory is on unless the owner turned it off."""
    ws = _current
    return ws.memory_enabled if ws is not None else True


async def list_memories(session: AsyncSession, user_id: uuid.UUID, limit: int | None = None) -> list[AIMemory]:
    """A user's memories, newest first."""
    from sqlalchemy import select

    from app.modules.ai.models import AIMemory

    stmt = select(AIMemory).where(AIMemory.user_id == user_id).order_by(AIMemory.created_at.desc())
    if limit:
        stmt = stmt.limit(limit)
    return list((await session.scalars(stmt)).all())


async def add_memory(session: AsyncSession, user_id: uuid.UUID, content: str, source: str = "user") -> AIMemory:
    """Store one memory. An identical existing memory is returned instead of a duplicate."""
    from sqlalchemy import delete, func, select

    from app.modules.ai.models import AIMemory

    text = " ".join((content or "").split())[:MEMORY_MAX_CHARS]
    if not text:
        raise ValueError("Memory text is empty.")
    existing = await session.scalar(select(AIMemory).where(AIMemory.user_id == user_id, AIMemory.content == text))
    if existing is not None:
        return existing
    memory = AIMemory(user_id=user_id, content=text, source=source)
    session.add(memory)
    await session.flush()

    count = await session.scalar(select(func.count()).select_from(AIMemory).where(AIMemory.user_id == user_id))
    if count and count > MEMORY_MAX_ITEMS:
        oldest = (
            select(AIMemory.id)
            .where(AIMemory.user_id == user_id)
            .order_by(AIMemory.created_at)
            .limit(count - MEMORY_MAX_ITEMS)
        )
        await session.execute(delete(AIMemory).where(AIMemory.id.in_(oldest)))
    return memory


async def delete_memory(session: AsyncSession, user_id: uuid.UUID, memory_id: uuid.UUID) -> bool:
    from sqlalchemy import delete

    from app.modules.ai.models import AIMemory

    result = await session.execute(delete(AIMemory).where(AIMemory.id == memory_id, AIMemory.user_id == user_id))
    return bool(result.rowcount)


async def clear_memories(session: AsyncSession, user_id: uuid.UUID) -> int:
    from sqlalchemy import delete

    from app.modules.ai.models import AIMemory

    result = await session.execute(delete(AIMemory).where(AIMemory.user_id == user_id))
    return int(result.rowcount or 0)


def memory_prompt_block(memories: list[AIMemory]) -> str:
    """The part of the chat prompt that tells the assistant what it remembers."""
    lines = [f"- {m.content}" for m in memories if m.content]
    intro = (
        "\n\n## Memory\n"
        "You can remember things about this user between conversations. When they ask you "
        "to remember something, or tell you a lasting preference or fact about themselves or "
        "their work, call `save_memory` with one short sentence. Do not save passwords, keys, "
        "or one-off details of the current task."
    )
    if not lines:
        return intro + "\nYou have nothing saved about this user yet."
    return intro + "\nWhat you remember about this user (newest first):\n" + "\n".join(lines)
