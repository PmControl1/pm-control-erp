"""Exercise the real owner decision with database identities and endpoint handlers."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.core.crypto import decrypt_secret, encrypt_secret
from app.modules.ai import workspace, workspace_router

OWNER_ID = UUID("11111111-1111-4111-8111-111111111111")
STAFF_ID = UUID("22222222-2222-4222-8222-222222222222")
PRIVATE_KEY = "sk-private-workspace-12345678"


def _user(user_id=OWNER_ID, *, role="admin", active=True, deleted_at=None):
    return SimpleNamespace(id=user_id, email="owner@example.com", role=role, is_active=active, deleted_at=deleted_at)


def _session(user, row=None):
    return SimpleNamespace(
        get=AsyncMock(return_value=user),
        scalar=AsyncMock(return_value=row),
        add=Mock(),
        delete=AsyncMock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
    )


@pytest.fixture(autouse=True)
def explicit_owner(monkeypatch):
    monkeypatch.setenv("PLATFORM_OWNER_USER_IDS", str(OWNER_ID))
    monkeypatch.delenv("PLATFORM_OWNER_EMAILS", raising=False)
    monkeypatch.setattr(workspace, "_current", None)


@pytest.fixture
def private_row(monkeypatch):
    row = SimpleNamespace(
        provider="deepseek",
        model="private-workspace-model",
        api_key=encrypt_secret(PRIVATE_KEY),
        system_prompt="Private company instructions.",
        memory_enabled=True,
        updated_at=datetime.now(UTC),
        updated_by=OWNER_ID,
    )
    monkeypatch.setattr(workspace, "_current", workspace.from_row(row))
    return row


@pytest.mark.parametrize("raw", [None, "", " ", ", ,", "not-a-uuid", f"{OWNER_ID},invalid"])
async def test_missing_or_invalid_owner_configuration_denies_administrators(monkeypatch, raw):
    if raw is None:
        monkeypatch.delenv("PLATFORM_OWNER_USER_IDS")
    else:
        monkeypatch.setenv("PLATFORM_OWNER_USER_IDS", raw)
    # The retired email configuration cannot revive the old role fallback.
    monkeypatch.setenv("PLATFORM_OWNER_EMAILS", "owner@example.com")
    assert not await workspace.is_owner(_session(_user()), {"sub": str(OWNER_ID), "role": "admin"})
    assert not await workspace.is_owner_user(_session(_user()), OWNER_ID)


def test_owner_ids_accept_normalized_multiple_explicit_accounts(monkeypatch):
    monkeypatch.setenv("PLATFORM_OWNER_USER_IDS", f" {OWNER_ID} , {str(STAFF_ID).upper()} , {OWNER_ID} ")
    assert workspace.owner_user_ids() == {OWNER_ID, STAFF_ID}


@pytest.mark.parametrize(
    ("user", "subject", "claimed_role", "allowed"),
    [
        (_user(), str(OWNER_ID), "editor", True),
        (_user(STAFF_ID), str(STAFF_ID), "admin", False),
        (_user(role="editor"), str(OWNER_ID), "admin", False),
        (_user(role="manager"), str(OWNER_ID), "admin", False),
        (_user(active=False), str(OWNER_ID), "admin", False),
        (_user(deleted_at=datetime.now(UTC)), str(OWNER_ID), "admin", False),
        (None, str(OWNER_ID), "admin", False),
        (_user(), "invalid", "admin", False),
        (_user(), None, "admin", False),
    ],
)
async def test_only_the_configured_active_database_administrator_is_owner(user, subject, claimed_role, allowed):
    payload = {"sub": subject, "role": claimed_role, "email": "owner@example.com"}
    assert await workspace.is_owner(_session(user), payload) is allowed
    assert await workspace.is_owner_user(_session(user), subject) is allowed


async def test_recreating_an_owner_email_does_not_transfer_ownership():
    replacement = _user(uuid4())
    assert not await workspace.is_owner(
        _session(replacement), {"sub": str(replacement.id), "role": "admin", "email": replacement.email}
    )


@pytest.mark.parametrize(("user_id", "role"), [(STAFF_ID, "admin"), (uuid4(), "editor")])
@pytest.mark.parametrize("configured", [False, True])
async def test_staff_settings_return_only_public_availability(private_row, user_id, role, configured):
    session = _session(_user(user_id, role=role), private_row if configured else None)
    response = await workspace_router.get_workspace_ai(session, {"sub": str(user_id), "role": role})
    assert response == {"configured": configured, "memory_enabled": True, "can_manage": False}


async def test_owner_settings_include_configuration_and_hint_but_never_credentials(private_row):
    response = await workspace_router.get_workspace_ai(_session(_user(), private_row), {"sub": str(OWNER_ID)})
    assert response["can_manage"] is True
    assert response["provider"] == private_row.provider
    assert response["model"] == private_row.model
    assert response["system_prompt"] == private_row.system_prompt
    assert response["key_hint"] == "…5678"
    assert response["key_set"] is True
    assert "api_key" not in response
    assert PRIVATE_KEY not in str(response)
    assert private_row.api_key not in str(response)


@pytest.mark.parametrize("owner_ids", [None, "", f"{OWNER_ID},invalid"])
async def test_ownerless_installation_keeps_shared_ai_usable_without_settings_access(
    private_row, monkeypatch, owner_ids
):
    from app.modules.ai.ai_client import resolve_provider_key_model

    if owner_ids is None:
        monkeypatch.delenv("PLATFORM_OWNER_USER_IDS")
    else:
        monkeypatch.setenv("PLATFORM_OWNER_USER_IDS", owner_ids)
    for role in ("admin", "editor"):
        session = _session(_user(role=role), private_row)
        payload = {"sub": str(OWNER_ID), "role": role}
        assert await workspace_router.get_workspace_ai(session, payload) == {
            "configured": True,
            "memory_enabled": True,
            "can_manage": False,
        }
        for request in (
            workspace_router.save_workspace_ai(
                workspace_router.WorkspaceAIUpdate(provider="openai", api_key="replacement-key"), session, payload
            ),
            workspace_router.remove_workspace_ai(session, payload),
            workspace_router.test_workspace_ai(session, payload),
        ):
            with pytest.raises(HTTPException) as denied:
                await request
            assert denied.value.status_code == 403
        session.add.assert_not_called()
        session.delete.assert_not_awaited()
        session.flush.assert_not_awaited()
        session.commit.assert_not_awaited()
    assert resolve_provider_key_model(None) == (private_row.provider, PRIVATE_KEY, private_row.model)


@pytest.mark.parametrize(("user_id", "role"), [(STAFF_ID, "admin"), (uuid4(), "editor")])
@pytest.mark.parametrize("operation", ["save", "delete", "test"])
async def test_staff_cannot_mutate_or_test_workspace_configuration(private_row, user_id, role, operation, monkeypatch):
    from app.modules.ai import ai_client

    call_ai = AsyncMock()
    monkeypatch.setattr(ai_client, "call_ai", call_ai)
    session = _session(_user(user_id, role=role), private_row)
    payload = {"sub": str(user_id), "role": role}
    original = vars(private_row).copy()
    if operation == "save":
        request = workspace_router.save_workspace_ai(
            workspace_router.WorkspaceAIUpdate(
                provider="openai", api_key="replacement-key", system_prompt="Replacement instructions."
            ),
            session,
            payload,
        )
    elif operation == "delete":
        request = workspace_router.remove_workspace_ai(session, payload)
    else:
        request = workspace_router.test_workspace_ai(session, payload)
    with pytest.raises(HTTPException) as denied:
        await request
    assert denied.value.status_code == 403
    assert vars(private_row) == original
    session.scalar.assert_not_awaited()
    session.add.assert_not_called()
    session.delete.assert_not_awaited()
    session.flush.assert_not_awaited()
    session.commit.assert_not_awaited()
    call_ai.assert_not_awaited()


@pytest.mark.parametrize(("user_id", "role"), [(STAFF_ID, "admin"), (uuid4(), "editor")])
async def test_staff_cannot_bypass_workspace_controls_through_personal_settings(private_row, user_id, role):
    from app.modules.ai.router import test_ai_connection
    from app.modules.ai.schemas import AISettingsUpdate
    from app.modules.ai.service import AIService

    session = _session(_user(user_id, role=role), private_row)
    service = AIService(session)
    service.settings_repo = SimpleNamespace(get_by_user_id=AsyncMock())
    with pytest.raises(HTTPException) as denied_update:
        await service.update_ai_settings(str(user_id), AISettingsUpdate(preferred_model="openai"))
    assert denied_update.value.status_code == 403
    with pytest.raises(HTTPException) as denied_test:
        await test_ai_connection({"provider": "deepseek"}, str(user_id), service)
    assert denied_test.value.status_code == 403
    service.settings_repo.get_by_user_id.assert_not_awaited()


async def test_owner_can_replace_the_key_and_employees_keep_using_server_credentials(private_row):
    from app.modules.ai.ai_client import resolve_provider_key_model

    session = _session(_user(), private_row)
    replacement = "sk-replacement-workspace-87654321"
    response = await workspace_router.save_workspace_ai(
        workspace_router.WorkspaceAIUpdate(
            provider="openai", model="company-model", api_key=replacement, system_prompt="New instructions."
        ),
        session,
        {"sub": str(OWNER_ID)},
    )
    assert response["can_manage"] is True
    assert response["key_hint"] == "…4321"
    assert replacement not in str(response)
    assert private_row.api_key != replacement
    assert decrypt_secret(private_row.api_key) == replacement
    assert resolve_provider_key_model(None) == ("openai", replacement, "company-model")
    session.flush.assert_awaited_once()
    session.commit.assert_awaited_once()


async def test_owner_can_test_the_saved_connection(private_row, monkeypatch):
    from app.modules.ai import ai_client

    call_ai = AsyncMock(return_value=("OK", 1))
    monkeypatch.setattr(ai_client, "call_ai", call_ai)
    result = await workspace_router.test_workspace_ai(_session(_user(), private_row), {"sub": str(OWNER_ID)})
    assert result["success"] is True
    assert call_ai.await_args.kwargs["api_key"] == PRIVATE_KEY
    assert call_ai.await_args.kwargs["provider"] == private_row.provider
    assert PRIVATE_KEY not in str(result)


async def test_owner_can_disable_workspace_ai(private_row):
    session = _session(_user(), private_row)
    session.scalar.side_effect = [private_row, None]
    result = await workspace_router.remove_workspace_ai(session, {"sub": str(OWNER_ID)})
    assert result["configured"] is False
    assert workspace.current() is None
    session.delete.assert_awaited_once_with(private_row)
    session.commit.assert_awaited_once()
