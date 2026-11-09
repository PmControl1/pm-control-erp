"""Available stock add-ons match the Bulgarian product and working installers."""

from __future__ import annotations

import pytest

from app.core import marketplace
from app.core.converter_source import PACKAGES
from app.core.market_profile import MARKET_COST_REGION
from app.modules.costs.base_registry import github_catalog_folder, variant_by_region


def test_available_data_and_languages_are_bulgarian_with_english_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEED_DEMO", "false")
    modules = marketplace.get_marketplace_catalog()
    assert {m["id"] for m in modules if m["category"] == "cost_database"} == {"cwicr-bg-sofia"}
    assert {m["id"] for m in modules if m["category"] == "resource_catalog"} == {"catalog-bg-sofia"}
    assert {m["id"] for m in modules if m["category"] == "language"} == {"lang-bg", "lang-en"}
    assert all(m["installed"] for m in modules if m["category"] == "language")
    assert not any(m["category"] == "demo_project" for m in modules)


@pytest.mark.parametrize(
    "foreign_id",
    ["cwicr-de-berlin", "catalog-usa-usd", "vector-uk-gbp", "demo-office-london", "lang-de"],
)
def test_foreign_stock_ids_are_unavailable_even_by_direct_lookup(foreign_id: str) -> None:
    assert marketplace.get_marketplace_module(foreign_id) is None


def test_bulgarian_resource_catalogue_has_real_registry_mapping_and_installed_state() -> None:
    variant = variant_by_region(MARKET_COST_REGION)
    assert variant is not None
    assert variant.lang_code == "bg"
    assert github_catalog_folder(MARKET_COST_REGION)
    assert variant.currency == "BGN"

    def resource_entry(loaded_regions: set[str]) -> dict:
        return next(
            entry for entry in marketplace.get_marketplace_catalog(loaded_regions) if entry["id"] == "catalog-bg-sofia"
        )

    assert not resource_entry({"DE_BERLIN"})["installed"]
    assert resource_entry({MARKET_COST_REGION})["installed"]
    assert "BGN" in marketplace.get_marketplace_module("cwicr-bg-sofia").description


def test_marketplace_keeps_semantic_setup_in_the_cost_workflow() -> None:
    assert not any(entry["category"] == "vector_index" for entry in marketplace.get_marketplace_catalog())
    assert marketplace.get_marketplace_module("vector-bg-sofia") is None


def test_shared_converters_remain_available_with_their_current_versions() -> None:
    for name in ("dwg", "rvt", "ifc"):
        entry = marketplace.get_marketplace_module(f"converter-{name}")
        assert entry is not None
        assert entry.version == PACKAGES[name].version
        assert entry.category == "converter"
    assert marketplace.get_marketplace_module("converter-pdf-ocr") is not None
    assert marketplace.get_marketplace_module("analytics-co2") is not None
    assert marketplace.get_marketplace_module("analytics-benchmarks") is not None


def test_sofia_sample_follows_the_existing_sample_enable_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEED_DEMO", "false")
    assert marketplace.get_marketplace_module("demo-residential-sofia") is None
    monkeypatch.setenv("SEED_DEMO", "true")
    entries = marketplace.get_marketplace_catalog()
    assert {m["id"] for m in entries if m["category"] == "demo_project"} == {"demo-residential-sofia"}
    assert marketplace.get_marketplace_module("demo-residential-sofia") is not None
