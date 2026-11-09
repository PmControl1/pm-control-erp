"""Alternate setup/download surfaces honour the Bulgarian product market."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.job_run import JobRun
from app.dependencies import get_current_user_id, get_session
from app.modules.onboarding import router as onboarding_router
from app.modules.onboarding.schemas import ProvisionRequest
from app.modules.users.models import User


@pytest.fixture
def setup_api(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, AsyncMock]:
    app = FastAPI()
    app.include_router(onboarding_router.router, prefix="/onboarding")
    app.dependency_overrides[get_current_user_id] = lambda: str(uuid.uuid4())

    async def session() -> Any:
        yield object()

    app.dependency_overrides[get_session] = session
    monkeypatch.setattr(onboarding_router, "_attempt_key", AsyncMock(return_value="setup-test"))

    async def submit(kind: str, payload: dict[str, Any], **_kwargs: Any) -> JobRun:
        return JobRun(id=uuid.uuid4(), kind=kind, status="pending", progress_percent=0, payload_jsonb=payload)

    submit_job = AsyncMock(side_effect=submit)
    monkeypatch.setattr(onboarding_router, "submit_job", submit_job)
    return TestClient(app), submit_job


@pytest.mark.parametrize(
    "body",
    [
        {"region": "DE_BERLIN"},
        {"region": "ENG_TORONTO"},
        {"demo_ids": ["office-london"]},
        {"region": "BG_SOFIA", "demo_ids": ["residential-berlin"]},
    ],
)
def test_foreign_provisioning_is_refused_before_queuing_jobs(
    setup_api: tuple[TestClient, AsyncMock], body: dict[str, Any]
) -> None:
    client, submit = setup_api
    response = client.post("/onboarding/provision", json=body)
    assert response.status_code == 422
    submit.assert_not_called()


def test_bulgarian_cost_setup_still_submits_the_real_job(setup_api: tuple[TestClient, AsyncMock]) -> None:
    client, submit = setup_api
    response = client.post("/onboarding/provision", json={"region": " bg_sofia "})
    assert response.status_code == 200, response.text
    assert len(response.json()["jobs"]) == 1
    assert submit.call_args.args[1]["db_id"] == "BG_SOFIA"
    assert ProvisionRequest().region is None  # downloads remain optional


def test_disabled_demos_are_skipped_without_blocking_the_cost_catalogue(
    setup_api: tuple[TestClient, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEED_DEMO", "false")
    client, submit = setup_api
    response = client.post("/onboarding/provision", json={"region": "BG_SOFIA", "demo_ids": ["residential-sofia"]})
    assert response.status_code == 200, response.text
    assert response.json()["skipped_demo_ids"] == ["residential-sofia"]
    assert response.json()["demo_skip_reason"]
    submit.assert_called_once()
    assert submit.call_args.args[1]["db_id"] == "BG_SOFIA"


@pytest.mark.asyncio
async def test_demo_catalog_and_install_offer_sofia_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import create_app

    app = create_app()
    endpoints = {route.path: route.endpoint for route in app.routes if hasattr(route, "endpoint")}
    monkeypatch.setenv("SEED_DEMO", "true")
    catalog = await endpoints["/api/demo/catalog"]()
    assert [entry["demo_id"] for entry in catalog] == ["residential-sofia"]
    with pytest.raises(HTTPException) as failure:
        await endpoints["/api/demo/install/{demo_id}"]("office-london", _user_id=str(uuid.uuid4()))
    assert failure.value.status_code == 404
    monkeypatch.setenv("SEED_DEMO", "false")
    assert await endpoints["/api/demo/catalog"]() == []


def test_new_account_regional_defaults_are_bulgarian() -> None:
    assert User.__table__.c.timezone.default.arg == "Europe/Sofia"
    assert User.__table__.c.currency_code.default.arg == "EUR"


@pytest.mark.asyncio
async def test_pack_install_skips_disabled_demos_and_keeps_cost_setup_successful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.core.demo_projects as demo_projects
    from app.core.partner_pack import full_install as install

    monkeypatch.setenv("SEED_DEMO", "false")
    create_demo = AsyncMock()
    monkeypatch.setattr(demo_projects, "install_demo_project", create_demo)
    monkeypatch.setattr(
        install, "_step_apply_pack", AsyncMock(return_value=install.StepResult(step="apply_pack", status="ok"))
    )
    load_costs = AsyncMock(
        return_value=(install.StepResult(step="cost_db", status="ok", detail={"regions": ["BG_SOFIA"]}), ["BG_SOFIA"])
    )
    monkeypatch.setattr(install, "_step_cost_db", load_costs)
    result = await install.full_install(
        install.FullInstallRequest(slug="bulgaria-bg", set_locale=False, vectorize=False, demo_count=2)
    )
    assert result.ok
    load_costs.assert_awaited_once()
    demos = next(step for step in result.steps if step.step == "demos")
    assert demos.status == "skipped"
    assert demos.detail["reason_code"] == "demo_disabled"
    create_demo.assert_not_awaited()

    frames = [
        frame
        async for frame in install.full_install_stream(
            install.FullInstallRequest(slug="bulgaria-bg", only_steps=["demos"], demo_count=2)
        )
    ]
    completed = next(frame for frame in frames if frame.startswith("event: done\n"))
    stream_result = json.loads(completed.split("data: ", 1)[1])
    assert stream_result["ok"]
    assert stream_result["steps"][0]["detail"]["reason_code"] == "demo_disabled"
    create_demo.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_pack_apply_respects_disabled_demo_projects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.core.partner_pack.apply import apply_pack
    from app.core.partner_pack.discovery import reset_cache
    from app.core.partner_pack.state import load_applied_state

    monkeypatch.setenv("SEED_DEMO", "false")
    monkeypatch.setenv("OE_CLI_DATA_DIR", str(tmp_path))
    create_demo = AsyncMock()
    monkeypatch.setattr("app.core.demo_projects.install_demo_project", create_demo)
    reset_cache()
    try:
        result = await apply_pack("bulgaria-bg", install_demo=True)
        assert result["applied"]
        assert load_applied_state().slug == "bulgaria-bg"
        assert "demo_project" not in result["effects"]
        create_demo.assert_not_awaited()
    finally:
        reset_cache()
