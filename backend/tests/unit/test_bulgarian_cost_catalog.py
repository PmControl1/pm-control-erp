"""Bulgarian reference downloads are narrow; saved foreign costs retain their units."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.core.market_profile import MARKET_COST_REGION
from app.modules.costs import base_registry


def test_market_projection_offers_sofia_without_changing_native_currency() -> None:
    catalog = base_registry.public_catalog(
        {"BG_SOFIA": 55_719, "USA_USD": 40},
        allowed_regions=frozenset({MARKET_COST_REGION}),
    )
    variants = [v for family in catalog["families"] for v in family["variants"]]
    assert [(v["region"], v["currency"], v["loaded"]) for v in variants] == [("BG_SOFIA", "BGN", True)]
    assert catalog["total_bases"] == catalog["total_families"] == 1
    assert catalog["families"][0]["market_count"] == 1
    assert catalog["loaded_regions"] == ["BG_SOFIA", "USA_USD"]
    assert base_registry.variant_by_region("USA_USD").currency == "USD"


@pytest.mark.asyncio
async def test_available_downloads_only_offer_sofia() -> None:
    from app.modules.costs import router

    choices = await router.list_available_databases()
    assert [choice["id"] for choice in choices] == [MARKET_COST_REGION]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "arguments"),
    [
        ("load_cwicr_database", {"db_id": "USA_USD", "session": None}),
        ("load_vector_from_github", {"db_id": "DE_BERLIN", "session": None}),
        ("restore_qdrant_snapshot", {"db_id": "USA_USD"}),
        ("install_v3_catalogue", {"region": "DE_BERLIN"}),
        ("load_base_market", {"base_region": "ZH_CHINA", "market_token": "BG_SOFIA_bg", "session": None}),
        ("restore_base_home_market", {"base_region": "ZH_CHINA", "session": None}),
    ],
)
async def test_foreign_stock_installers_refuse_before_loading(handler: str, arguments: dict) -> None:
    from app.modules.costs import router

    with pytest.raises(HTTPException) as failure:
        await getattr(router, handler)(_user_id="test-user", **arguments)
    assert failure.value.status_code == 404
    assert "Bulgarian product" in failure.value.detail


@pytest.mark.asyncio
async def test_sofia_uses_the_shared_cost_importer(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.costs import router

    importer = AsyncMock(return_value={"status": "loaded", "region": MARKET_COST_REGION})
    monkeypatch.setattr(router, "load_cwicr_region", importer)
    session = object()
    result = await router.load_cwicr_database(MARKET_COST_REGION, session, "test-user")
    importer.assert_awaited_once_with(MARKET_COST_REGION, session)
    assert result["region"] == MARKET_COST_REGION


@pytest.mark.asyncio
async def test_resource_downloads_refuse_foreign_but_keep_sofia_importer(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.catalog import router

    importer = AsyncMock(return_value={"imported": 20, "region": MARKET_COST_REGION})
    monkeypatch.setattr(router, "import_region_catalog", importer)
    session = object()
    with pytest.raises(HTTPException) as failure:
        await router.import_catalog_from_github("DE_BERLIN", session, "test-user")
    assert failure.value.status_code == 404
    importer.assert_not_awaited()
    result = await router.import_catalog_from_github(MARKET_COST_REGION, session, "test-user")
    importer.assert_awaited_once_with(session, MARKET_COST_REGION)
    assert result["imported"] == 20


@pytest.mark.asyncio
async def test_v3_catalogue_picker_only_lists_sofia(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.costs import router

    monkeypatch.setattr(router, "_v3_qdrant_url", lambda: None)
    result = await router.list_v3_catalogues()
    assert [choice["region"] for choice in result["catalogues"]] == [MARKET_COST_REGION]


def test_legacy_cost_currency_resolution_is_preserved() -> None:
    from app.modules.costs.router import _resolve_currency

    assert _resolve_currency(None, "BG_SOFIA") == "BGN"
    assert _resolve_currency(None, "USA_USD") == "USD"
    assert _resolve_currency(None, "DE_BERLIN") == "EUR"
