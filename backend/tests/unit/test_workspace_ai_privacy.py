"""Ordinary shared-AI responses disclose readiness, not the owner's runtime."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai import workspace, workspace_router
from app.modules.ai.ai_client import resolve_provider_key_model
from app.modules.ai.service import _build_job_response, _build_job_summary, _build_settings_response
from app.modules.boq.schemas import BOQResponse


@pytest.fixture
def private_ai(monkeypatch):
    settings = workspace.WorkspaceAI(
        provider="deepseek",
        api_key="owner-private-key",
        model="owner-private-model",
        system_prompt="Private instructions",
        memory_enabled=True,
    )
    monkeypatch.setattr(workspace, "_current", settings)
    return settings


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [False, True])
async def test_workspace_status_discloses_configuration_only_to_owner(monkeypatch, private_ai, owner):
    row = SimpleNamespace(
        provider=private_ai.provider,
        model=private_ai.model,
        api_key="ciphertext",
        system_prompt=private_ai.system_prompt,
        memory_enabled=True,
        updated_at=datetime.now(UTC),
    )
    monkeypatch.setattr(workspace, "load_row", AsyncMock(return_value=row))
    monkeypatch.setattr(workspace, "is_owner", AsyncMock(return_value=owner))
    monkeypatch.setattr(workspace_router, "_key_hint", lambda _: "…-key")
    status = await workspace_router._status(object(), {"sub": str(uuid4())})
    assert status["configured"] is True
    assert status["can_manage"] is owner
    assert "api_key" not in status
    if owner:
        assert status["provider"] == private_ai.provider
        assert status["model"] == private_ai.model
        assert status["system_prompt"] == private_ai.system_prompt
    else:
        assert status == {"configured": True, "memory_enabled": True, "can_manage": False}


@pytest.mark.asyncio
async def test_explicit_owner_allowlist_does_not_grant_other_administrators_access(monkeypatch):
    monkeypatch.setenv("PLATFORM_OWNER_EMAILS", "owner@example.com")
    user = SimpleNamespace(id=uuid4(), email="colleague@example.com", role="admin")
    session = SimpleNamespace(get=AsyncMock(return_value=user))
    assert not await workspace.is_owner_user(session, user.id)
    user.email = "OWNER@example.com"
    assert await workspace.is_owner_user(session, user.id)


def test_settings_remain_ready_without_identifying_workspace_provider(private_ai):
    now = datetime.now(UTC)
    settings = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        created_at=now,
        updated_at=now,
        preferred_model=private_ai.provider,
        deepseek_api_key="ciphertext",
        metadata_={"model_overrides": {private_ai.provider: private_ai.model}},
    )
    result = _build_settings_response(settings).model_dump(mode="json", by_alias=True)
    assert result["workspace_managed"] and result["ai_ready"]
    assert result["preferred_model"] == "workspace"
    assert result["model_overrides"] == result["default_models"] == result["metadata_"] == {}
    assert not any(value for key, value in result.items() if key.endswith("_api_key_set"))
    assert private_ai.model not in str(result)
    assert private_ai.api_key not in str(result)
    # The privacy projection must not change actual provider execution.
    assert resolve_provider_key_model(None) == (private_ai.provider, private_ai.api_key, private_ai.model)
    assert settings.metadata_["model_overrides"][private_ai.provider] == private_ai.model


def _job():
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        project_id=None,
        input_type="text",
        input_text="Build a wall",
        input_filename=None,
        status="failed",
        result=[],
        error_message="deepseek rejected owner-private-model",
        model_used="deepseek",
        tokens_used=12,
        duration_ms=120,
        cost_usd_estimate=0.4,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.parametrize("builder", [_build_job_response, _build_job_summary])
def test_estimate_history_masks_runtime_details_without_changing_audit(private_ai, builder):
    job = _job()
    result = builder(job).model_dump(mode="json")
    assert result["model_used"] is None
    assert result["cost_usd_estimate"] is None
    assert result["error_message"] == workspace.PUBLIC_AI_ERROR
    assert result["tokens_used"] == 12
    assert job.model_used == "deepseek" and "owner-private-model" in job.error_message


@pytest.mark.parametrize("builder", [_build_job_response, _build_job_summary])
def test_personal_estimate_diagnostics_remain_available(monkeypatch, builder):
    monkeypatch.setattr(workspace, "_current", None)
    job = _job()
    result = builder(job)
    assert result.model_used == job.model_used
    assert result.error_message == job.error_message
    assert str(result.cost_usd_estimate) == "0.4"


def test_legacy_boq_runtime_metadata_is_not_sent_to_workspace_members(private_ai):
    now = datetime.now(UTC)
    original = {"ai_model": private_ai.model, "ai_job_id": "audit-1", "project_note": "Keep this"}
    boq = BOQResponse(
        id=uuid4(),
        project_id=uuid4(),
        name="Estimate",
        description="AI estimate",
        status="draft",
        metadata_=original,
        created_at=now,
        updated_at=now,
    )
    result = boq.model_dump(mode="json")
    assert result["metadata"] == {"ai_job_id": "audit-1", "project_note": "Keep this"}
    assert original["ai_model"] == private_ai.model


def test_workspace_error_details_are_generic_but_empty_errors_stay_empty(private_ai):
    assert (
        workspace.public_error("Provider https://api.example rejected owner-private-model") == workspace.PUBLIC_AI_ERROR
    )
    assert workspace.public_error(None) is None
    assert workspace.public_error("") == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["configuration", "provider", "transport"])
async def test_takeoff_analysis_errors_do_not_disclose_workspace_runtime(monkeypatch, private_ai, failure):
    from fastapi import HTTPException

    from app.modules.ai import ai_client
    from app.modules.ai.repository import AISettingsRepository
    from app.modules.takeoff import router

    monkeypatch.setattr(router, "_verify_takeoff_doc_access", AsyncMock())
    monkeypatch.setattr(AISettingsRepository, "get_by_user_id", AsyncMock(return_value=None))
    document = SimpleNamespace(filename="plan.pdf", extracted_text="The wall is five metres long.")
    service = SimpleNamespace(get_document=AsyncMock(return_value=document))
    error = "deepseek rejected owner-private-model at https://provider.example"

    def resolve(_settings):
        if failure == "configuration":
            raise ValueError(error)
        return private_ai.provider, private_ai.api_key, private_ai.model

    monkeypatch.setattr(ai_client, "resolve_provider_key_model", resolve)
    monkeypatch.setattr(
        ai_client,
        "call_ai",
        AsyncMock(side_effect=RuntimeError(error) if failure == "transport" else ValueError(error)),
    )
    with pytest.raises(HTTPException) as raised:
        await router.analyze_document("plan-id", str(uuid4()), object(), service)
    assert raised.value.detail == workspace.PUBLIC_AI_ERROR
    assert raised.value.status_code == (502 if failure == "transport" else 400)
