"""The grant, provider, model and readiness agree across existing AI entry points."""

from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from app.modules.ai import ai_client, company_config
from app.modules.ai.company_config import CompanySettingsUpdate
from app.modules.ai.internal_pilot import ACCESS_FLAG
from app.modules.ai.models import AISettings
from app.modules.ai.repository import AISettingsRepository
from app.modules.ai.schemas import AISettingsUpdate
from app.modules.ai.service import AIService
from app.modules.ai.team_grants import GrantRequest, set_team_grant
from tests.unit.teams.conftest import make_membership, make_project, make_team, make_user

pytestmark = pytest.mark.asyncio


async def test_existing_features_use_owner_selection_only_for_approved_teams(session, monkeypatch, tmp_path):
    owner = await make_user(session, role="admin")
    member = await make_user(session)
    other = await make_user(session, role="admin")
    project = await make_project(session, owner.id)
    team = await make_team(session, project.id)
    await make_membership(session, team.id, member.id)
    monkeypatch.setenv("PMPM_INTERNAL_AI_PILOT", "true")
    monkeypatch.setenv("REGISTRATION_MODE", "closed")
    monkeypatch.setenv("SEED_DEMO", "false")
    monkeypatch.setenv("PMPM_AI_OWNER_USER_ID", str(owner.id))
    monkeypatch.setenv("OPENAI_API_KEY", "unused-env")
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    company_config.save_company_settings(
        CompanySettingsUpdate(provider="openai", model="owner-model", api_key=SecretStr("test-central-credential"))
    )
    # Another admin previously approved under the legacy pilot has no team grant.
    session.add(AISettings(user_id=other.id, metadata_={ACCESS_FLAG: True}, openai_api_key="old-personal"))
    await session.flush()

    repo = AISettingsRepository(session)
    service = AIService(session)
    assert (await service.get_ai_settings(str(owner.id))).managed_ai.is_owner
    assert not (await service.get_ai_settings(str(other.id))).ai_ready
    with pytest.raises(ValueError, match="does not have"):
        ai_client.resolve_provider_key_model(await repo.get_by_user_id(other.id))
    assert not (await service.get_ai_settings(str(member.id))).ai_ready
    with pytest.raises(HTTPException, match="company owner"):
        await service.update_ai_settings(str(member.id), AISettingsUpdate(openai_api_key="unused"))
    await set_team_grant(team.id, GrantRequest(enabled=True), session)

    status = await service.get_ai_settings(str(member.id))
    assert status.ai_ready and status.managed_ai.has_access and not status.managed_ai.is_owner
    assert not status.openai_api_key_set
    assert "test-central-credential" not in status.model_dump_json()
    settings = await repo.get_by_user_id(member.id)
    assert ai_client.resolve_provider_key_model(settings, "unapproved-model") == (
        "openai",
        "test-central-credential",
        "owner-model",
    )
    # Feature paths that only resolve the historical 2-tuple still use the owner model.
    provider, key = ai_client.resolve_provider_and_key(settings)
    outbound = AsyncMock(return_value=("ok", 2))
    monkeypatch.setattr(ai_client, "call_openai", outbound)
    assert await ai_client.call_ai(provider, key, "", "hello", model="other-model") == ("ok", 2)
    assert outbound.await_args.kwargs["model"] == "owner-model"
    with pytest.raises(ValueError, match="custom endpoint"):
        await ai_client.call_ai(provider, key, "", "hello", base_url="https://untrusted.invalid")
    with pytest.raises(ValueError, match="unavailable"):
        await ai_client.call_ai("deepseek", key, "", "hello")
    assert outbound.await_count == 1

    # A provider response may echo sensitive input. No fallback to another model,
    # and neither its body nor the key should appear in the member's error.
    req = httpx.Request("POST", "https://provider.invalid")
    response = httpx.Response(404, json={"error": {"message": "model not found, test-central-credential"}}, request=req)
    outbound.side_effect = httpx.HTTPStatusError("test-central-credential", request=req, response=response)
    with pytest.raises(ValueError, match="Contact your workspace owner") as error:
        await ai_client.call_ai(provider, key, "", "hello")
    assert outbound.await_count == 2 and "test-central-credential" not in str(error.value)

    company_config.save_company_settings(
        CompanySettingsUpdate(provider="deepseek", model="selected-deepseek", api_key=SecretStr("rotated-secret"))
    )
    assert ai_client.resolve_provider_key_model(await repo.get_by_user_id(member.id)) == (
        "deepseek",
        "rotated-secret",
        "selected-deepseek",
    )
    with pytest.raises(ValueError):
        await ai_client.call_ai(provider, key, "", "hello")
    await set_team_grant(team.id, GrantRequest(enabled=False), session)
    with pytest.raises(ValueError, match="does not have"):
        ai_client.resolve_provider_key_model(await repo.get_by_user_id(member.id))
    assert not (await service.get_ai_settings(str(member.id))).ai_ready

    monkeypatch.delenv("PMPM_AI_OWNER_USER_ID")
    monkeypatch.setenv("PMPM_INTERNAL_DEEPSEEK_API_KEY", "unused-legacy-key")
    with pytest.raises(ValueError, match="does not have"):
        ai_client.resolve_provider_key_model(await repo.get_by_user_id(other.id))


@pytest.mark.parametrize("bad_env", [{"PMPM_AI_OWNER_USER_ID": "broken"}, {"REGISTRATION_MODE": "open"}])
async def test_unsafe_managed_mode_ignores_legacy_personal_and_environment_credentials(monkeypatch, bad_env):
    monkeypatch.setenv("PMPM_INTERNAL_AI_PILOT", "true")
    monkeypatch.setenv("PMPM_AI_OWNER_USER_ID", str(uuid4()))
    monkeypatch.setenv("REGISTRATION_MODE", "closed")
    monkeypatch.setenv("SEED_DEMO", "false")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unused-env")
    monkeypatch.setenv("PMPM_INTERNAL_DEEPSEEK_API_KEY", "unused-company-env")
    for name, value in bad_env.items():
        monkeypatch.setenv(name, value)
    row = AISettings(user_id=uuid4(), openai_api_key="personal", metadata_={ACCESS_FLAG: True})
    with pytest.raises(ValueError, match="does not have"):
        ai_client.resolve_provider_key_model(row)
