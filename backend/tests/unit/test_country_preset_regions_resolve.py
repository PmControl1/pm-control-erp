# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Bulgarian setup preset resolves across every cost-data surface.

Global registry/alias integrity remains covered for existing imported projects;
new setup choices must expose only the Bulgarian market.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.modules.costs import base_registry


def _repo_root() -> Path:
    """Walk up until a directory holds both halves of the repository."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "backend").is_dir() and (parent / "frontend").is_dir():
            return parent
    raise RuntimeError(f"repository root not found from {__file__}")


_FRONTEND = _repo_root() / "frontend" / "src"

COUNTRY_PACKS_TS = _FRONTEND / "features" / "onboarding" / "countryPacks.ts"

# One preset object literal. Anchored on ``id`` and ``region`` together so a
# stray ``region`` in a doc comment cannot be mistaken for an entry.
_PRESET = re.compile(r"\{\s*\n\s*id:\s*'(?P<id>[a-z-]+)',.*?\n\s*region:\s*'(?P<region>[A-Z0-9_]+)',", re.S)

# An ``{ id: 'X', ... }`` row in a list-shaped mirror.
_ROW_ID = re.compile(r"\{\s*id:\s*'([A-Z0-9_]+)'")

# A ``KEY: { ... }`` entry in a record-shaped mirror.
_RECORD_KEY = re.compile(r"^\s{2}([A-Z][A-Z0-9_]*):\s*\{", re.M)

# The frontend copies of the cost-base id list, each maintained by hand.
# The advisor selects one fixed product region rather than offering a list;
# its value is checked separately below.
MIRRORS: tuple[tuple[str, Path, str, re.Pattern[str]], ...] = (
    ("REGION_MAP", _FRONTEND / "stores" / "useCostDatabaseStore.ts", "REGION_MAP", _RECORD_KEY),
    (
        "CWICR_DATABASES (onboarding)",
        _FRONTEND / "features" / "onboarding" / "OnboardingWizard.tsx",
        "CWICR_DATABASES",
        _ROW_ID,
    ),
    (
        "CWICR_DATABASES (import)",
        _FRONTEND / "features" / "costs" / "ImportDatabasePage.tsx",
        "CWICR_DATABASES",
        _ROW_ID,
    ),
    ("CWICR_REGIONS", _FRONTEND / "features" / "catalog" / "CatalogPage.tsx", "CWICR_REGIONS", _ROW_ID),
)

# Ids a mirror may carry that the registry does not load. ``CUSTOM`` is the tag
# stamped on a user's own items, not a published base.
NOT_A_LOADABLE_BASE = frozenset({"CUSTOM"})

ONBOARDING_WIZARD_TSX = _FRONTEND / "features" / "onboarding" / "OnboardingWizard.tsx"


def _read_block(path: Path, const_name: str) -> str:
    """The source of one array/record literal, from its name to its closing line."""
    source = path.read_text(encoding="utf-8")
    marker = f"const {const_name}"
    if marker not in source:
        pytest.fail(f"{path.name} no longer declares `{marker}`; this mirror was renamed or removed")
    body = source.split(marker, 1)[1]
    end = re.search(r"^\];|^\};", body, re.M)
    return body[: end.start()] if end else body


def _presets() -> list[tuple[str, str]]:
    """Parse ``(preset id, region id)`` pairs out of the shipped preset table."""
    source = COUNTRY_PACKS_TS.read_text(encoding="utf-8")
    body = source
    found = [(m.group("id"), m.group("region")) for m in _PRESET.finditer(body)]
    if not found:
        pytest.fail(f"parsed no presets out of {COUNTRY_PACKS_TS}; the table shape changed")
    return found


def _mirror_ids(name: str, path: Path, const_name: str, pattern: re.Pattern[str]) -> set[str]:
    """The region ids one mirror declares."""
    ids = set(pattern.findall(_read_block(path, const_name)))
    if not ids:
        pytest.fail(f"parsed no ids out of {name} in {path.name}; the literal shape changed")
    return ids


def _registry_regions() -> set[str]:
    """Every region id the backend can actually load a base for."""
    return {v.region for v in base_registry.iter_variants()}


def test_the_parsers_still_see_the_tables_they_are_pointed_at() -> None:
    """Guard every parser, so a silent zero can never read as a pass."""
    presets = _presets()
    assert presets == [("bg", "BG_SOFIA")], "setup must offer the Bulgarian preset only"
    for name, path, const_name, pattern in MIRRORS:
        ids = _mirror_ids(name, path, const_name, pattern)
        assert "BG_SOFIA" in ids, f"{name} cannot name the Bulgarian catalogue"
        if name != "REGION_MAP":
            assert ids == {"BG_SOFIA"}, f"{name} still offers foreign catalogue choices: {sorted(ids)}"
    assert "BG_SOFIA" in _registry_regions(), "the shared registry cannot load Sofia"


def test_every_preset_region_is_a_base_the_backend_can_load() -> None:
    """The direction no frontend check has: all four mirrors can be wrong together."""
    known = _registry_regions()
    unresolved = sorted({(pack, region) for pack, region in _presets() if region not in known})
    assert not unresolved, (
        f"{len(unresolved)} preset(s) name a region the base registry cannot load: {unresolved}. "
        f"A preset installs its region id verbatim, so an id that is not in the registry is a "
        f"one-click button that sets up an empty cost database."
    )


@pytest.mark.parametrize("name,path,const_name,pattern", MIRRORS, ids=[m[0] for m in MIRRORS])
def test_every_preset_region_resolves_in_every_mirror(
    name: str, path: Path, const_name: str, pattern: re.Pattern[str]
) -> None:
    """Red when a preset names an unknown id, and when a mirror loses one it needs."""
    ids = _mirror_ids(name, path, const_name, pattern)
    missing = sorted({(pack, region) for pack, region in _presets() if region not in ids})
    assert not missing, (
        f"{len(missing)} preset region(s) are absent from {name} in {path.name}: {missing}. "
        f"A region with no entry there has no label, no flag and no card, so the base the user "
        f"installed is unnameable in that surface - which is what made rewriting the id to a "
        f"different base look like a fix."
    )


@pytest.mark.parametrize("name,path,const_name,pattern", MIRRORS, ids=[m[0] for m in MIRRORS])
def test_no_mirror_offers_a_base_the_backend_cannot_load(
    name: str, path: Path, const_name: str, pattern: re.Pattern[str]
) -> None:
    """A card for an id the registry lacks is a button that loads nothing."""
    known = _registry_regions() | NOT_A_LOADABLE_BASE
    unknown = sorted(_mirror_ids(name, path, const_name, pattern) - known)
    assert not unknown, f"{name} in {path.name} offers {len(unknown)} id(s) the registry cannot load: {unknown}"


def test_the_two_conflated_pairs_are_four_separate_bases() -> None:
    """Pin the fact the alias got wrong, so it cannot be re-asserted quietly.

    Asking the registry rather than restating the claim. If these four ever
    collapse into two, the alias was right after all and this whole file is
    wrong, which is a conversation worth forcing rather than a silent merge.
    """
    pairs = (("ZH_SHANGHAI", "ZH_CHINA"), ("TR_ISTANBUL", "TR_NATIONAL"))
    for market_id, national_id in pairs:
        market = base_registry.variant_by_region(market_id)
        national = base_registry.variant_by_region(national_id)
        assert market is not None, f"{market_id} is no longer a loadable base"
        assert national is not None, f"{national_id} is no longer a loadable base"
        assert not base_registry.is_national_region(market_id), f"{market_id} became a national base"
        assert base_registry.is_national_region(national_id), f"{national_id} stopped being a national base"
        assert market.workitems_path != national.workitems_path, (
            f"{market_id} and {national_id} now read the same work items, so they are one base "
            f"after all and the aliasing this file forbids would be correct"
        )


def test_the_advisor_uses_the_registered_bulgarian_market() -> None:
    """The fixed advisor market resolves to the same real Sofia catalogue."""
    source = (_FRONTEND / "features" / "ai" / "AdvisorPage.tsx").read_text(encoding="utf-8")
    selected = re.search(r"const region = '([A-Z0-9_]+)'", source)
    assert selected is not None, "the advisor's product market is missing"
    assert selected.group(1) == "BG_SOFIA"
    assert selected.group(1) in _registry_regions()


@pytest.mark.parametrize("market_id,national_id", [("ZH_SHANGHAI", "ZH_CHINA"), ("TR_ISTANBUL", "TR_NATIONAL")])
def test_legacy_region_installs_and_searches_its_own_snapshot(market_id: str, national_id: str) -> None:
    """The v3 snapshot a preset region installs is that region's, and search reads it.

    The vector registry filed the Shanghai and Istanbul snapshots under the
    national ids and reached them through an alias, so the Turkish card read
    "National" while it restored the Istanbul catalogue. The market id must
    reach a row of its own, the national id must reach none, because no
    national base has a published snapshot, and the collection the install
    restores into must be the one search reads for the same region.
    """
    from app.modules.costs.cwicr_v3_catalogue import _HF_PUBLISHED, get_catalogue
    from app.modules.costs.qdrant_adapter import country_to_collection

    row = get_catalogue(market_id)
    assert row is not None, f"{market_id} reaches no v3 row, so its install answers 404"
    assert row.region == market_id, f"{market_id} reaches the v3 row filed as {row.region}"
    assert _HF_PUBLISHED[row.region][1] == market_id, f"{market_id}'s row restores another market's snapshot"
    assert country_to_collection(market_id) == row.collection
    assert get_catalogue(national_id) is None, f"{national_id} reaches a v3 snapshot built from another catalogue"


def test_no_v3_alias_joins_two_separate_bases() -> None:
    """An alias is a rename. Two ids the base registry loads separately are not one."""
    from app.modules.costs.cwicr_v3_catalogue import _REGION_ALIASES

    known = _registry_regions()
    joined = sorted((old, new) for old, new in _REGION_ALIASES.items() if old in known and new in known)
    assert not joined, f"{joined} alias one loadable base to another"
