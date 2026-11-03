"""Workspace provider details stay off employee chat and agent responses."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.ai import workspace
from app.modules.ai_agents import router as agent_router
from tests.unit.test_erp_chat_fallback_provider import _drive, _frames


@pytest.fixture
def workspace_ai(monkeypatch):
    config = workspace.WorkspaceAI(
        provider="deepseek",
        api_key="private-key",
        model="private-model-id",
        system_prompt="",
        memory_enabled=False,
    )
    monkeypatch.setattr(workspace, "_current", config)
    return config


@pytest.mark.asyncio
@pytest.mark.parametrize("exception", [ValueError, RuntimeError])
async def test_chat_stream_keeps_provider_failures_private(monkeypatch, workspace_ai, exception):
    chunks, _, _ = await _drive(
        monkeypatch,
        provider_error=exception("deepseek rejected private-model-id at https://provider.example"),
    )
    errors = _frames(chunks, "error")
    assert errors == [{"message": workspace.PUBLIC_AI_ERROR}]
    assert _frames(chunks, "done") == [{}]
    assert "private-model-id" not in "".join(chunks)
    assert "deepseek" not in "".join(chunks)


@pytest.mark.asyncio
async def test_personal_chat_retains_actionable_provider_error(monkeypatch):
    monkeypatch.setattr(workspace, "_current", None)
    chunks, _, _ = await _drive(monkeypatch, provider_error=ValueError("Update your personal provider model"))
    assert _frames(chunks, "error") == [{"message": "Update your personal provider model"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [False, True])
async def test_agents_health_discloses_workspace_model_only_to_owner(monkeypatch, workspace_ai, owner):
    from app.modules.ai import ai_client
    from app.modules.ai.repository import AISettingsRepository

    monkeypatch.setattr(AISettingsRepository, "get_by_user_id", AsyncMock(return_value=None))
    monkeypatch.setattr(
        ai_client, "resolve_provider_key_model", lambda _: ("deepseek", "private-key", "private-model-id")
    )
    monkeypatch.setattr(workspace, "is_owner_user", AsyncMock(return_value=owner))
    response = await agent_router.agents_health(user_id=str(uuid4()), session=object())
    assert response.llm_configured is True
    assert response.provider == ("deepseek" if owner else None)
    assert response.model == ("private-model-id" if owner else None)
    assert "private-key" not in response.model_dump_json()


def _run(status="failed", failure_reason="exception", final_output="deepseek transport error"):
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        agent_name="test-agent",
        project_id=None,
        user_id=uuid4(),
        status=status,
        failure_reason=failure_reason,
        user_input="Check the project",
        final_output=final_output,
        iterations=1,
        total_tokens=0,
        started_at=None,
        finished_at=None,
        created_at=now,
        updated_at=now,
    )


def test_historical_agent_errors_are_masked_without_rewriting_internal_records(workspace_ai):
    run = _run()
    step = SimpleNamespace(
        id=uuid4(),
        step_idx=1,
        role="error",
        content={"reason": "llm_error", "message": "deepseek rejected private-model-id"},
        token_count=0,
        created_at=datetime.now(UTC),
    )
    response = agent_router._serialise_run(run, steps=[step])
    assert response.final_output == workspace.PUBLIC_AI_ERROR
    assert response.steps[0].content == {"reason": "llm_error", "message": workspace.PUBLIC_AI_ERROR}
    assert run.final_output == "deepseek transport error"
    assert step.content["message"] == "deepseek rejected private-model-id"


def test_successful_agent_answer_is_not_rewritten(workspace_ai):
    run = _run(status="completed", failure_reason=None, final_output="The document mentions DeepSeek.")
    response = agent_router._serialise_run(run, steps=[])
    assert response.final_output == "The document mentions DeepSeek."


def test_agent_trust_keeps_evidence_without_disclosing_workspace_model(workspace_ai):
    run = _run(status="completed", failure_reason=None, final_output="Project reviewed.")
    run.trust = {"model": "private-model-id", "confidence": 0.8, "sources": [{"id": "doc-1"}]}
    response = agent_router._serialise_run(run, steps=[])
    assert response.trust == {"confidence": 0.8, "sources": [{"id": "doc-1"}]}
    assert run.trust["model"] == "private-model-id"


def test_voice_draft_serialization_preserves_transcript_and_hides_transcription_model(workspace_ai):
    from app.modules.voice.schemas import TranscriptionInfo, VoiceDraftResponse

    transcription = TranscriptionInfo(
        available=True,
        model="private-transcription-model",
        language="bg",
        error="provider.example rejected private-transcription-model",
    )
    response = VoiceDraftResponse(
        target_type="diary_note",
        transcript="The client discussed DeepSeek in the meeting.",
        ai_generated=True,
        transcription=transcription,
    )
    public = response.model_dump()
    assert public["transcript"] == response.transcript
    assert public["ai_generated"] is True
    assert public["transcription"] == {
        "available": True,
        "model": None,
        "language": "bg",
        "error": workspace.PUBLIC_AI_ERROR,
    }
    assert transcription.model == "private-transcription-model"


def test_phonelog_serialization_keeps_protocol_and_internal_audit(workspace_ai):
    from app.modules.phonelog.schemas import PhoneLogResponse

    original_metadata = {
        "source": "recording",
        "protocol": {"summary": "Client requested new drawings.", "ai_generated": True},
        "transcription": {
            "available": True,
            "provider": "openai",
            "model": "private-transcription-model",
            "language": "bg",
            "error": "provider.example request failed",
        },
    }
    now = datetime.now(UTC)
    response = PhoneLogResponse(
        id=uuid4(),
        project_id=uuid4(),
        direction="incoming",
        channel="phone",
        transcript="Please send new drawings.",
        metadata=original_metadata,
        created_at=now,
        updated_at=now,
    )
    public = response.model_dump()
    assert public["transcript"] == "Please send new drawings."
    assert public["metadata"]["protocol"] == original_metadata["protocol"]
    assert public["metadata"]["transcription"] == {
        "available": True,
        "language": "bg",
        "error": workspace.PUBLIC_AI_ERROR,
    }
    assert response.metadata["transcription"]["model"] == "private-transcription-model"
    assert original_metadata["transcription"]["provider"] == "openai"


def test_personal_transcription_metadata_is_unchanged(monkeypatch):
    from app.modules.voice.schemas import TranscriptionInfo

    monkeypatch.setattr(workspace, "_current", None)
    transcription = TranscriptionInfo(available=True, model="personal-model", error="personal configuration error")
    assert transcription.model_dump()["model"] == "personal-model"
    assert transcription.model_dump()["error"] == "personal configuration error"


@pytest.mark.parametrize(
    ("schema_name", "fields"),
    [
        ("EnhanceDescriptionResponse", {"enhanced_description": "Concrete C25", "confidence": 0.8}),
        ("SuggestPrerequisitesResponse", {"suggestions": []}),
        ("CheckScopeResponse", {"completeness_score": 0.9, "summary": "Scope reviewed."}),
        ("EscalateRateResponse", {"escalation_percent": 10, "original_rate": "10", "escalated_rate": "11"}),
    ],
)
def test_boq_ai_result_serializers_hide_model_without_changing_results(workspace_ai, schema_name, fields):
    from app.modules.boq import schemas

    response = getattr(schemas, schema_name)(**fields, model_used="private-model-id", tokens_used=42)
    public = response.model_dump(mode="json")
    assert public["model_used"] == ""
    assert public["tokens_used"] == 42
    assert response.model_used == "private-model-id"
    for key, value in fields.items():
        assert public[key] == value


def test_personal_boq_ai_result_retains_model(monkeypatch):
    from app.modules.boq.schemas import EnhanceDescriptionResponse

    monkeypatch.setattr(workspace, "_current", None)
    result = EnhanceDescriptionResponse(enhanced_description="Concrete", model_used="personal-model")
    assert result.model_dump()["model_used"] == "personal-model"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_failure", [False, True])
async def test_smart_import_hides_workspace_model_and_provider_errors(monkeypatch, workspace_ai, provider_failure):
    from io import BytesIO

    from fastapi import HTTPException, Response, UploadFile

    from app.modules.ai import ai_client
    from app.modules.ai.repository import AISettingsRepository
    from app.modules.boq import router as boq_router
    from app.modules.projects.repository import ProjectRepository

    user_id = str(uuid4())
    service = SimpleNamespace(
        _ensure_boq_writable=AsyncMock(),
        get_boq=AsyncMock(return_value=SimpleNamespace(project_id=uuid4())),
        add_position=AsyncMock(),
    )
    monkeypatch.setattr(boq_router, "_verify_boq_owner", AsyncMock())
    monkeypatch.setattr(boq_router, "_extract_from_pdf", lambda _: {"text": "Concrete 10 m3", "structured": False})
    monkeypatch.setattr(ProjectRepository, "get_by_id", AsyncMock(return_value=SimpleNamespace(currency="EUR")))
    monkeypatch.setattr(AISettingsRepository, "get_by_user_id", AsyncMock(return_value=None))
    monkeypatch.setattr(
        ai_client, "resolve_provider_key_model", lambda _: ("deepseek", "private-key", "private-model-id")
    )
    provider = AsyncMock(return_value=('[{"description":"Concrete","unit":"m3","quantity":10,"unit_rate":50}]', 20))
    if provider_failure:
        provider.side_effect = ValueError("deepseek rejected private-model-id at provider.example")
    monkeypatch.setattr(ai_client, "call_ai", provider)
    kwargs = {
        "boq_id": uuid4(),
        "user_id": user_id,
        "payload": {},
        "response": Response(),
        "file": UploadFile(filename="input.pdf", file=BytesIO(b"mock PDF")),
        "session": object(),
        "service": service,
    }
    if provider_failure:
        with pytest.raises(HTTPException) as raised:
            await boq_router.smart_import(**kwargs)
        assert raised.value.status_code == 502
        assert raised.value.detail == workspace.PUBLIC_AI_ERROR
        service.add_position.assert_not_awaited()
    else:
        result = await boq_router.smart_import(**kwargs)
        assert result["imported"] == 1
        assert result["model_used"] is None
        service.add_position.assert_awaited_once()
        assert service.add_position.await_args.args[0].description == "Concrete"
        assert service.add_position.await_args.args[0].quantity == 10
