"""The public product selects Bulgaria without rewriting legacy records."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.partner_pack import discovery, scope
from app.core.partner_pack import router as packs_router
from app.core.partner_pack.manifest import PartnerPackManifest
from app.dependencies import get_current_user_id
from app.modules.projects import router as projects_router
from app.modules.projects.models import Project
from app.modules.projects.schemas import BulgariaProjectCreate, ProjectCreate, ProjectUpdate
from app.modules.users.schemas import AdminUserCreate, UserCreate


@pytest.fixture
def project_api() -> tuple[TestClient, AsyncMock]:
    app = FastAPI()
    service = SimpleNamespace(create_project=AsyncMock())
    now = datetime.now(UTC)

    async def create(data: ProjectCreate, owner_id: uuid.UUID) -> SimpleNamespace:
        fields = data.model_dump()
        fields["fx_rates"] = fields["fx_rates"] or []
        fields["custom_units"] = fields["custom_units"] or []
        return SimpleNamespace(
            **fields,
            id=uuid.uuid4(),
            owner_id=owner_id,
            status="active",
            metadata_={},
            created_at=now,
            updated_at=now,
        )

    service.create_project.side_effect = create
    app.include_router(projects_router.router, prefix="/projects")
    app.dependency_overrides[get_current_user_id] = lambda: str(uuid.uuid4())
    app.dependency_overrides[projects_router._get_service] = lambda: service
    return TestClient(app), service.create_project


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"region": "", "country_code": None, "currency": "", "locale": ""},
        {"region": "България", "address": {"country": "България", "city": "Пловдив"}},
        {"region": " bg ", "country_code": " bg ", "currency": " eur "},
    ],
)
def test_public_create_selects_bulgaria_without_market_setup(
    project_api: tuple[TestClient, AsyncMock], fields: dict[str, object]
) -> None:
    client, create = project_api
    response = client.post("/projects/", json={"name": "Обект Пловдив", **fields})
    assert response.status_code == 201, response.text
    payload = response.json()
    assert (payload["country_code"], payload["region"], payload["currency"], payload["locale"]) == (
        "BG",
        "BG",
        "EUR",
        "bg",
    )
    assert payload["classification_standard"] == ""
    assert isinstance(create.call_args.args[0], BulgariaProjectCreate)


@pytest.mark.parametrize(
    "fields",
    [
        {"country_code": "DE"},
        {"region": "DACH"},
        {"country_code": "BG", "address": {"country": "Germany"}},
        {"currency": "BGN"},
        {"currency": "USD"},
    ],
)
def test_public_create_refuses_foreign_market_without_creating_a_record(
    project_api: tuple[TestClient, AsyncMock], fields: dict[str, object]
) -> None:
    client, create = project_api
    response = client.post("/projects/", json={"name": "New site", **fields})
    assert response.status_code == 422
    create.assert_not_called()


def test_english_and_legacy_edit_data_are_preserved() -> None:
    assert BulgariaProjectCreate(name="Site", locale="en").locale == "en"
    legacy = ProjectUpdate(country_code="DE", region="DACH", currency="USD", locale="de")
    assert legacy.model_dump(exclude_unset=True) == {
        "country_code": "DE",
        "region": "DACH",
        "currency": "USD",
        "locale": "de",
    }
    # The internal schema remains available to historical import workflows.
    assert ProjectCreate(name="Imported", country_code="DE").country_code == "DE"


def test_clean_install_and_stale_foreign_selection_use_bulgarian_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    bg = discovery.get_pack_by_slug("bulgaria-bg")
    assert bg is not None
    foreign = PartnerPackManifest(slug="foreign-old", partner_name="Old", metadata={"country": "DE"})
    for old_selection in (None, foreign):
        monkeypatch.setattr(discovery, "_get_active_pack_cached", lambda _dir, value=old_selection: value)
        assert discovery.get_active_pack() is bg


def test_bulgarian_default_does_not_hide_legacy_pack_projects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scope, "active_pack_slug", lambda: "bulgaria-bg")
    query = select(Project)
    assert scope.scope_project_query(query, Project) is query


def test_only_bulgarian_pack_is_offered_and_foreign_activation_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    bg = discovery.get_pack_by_slug("bulgaria-bg")
    assert bg is not None
    foreign = PartnerPackManifest(slug="foreign-old", partner_name="Old", metadata={"country": "DE"})
    monkeypatch.setattr(packs_router, "discover_packs", lambda: [foreign, bg])
    monkeypatch.setattr(packs_router, "get_active_pack", lambda: bg)
    assert [item["slug"] for item in packs_router.list_installed()["installed"]] == ["bulgaria-bg"]
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        packs_router.apply_preview("foreign-old")
    assert error.value.status_code == 409


def test_new_accounts_default_to_bulgarian_with_english_available() -> None:
    fields = {"email": "user@example.com", "password": "SafeTestPassword123", "full_name": "Тест"}
    assert UserCreate(**fields).locale == "bg"
    assert AdminUserCreate(**fields).locale == "bg"
    assert UserCreate(**fields, locale="en").locale == "en"


def test_new_buyer_and_sales_documents_default_to_bulgarian() -> None:
    from app.modules.property_dev.schemas import (
        BuyerCreate,
        LeadCreate,
        PlotReserveRequest,
        ReservationConvertToSpaRequest,
        SalesContractCreate,
    )

    cases = [
        (BuyerCreate, {"development_id": uuid.uuid4()}),
        (LeadCreate, {}),
        (PlotReserveRequest, {}),
        (ReservationConvertToSpaRequest, {"signing_date": "2026-11-09", "total_value": "100", "currency": "EUR"}),
        (SalesContractCreate, {"plot_id": uuid.uuid4()}),
    ]
    for schema, fields in cases:
        assert schema(**fields).language == "bg"
        assert schema(**fields, language="en").language == "en"
