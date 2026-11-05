"""Workspace AI: the owner's provider serves everyone, and the assistant's memory."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.modules.ai import workspace
from app.modules.ai.ai_client import resolve_provider_and_key, resolve_provider_key_model

WS = workspace.WorkspaceAI(
    provider="deepseek",
    api_key="sk-workspace-0000",
    model="deepseek-flash",
    system_prompt="Answer in Bulgarian.",
    memory_enabled=True,
)


@pytest.fixture
def workspace_ai():
    workspace.set_current(WS)
    yield WS
    workspace.set_current(None)


def test_workspace_key_wins_over_personal_key(workspace_ai) -> None:
    from app.core.crypto import encrypt_secret

    personal = SimpleNamespace(
        preferred_model="gpt-4.1",
        openai_api_key=encrypt_secret("sk-personal"),
        metadata_={"model_overrides": {"openai": "gpt-4o"}},
    )
    assert resolve_provider_and_key(personal) == ("deepseek", "sk-workspace-0000")
    assert resolve_provider_key_model(None) == ("deepseek", "sk-workspace-0000", "deepseek-flash")


def test_owner_instructions_are_prepended_once(workspace_ai) -> None:
    once = workspace.with_workspace_instructions("Return JSON.")
    assert once.startswith(workspace.WORKSPACE_PROMPT_HEADER)
    assert "Answer in Bulgarian." in once and once.endswith("Return JSON.")
    assert workspace.with_workspace_instructions(once) == once


def test_no_workspace_leaves_prompt_alone() -> None:
    workspace.set_current(None)
    assert workspace.with_workspace_instructions("Return JSON.") == "Return JSON."


# ── HTTP ─────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def client():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


async def _login(client: AsyncClient, role: str, *, email: str | None = None) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    tag = uuid.uuid4().hex[:8]
    email = email or f"ws-ai-{role}-{tag}@test.io"
    password = f"WorkspaceAi{tag}9"
    reply = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": f"WS {tag}"}
    )
    assert reply.status_code in (200, 201), reply.text
    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email).values(role=role, is_active=True))
        await session.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_owner_sets_ai_once_and_everyone_uses_it(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = await _login(client, "admin")
    identity = await client.get("/api/v1/users/me/", headers=owner)
    assert identity.status_code == 200, identity.text
    monkeypatch.setenv("PLATFORM_OWNER_USER_IDS", identity.json()["id"])
    staff_admin = await _login(client, "admin")
    member = await _login(client, "editor")
    try:
        saved = await client.put(
            "/api/v1/ai/workspace/",
            headers=owner,
            json={"provider": "deepseek", "model": "", "api_key": "sk-test-12345678", "system_prompt": "Be brief."},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["key_hint"] == "…5678"

        assert saved.json()["provider"] == "deepseek"
        assert saved.json()["model"]
        assert "api_key" not in saved.json()

        assert resolve_provider_and_key(None) == ("deepseek", "sk-test-12345678")

        for employee in (staff_admin, member):
            seen = await client.get("/api/v1/ai/workspace/", headers=employee)
            assert seen.status_code == 200, seen.text
            assert seen.json() == {"configured": True, "memory_enabled": True, "can_manage": False}

            settings = (await client.get("/api/v1/ai/settings/", headers=employee)).json()
            assert settings["ai_ready"] and settings["workspace_managed"]
            assert settings["preferred_model"] == "workspace"
            assert settings["model_overrides"] == {} and settings["default_models"] == {}
            assert settings["metadata_"] == {}
            assert not any(value for key, value in settings.items() if key.endswith("_api_key_set"))

            for method, url, body in (
                ("put", "/api/v1/ai/workspace/", {"provider": "openai", "api_key": "replacement-key"}),
                ("delete", "/api/v1/ai/workspace/", None),
                ("post", "/api/v1/ai/workspace/test/", None),
                ("post", "/api/v1/ai/settings/test/", {"provider": "deepseek"}),
                ("patch", "/api/v1/ai/settings/", {"preferred_model": "openai"}),
            ):
                denied = await client.request(method, url, headers=employee, **({"json": body} if body else {}))
                assert denied.status_code == 403, denied.text
            assert resolve_provider_and_key(None) == ("deepseek", "sk-test-12345678")

        # Changing the model keeps the saved key.
        kept = await client.put(
            "/api/v1/ai/workspace/", headers=owner, json={"provider": "deepseek", "model": "deepseek-v4-pro"}
        )
        assert kept.status_code == 200 and kept.json()["key_set"]
        assert resolve_provider_key_model(None)[2] == "deepseek-v4-pro"
    finally:
        removed = await client.delete("/api/v1/ai/workspace/", headers=owner)
        assert removed.status_code == 200 and not removed.json()["configured"]
    assert workspace.current() is None


@pytest.mark.parametrize("state", ["demoted", "inactive", "erased"])
async def test_owner_authorization_uses_current_database_state(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    from sqlalchemy import delete, update

    from app.core.crypto import decrypt_secret
    from app.database import async_session_factory
    from app.modules.ai.models import WorkspaceAIConfig
    from app.modules.users.models import User

    owner = await _login(client, "admin")
    identity = await client.get("/api/v1/users/me/", headers=owner)
    assert identity.status_code == 200, identity.text
    owner_id = uuid.UUID(identity.json()["id"])
    monkeypatch.setenv("PLATFORM_OWNER_USER_IDS", str(owner_id))
    key = "sk-http-owner-state-12345678"
    try:
        saved = await client.put("/api/v1/ai/workspace/", headers=owner, json={"provider": "deepseek", "api_key": key})
        assert saved.status_code == 200, saved.text
        async with async_session_factory() as session:
            row = await workspace.load_row(session)
            assert row is not None
            stored_key = row.api_key
            assert stored_key != key and decrypt_secret(stored_key) == key
            values = {
                "demoted": {"role": "editor"},
                "inactive": {"is_active": False},
                # Keep the active flag set to exercise the erasure marker itself,
                # independently of authentication's inactive-account rejection.
                "erased": {"deleted_at": datetime.now(UTC)},
            }[state]
            await session.execute(update(User).where(User.id == owner_id).values(**values))
            await session.commit()

        # Use a new session so the identity is read from committed PostgreSQL
        # state rather than a session identity map or the original admin JWT.
        async with async_session_factory() as session:
            assert not await workspace.is_owner_user(session, owner_id)
        seen = await client.get("/api/v1/ai/workspace/", headers=owner)
        if seen.status_code == 200:
            assert seen.json() == {"configured": True, "memory_enabled": True, "can_manage": False}
        else:
            assert seen.status_code == 401, seen.text
        denied = await client.put(
            "/api/v1/ai/workspace/", headers=owner, json={"provider": "openai", "api_key": "replacement-key"}
        )
        assert denied.status_code in (401, 403), denied.text
        async with async_session_factory() as session:
            row = await workspace.load_row(session)
            assert row is not None and row.provider == "deepseek" and row.api_key == stored_key
        assert resolve_provider_and_key(None) == ("deepseek", key)
    finally:
        # The intentionally invalid owner cannot clean up through the API.
        async with async_session_factory() as session:
            await session.execute(delete(WorkspaceAIConfig).where(WorkspaceAIConfig.updated_by == owner_id))
            await session.commit()
        workspace.set_current(None)


async def test_recreated_owner_email_cannot_manage_workspace(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import delete, update

    from app.database import async_session_factory
    from app.modules.ai.models import WorkspaceAIConfig
    from app.modules.users.models import User

    owner = await _login(client, "admin")
    identity = await client.get("/api/v1/users/me/", headers=owner)
    assert identity.status_code == 200, identity.text
    owner_id = uuid.UUID(identity.json()["id"])
    owner_email = identity.json()["email"]
    monkeypatch.setenv("PLATFORM_OWNER_USER_IDS", str(owner_id))
    # Prove the former setting cannot authorize a new account with that email.
    monkeypatch.setenv("PLATFORM_OWNER_EMAILS", owner_email)
    key = "sk-http-recreated-owner-12345678"
    try:
        saved = await client.put("/api/v1/ai/workspace/", headers=owner, json={"provider": "deepseek", "api_key": key})
        assert saved.status_code == 200, saved.text
        async with async_session_factory() as session:
            await session.execute(
                update(User)
                .where(User.id == owner_id)
                .values(email=f"erased-{owner_id.hex}@test.io", is_active=False, deleted_at=datetime.now(UTC))
            )
            await session.commit()

        replacement = await _login(client, "admin", email=owner_email)
        replacement_identity = await client.get("/api/v1/users/me/", headers=replacement)
        assert replacement_identity.status_code == 200, replacement_identity.text
        replacement_id = uuid.UUID(replacement_identity.json()["id"])
        assert replacement_id != owner_id
        async with async_session_factory() as session:
            assert not await workspace.is_owner_user(session, owner_id)
            assert not await workspace.is_owner_user(session, replacement_id)
        seen = await client.get("/api/v1/ai/workspace/", headers=replacement)
        assert seen.status_code == 200, seen.text
        assert seen.json() == {"configured": True, "memory_enabled": True, "can_manage": False}
        denied = await client.put(
            "/api/v1/ai/workspace/", headers=replacement, json={"provider": "openai", "api_key": "replacement-key"}
        )
        assert denied.status_code == 403, denied.text
        async with async_session_factory() as session:
            row = await workspace.load_row(session)
            assert row is not None and row.provider == "deepseek" and row.updated_by == owner_id
        assert resolve_provider_and_key(None) == ("deepseek", key)
    finally:
        async with async_session_factory() as session:
            await session.execute(delete(WorkspaceAIConfig).where(WorkspaceAIConfig.updated_by == owner_id))
            await session.commit()
        workspace.set_current(None)


async def test_memory_is_private_to_each_user(client: AsyncClient) -> None:
    alice = await _login(client, "editor")
    bob = await _login(client, "editor")

    added = await client.post("/api/v1/ai/memory/", headers=alice, json={"content": "Prefers answers in Bulgarian."})
    assert added.status_code == 201, added.text
    again = await client.post("/api/v1/ai/memory/", headers=alice, json={"content": "Prefers answers in Bulgarian."})
    assert again.json()["id"] == added.json()["id"]

    mine = (await client.get("/api/v1/ai/memory/", headers=alice)).json()
    assert [m["content"] for m in mine["items"]] == ["Prefers answers in Bulgarian."]
    assert (await client.get("/api/v1/ai/memory/", headers=bob)).json()["items"] == []

    memory_id = added.json()["id"]
    assert (await client.delete(f"/api/v1/ai/memory/{memory_id}", headers=bob)).status_code == 404
    assert (await client.delete(f"/api/v1/ai/memory/{memory_id}", headers=alice)).status_code == 200
    assert (await client.get("/api/v1/ai/memory/", headers=alice)).json()["items"] == []


# ── Chat ─────────────────────────────────────────────────────────────────────


async def test_chat_uses_workspace_key_prompt_and_memory(workspace_ai, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    import httpx

    from app.database import async_session_factory
    from app.modules.ai import ai_client
    from app.modules.erp_chat import service as chat_service
    from app.modules.erp_chat.schemas import StreamChatRequest
    from app.modules.erp_chat.service import ERPChatService

    sent: list[dict] = []
    replies = [
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "save_memory",
                                    "arguments": json.dumps({"content": "Works on the Sofia Tower project."}),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        },
        {
            "choices": [{"message": {"role": "assistant", "content": "Noted."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        },
    ]

    class _Client:
        def __init__(self, *_a, **_k) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc) -> bool:
            return False

        async def post(self, url, headers=None, json=None, timeout=None):  # noqa: A002 - httpx kwarg name
            sent.append({"url": url, "headers": headers or {}, "payload": json or {}})
            return httpx.Response(200, json=replies[len(sent) - 1], request=httpx.Request("POST", url))

    monkeypatch.setattr(ai_client.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(chat_service.httpx, "AsyncClient", _Client)

    user_id = uuid.uuid4()
    async with async_session_factory() as session:
        await workspace.add_memory(session, user_id, "Prefers short answers.")
        service = ERPChatService(session)
        chat = SimpleNamespace(id=uuid.uuid4(), project_id=None, title="t")

        async def _session(*_a, **_k):
            return chat

        async def _budget(_uid):
            return True, 0

        async def _messages(*_a, **_k):
            return [{"role": "user", "content": "Remember I work on the Sofia Tower project."}]

        async def _persist(*_a, **_k):
            return uuid.uuid4()

        monkeypatch.setattr(service, "get_or_create_session", _session)
        monkeypatch.setattr(service, "check_daily_token_budget", _budget)
        monkeypatch.setattr(service, "_build_messages", _messages)
        monkeypatch.setattr(service, "_persist_messages", _persist)
        monkeypatch.setattr(service, "_commit_turn", lambda *_a: _budget(None))

        chunks = [c async for c in service.stream_response(str(user_id), StreamChatRequest(message="hi"))]
        assert any("Noted." in c for c in chunks), chunks

        first = sent[0]
        assert first["url"] == "https://api.deepseek.com/chat/completions"
        assert first["headers"]["Authorization"] == "Bearer sk-workspace-0000"
        assert first["payload"]["model"] == "deepseek-flash"
        system = first["payload"]["messages"][0]["content"]
        assert system.startswith(workspace.WORKSPACE_PROMPT_HEADER) and "Answer in Bulgarian." in system
        assert "Prefers short answers." in system
        assert "save_memory" in {t["function"]["name"] for t in first["payload"]["tools"]}

        saved = [m.content for m in await workspace.list_memories(session, user_id)]
        assert saved == ["Works on the Sofia Tower project.", "Prefers short answers."]
        await session.rollback()
