"""Workspace members get AI readiness, while execution details stay internal."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.modules.ai import workspace
from app.modules.ai_estimator import schemas


@pytest.fixture
def shared_ai():
    previous = workspace.current()
    workspace.set_current(workspace.WorkspaceAI("private-provider", "secret", "private-model", "", True))
    yield
    workspace.set_current(previous)


def _run_data() -> dict:
    return {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "run_id": uuid.uuid4(),
        "name": "Concrete estimate",
        "status": "draft",
        "current_stage": "source",
        "provider": "private-provider",
        "model_used": "private-model",
        "failure_reason": "private-provider rejected private-model at https://private.example",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


@pytest.mark.parametrize(
    "schema", [schemas.RunRead, schemas.RunSummary, schemas.ProgressResponse, schemas.ReadinessResponse]
)
def test_estimator_serializers_hide_identity_without_changing_audit_values(shared_ai, schema) -> None:
    response = schema.model_validate(_run_data())
    public = response.model_dump(mode="json")

    assert public["model_used"] is None
    if "provider" in public:
        assert public["provider"] is None
    if "failure_reason" in public:
        assert public["failure_reason"] == workspace.PUBLIC_AI_ERROR
    assert response.model_used == "private-model"


def test_personal_provider_estimator_metadata_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workspace, "_current", None)
    response = schemas.RunRead.model_validate(_run_data())
    public = response.model_dump(mode="json")
    assert public["provider"] == "private-provider"
    assert public["model_used"] == "private-model"
    assert "private-provider rejected" in public["failure_reason"]


def test_step_errors_are_private_but_project_model_data_is_preserved(shared_ai) -> None:
    base = {"id": uuid.uuid4(), "stage": "source", "step_idx": 1, "created_at": datetime.now(UTC)}
    failed = schemas.StepOut(**base, role="observation", content={"degraded": "llm_error", "message": "private-model"})
    assert failed.model_dump()["content"]["message"] == workspace.PUBLIC_AI_ERROR
    internal = {"detected": {"model": "User-supplied building model"}, "provider": "private-provider"}
    normal = schemas.StepOut(**base, role="answer", content=internal)
    assert normal.model_dump()["content"] == {"detected": {"model": "User-supplied building model"}}
    assert internal["provider"] == "private-provider"


def test_plan_reading_keeps_results_and_failure_codes_without_ai_identity(shared_ai) -> None:
    from app.modules.takeoff.schemas import AiTakeoffRunResponse, PlanReadMetaResponse

    result = AiTakeoffRunResponse(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        status="failed",
        provider="private-provider",
        model_used="private-model",
        failure_reason="cost_cap",
        proposal_count=3,
    )
    public = result.model_dump(mode="json")
    assert public["provider"] is None and public["model_used"] is None
    assert public["failure_reason"] == "cost_cap" and public["proposal_count"] == 3
    assert result.model_used == "private-model"
    meta = PlanReadMetaResponse(
        provider="private-provider",
        model_used="private-model",
        vision_providers=["private-provider"],
        reason="private-model unavailable",
    )
    public_meta = meta.model_dump(mode="json")
    assert public_meta["provider"] is None and public_meta["model_used"] is None
    assert public_meta["vision_providers"] == [] and public_meta["reason"] == workspace.PUBLIC_AI_ERROR


@pytest.mark.asyncio
async def test_embedding_status_reports_progress_without_model_or_host_details(shared_ai, monkeypatch) -> None:
    from app.core import embedding_installer
    from app.modules.ai_estimator import router

    private = {
        "state": "ready",
        "enabled": True,
        "installed": True,
        "percent": 100,
        "semantic_enabled": True,
        "locked": False,
        "semantic_locked": False,
        "model": "private-model",
        "install_path": "/private/model",
        "error": "private-provider",
        "embedder": {"model": "private-model"},
        "message": "private-model ready",
    }
    monkeypatch.setattr(embedding_installer, "download_status", lambda: dict(private))
    owner_check = AsyncMock(return_value=False)
    monkeypatch.setattr(workspace, "is_owner_user", owner_check)
    session = object()
    public = await router.embedding_model_status("member", session)
    assert public == {
        key: private[key]
        for key in ("state", "enabled", "installed", "percent", "semantic_enabled", "locked", "semantic_locked")
    }
    owner_check.return_value = True
    assert await router.embedding_model_status("owner", session) == private


@pytest.mark.asyncio
async def test_vector_health_hides_url_and_disk_paths(shared_ai, monkeypatch) -> None:
    from app.modules.ai_estimator import router
    from app.modules.match_elements import qdrant_supervisor

    health = SimpleNamespace(reachable=True, installed=True, url="http://private:6333", storage_dir="/private/data")
    monkeypatch.setattr(qdrant_supervisor, "ensure_qdrant_running", lambda *a, **k: health)
    monkeypatch.setattr(workspace, "is_owner_user", AsyncMock(return_value=False))
    public = await router.qdrant_health("member", object())
    assert public == {"reachable": True, "installed": True, "message": "Semantic search is ready."}


@pytest.mark.asyncio
async def test_search_diagnostics_are_owner_only(shared_ai, monkeypatch) -> None:
    from app.modules.search import router
    from app.modules.search.schemas import SearchStatusResponse

    private = SearchStatusResponse(
        backend="qdrant",
        engine="sentence-transformers",
        model_name="private-model",
        embedding_dim=1024,
        connected=True,
        cost_collection={"host": "private"},
    )
    monkeypatch.setattr(router, "search_status_snapshot", lambda: private)
    owner_check = AsyncMock(return_value=False)
    monkeypatch.setattr(workspace, "is_owner_user", owner_check)
    public = await router.search_status_endpoint("member", object())
    assert public.connected
    assert not public.backend and not public.engine and not public.model_name
    assert public.embedding_dim == 0 and public.cost_collection is None
    owner_check.return_value = True
    assert await router.search_status_endpoint("owner", object()) is private


@pytest.mark.asyncio
async def test_member_cannot_download_models_to_bypass_owner_configuration(shared_ai, monkeypatch) -> None:
    from fastapi import HTTPException

    from app.core import embedding_installer
    from app.modules.ai_estimator import router

    monkeypatch.setattr(workspace, "is_owner_user", AsyncMock(return_value=False))
    start = AsyncMock()
    monkeypatch.setattr(embedding_installer, "start_background_download", start)
    with pytest.raises(HTTPException) as denied:
        await router.embedding_model_install("member", object())
    assert denied.value.status_code == 403
    start.assert_not_called()


@pytest.mark.asyncio
async def test_match_vector_diagnostics_do_not_bypass_owner_visibility(shared_ai, monkeypatch) -> None:
    from fastapi import HTTPException

    from app.modules.match_elements import qdrant_supervisor, router

    health = SimpleNamespace(
        reachable=True,
        installed=True,
        url="http://private:6333",
        binary_path="/private/qdrant",
        storage_dir="/private/data",
        download_url="https://private.example/qdrant",
        install_hint="Run /private/bin/install",
    )
    probe = Mock(return_value=health)
    monkeypatch.setattr(qdrant_supervisor, "ensure_qdrant_running", probe)
    owner_check = AsyncMock(return_value=False)
    monkeypatch.setattr(workspace, "is_owner_user", owner_check)
    public = await router.qdrant_health("member", object())
    assert public == {"reachable": True, "installed": True, "message": "Semantic search is ready."}
    owner_check.return_value = True
    assert (await router.qdrant_health("owner", object()))["binary_path"] == "/private/qdrant"

    owner_check.return_value = False
    probe.side_effect = RuntimeError("Cannot write /private/data for private-model")
    with pytest.raises(HTTPException) as failed:
        await router.qdrant_health("member", object())
    assert failed.value.status_code == 502 and failed.value.detail == workspace.PUBLIC_AI_ERROR


@pytest.mark.asyncio
async def test_match_vector_install_is_workspace_owner_only(shared_ai, monkeypatch) -> None:
    from fastapi import HTTPException

    from app.modules.match_elements import qdrant_supervisor, router

    monkeypatch.setattr(workspace, "is_owner_user", AsyncMock(return_value=False))
    install = Mock()
    monkeypatch.setattr(qdrant_supervisor, "install_qdrant_native", install)
    with pytest.raises(HTTPException) as denied:
        await router.qdrant_install("member", object())
    assert denied.value.status_code == 403
    install.assert_not_called()
