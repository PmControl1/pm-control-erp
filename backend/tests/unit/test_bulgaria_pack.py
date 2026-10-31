# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Bulgaria pack does the four things it says, each through the code that does it.

* EUR, with lev amounts at the fixed 1.95583: the conversion rule of ЗВЕРБ
  чл. 12, the FX layer answering the lev from the law rather than from a feed
  that stopped quoting it, and a Bulgarian euro project starting with the lev
  in its rate table.
* ДДС at 20 %, through the BG markup stack and the core tax table.
* The ЕИК, checked by its check digit, accepted by the company profile only
  when it is valid, and printed on the letterhead under its name.
* The ЗУТ categories I to VI, offered for a Bulgarian project and refused when
  a value is not one of them.

Plus the vocabulary overlay: generated from the shipped locale by the pack's
own tool, current with it, and free of the names it exists to replace.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.euro_conversion import (
    fixed_euro_rate,
    fixed_rate_between,
    fixed_rate_entries_for_project,
    is_replaced_by_euro,
    to_euro,
)
from app.core.partner_pack.classifications import classification_errors, classifications_payload
from app.core.partner_pack.manifest import CompanyIdentifierSpec, PartnerPackManifest
from app.core.party_identifiers import check, schemes_for
from app.core.party_identifiers.bg import check_eik

REPO = Path(__file__).resolve().parents[3]
PACK = REPO / "packs" / "bulgaria-bg"
OVERLAY = PACK / "src" / "openconstructionerp_bulgaria_bg" / "locales" / "bg.json"


@pytest.fixture(scope="module")
def pack() -> PartnerPackManifest:
    from app.core.partner_pack.discovery import get_pack_by_slug

    manifest = get_pack_by_slug("bulgaria-bg")
    assert manifest is not None, "the bulgaria-bg pack is not discovered"
    return manifest


# -- the lev ----------------------------------------------------------------


def test_the_lev_is_fixed_at_the_councils_rate() -> None:
    assert fixed_euro_rate("BGN") == Decimal("1.95583")
    assert fixed_euro_rate("bgn ") == Decimal("1.95583")
    assert is_replaced_by_euro("BGN")


@pytest.mark.parametrize(
    ("lev", "euro"),
    [
        # The worked example Bulgarian guidance on ЗВЕРБ чл. 12 gives.
        ("799.99", Decimal("409.03")),
        ("1.95583", Decimal("1.00")),
        ("1000", Decimal("511.29")),
        ("0.01", Decimal("0.01")),
        # 2.93 / 1.95583 = 1.498085... -> 1.50 only if the third decimal decides, half up.
        ("2.93", Decimal("1.50")),
    ],
)
def test_a_lev_amount_is_divided_and_rounded_half_up_to_the_cent(lev: str, euro: Decimal) -> None:
    assert to_euro(lev, "BGN") == euro


def test_only_currencies_the_euro_replaced_at_a_constant_rate_are_fixed() -> None:
    # The kuna floated before 2023, and nothing that asks for a rate says when.
    assert fixed_euro_rate("HRK") is None
    assert fixed_rate_between("USD", "EUR") is None
    assert fixed_rate_between("BGN", "USD") is None
    with pytest.raises(ValueError):
        to_euro("10", "USD")


def test_the_fixed_pair_answers_both_ways() -> None:
    assert fixed_rate_between("EUR", "BGN") == Decimal("1.95583")
    lev_to_euro = fixed_rate_between("BGN", "EUR")
    assert lev_to_euro is not None
    assert (lev_to_euro * Decimal("1.95583")).quantize(Decimal("1E-20")) == Decimal("1").quantize(Decimal("1E-20"))
    assert fixed_rate_between("BGN", "BGN") == Decimal("1")


@pytest.mark.parametrize(
    "rates",
    [
        # An ECB set published after the changeover: no lev at all.
        {"USD": Decimal("1.08")},
        # The old seed's rounded peg must not win over the law.
        {"USD": Decimal("1.08"), "BGN": Decimal("1.9558")},
    ],
)
def test_the_fx_layer_prices_the_lev_from_the_law(rates: dict[str, Decimal]) -> None:
    from app.modules.fx.service import convert_via_base, cross_rate

    converted, _rate = convert_via_base("1000", "BGN", "EUR", rates)
    assert converted.quantize(Decimal("0.01")) == Decimal("511.29")
    assert cross_rate("EUR", "BGN", rates) == Decimal("1.95583")
    # Through a third currency the lev is the euro at the fixed rate.
    assert cross_rate("BGN", "USD", rates) == Decimal("1.08") / Decimal("1.95583")


def test_the_fx_layer_prices_the_lev_in_a_register_based_on_another_currency() -> None:
    from app.modules.fx.service import cross_rate

    usd_based = {"EUR": Decimal("0.9259")}
    assert cross_rate("BGN", "EUR", usd_based, base_currency="USD") == fixed_rate_between("BGN", "EUR")
    assert cross_rate("BGN", "USD", usd_based, base_currency="USD") == Decimal("1") / (
        Decimal("1.95583") * Decimal("0.9259")
    )


def test_the_bundled_seed_carries_the_exact_rate() -> None:
    seed = json.loads((REPO / "backend/app/modules/fx/fx_seed.json").read_text(encoding="utf-8"))
    assert Decimal(str(seed["rates"]["BGN"])) == Decimal("1.95583")


def test_a_bulgarian_euro_project_starts_with_the_lev_at_its_fixed_rate() -> None:
    rows = fixed_rate_entries_for_project("EUR", "BG")
    assert [row["code"] for row in rows] == ["BGN"]
    assert Decimal(rows[0]["rate"]) * Decimal("1.95583") == pytest.approx(Decimal("1"), abs=Decimal("1E-20"))
    # The rate table's own validator accepts the row as written.
    from app.modules.projects.schemas import _validate_fx_rates

    assert _validate_fx_rates(rows)[0]["code"] == "BGN"
    assert fixed_rate_entries_for_project("EUR", "HR") == []
    assert fixed_rate_entries_for_project("BGN", "BG") == []
    assert fixed_rate_entries_for_project("EUR", None) == []


def test_the_project_service_adds_the_lev_and_keeps_a_rate_the_caller_sent() -> None:
    from app.modules.projects.service import _with_fixed_euro_rates

    added = _with_fixed_euro_rates([], "EUR", "BG", None)
    assert [row["code"] for row in added] == ["BGN"]
    # The region alone settles the country, the way the BOQ router reads it.
    assert [row["code"] for row in _with_fixed_euro_rates(None, "EUR", "Bulgaria", None)] == ["BGN"]
    sent = [{"code": "BGN", "rate": "0.5113", "label": "typed"}]
    assert _with_fixed_euro_rates(sent, "EUR", "BG", "BG") == sent
    assert _with_fixed_euro_rates([], "EUR", "HR", "HR") == []


def test_the_pack_loads_the_lev_base_into_a_euro_workspace(pack: PartnerPackManifest) -> None:
    from app.core.partner_pack.full_install import describe_cost_bases

    (entry,) = describe_cost_bases(list(pack.cwicr_regions))
    assert entry["db_id"] == "BG_SOFIA"
    assert entry["currency"] == "BGN"
    assert pack.default_currency == "EUR"
    assert fixed_rate_between(entry["currency"], pack.default_currency) is not None


# -- ДДС ----------------------------------------------------------------------


def test_a_bulgarian_bill_adds_dds_at_20_and_nothing_else() -> None:
    from app.modules.boq.markup_templates import region_key_for_country, region_lines_for_country

    assert region_key_for_country("BG") == "BG"
    lines = region_lines_for_country("BG", vat_rate="20")
    assert lines is not None
    assert [(line["category"], line["name"], line["percentage"]) for line in lines] == [("tax", "ДДС", "20")]


def test_the_core_tax_table_states_bulgarian_vat() -> None:
    from app.core.tax import get_vat_rate

    assert get_vat_rate("BG") == Decimal("0.20")
    assert get_vat_rate("BG", "reduced") == Decimal("0.09")


def test_the_pack_prices_with_the_bulgarian_method(pack: PartnerPackManifest) -> None:
    from app.modules.methodology.templates import TEMPLATES_BY_SLUG

    assert pack.default_methodology == "bulgaria"
    assert pack.default_methodology in TEMPLATES_BY_SLUG


# -- ЕИК ------------------------------------------------------------------------


def test_the_eik_scheme_is_registered_for_bulgaria(pack: PartnerPackManifest) -> None:
    assert pack.company_identifier is not None
    assert pack.company_identifier.scheme in schemes_for("BG")
    assert pack.company_identifier.label == "ЕИК"
    placeholder = pack.company_identifier.placeholder
    assert placeholder and check_eik(placeholder).valid


@pytest.mark.parametrize(
    ("value", "normalised"),
    [
        ("123456786", "123456786"),
        ("123 456 786", "123456786"),
        ("BG123456786", "123456786"),
        # The first pass leaves 10, the second (weights 3 to 10) gives 6.
        ("100000086", "100000086"),
        # Both passes leave 10, so the check digit is 0.
        ("100000550", "100000550"),
    ],
)
def test_a_valid_eik_passes_in_the_forms_people_type_it(value: str, normalised: str) -> None:
    result = check("BG", "eik", value)
    assert result is not None and result.valid, result
    assert result.normalised == normalised
    assert "needs_expert_review" not in result.details


def test_the_second_pass_is_the_one_the_register_uses() -> None:
    digits = "10000008"
    first = sum(w * int(d) for w, d in zip(range(1, 9), digits, strict=True)) % 11
    second = sum(w * int(d) for w, d in zip(range(3, 11), digits, strict=True)) % 11
    assert (first, second) == (10, 6)


@pytest.mark.parametrize(
    ("value", "reason"),
    [("123456787", "checksum"), ("12345678", "shape"), ("1234567890", "shape"), ("12345678A", "shape")],
)
def test_a_wrong_eik_says_whether_it_is_mistyped_or_not_one(value: str, reason: str) -> None:
    result = check_eik(value)
    assert not result.valid
    assert result.reason == reason


def test_a_branch_eik_checks_its_own_digit_and_its_parents() -> None:
    branch = check_eik("1234567860014")
    assert not branch.valid and branch.reason == "checksum"
    from app.core.party_identifiers.bg import branch_check_digit

    valid = "123456786001" + str(branch_check_digit("6001"))
    result = check_eik(valid)
    assert result.valid
    assert result.details["needs_expert_review"] == "true"
    # A branch of a parent that fails its own check digit is not a branch of anything.
    assert check_eik("123456787001" + str(branch_check_digit("7001"))).reason == "checksum"


def test_the_letterhead_prints_the_eik_under_its_name() -> None:
    from app.core.company_profile import registration_text

    profile = {"company_id": "123456786", "company_id_label": "ЕИК", "registration_line": "ДДС № BG123456786"}
    # The firm's line already carries the digits: printed once.
    assert registration_text(profile) == "ДДС № BG123456786"
    profile["registration_line"] = "Вписано в ТРРЮЛНЦ"
    assert registration_text(profile) == "ЕИК 123456786 · Вписано в ТРРЮЛНЦ"
    assert registration_text({"company_id": "123456786", "company_id_label": "ЕИК"}) == "ЕИК 123456786"
    assert registration_text({"registration_line": "HRB 1"}) == "HRB 1"
    assert registration_text(None) == ""


@pytest.fixture
def admin_with_the_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pack: PartnerPackManifest
) -> Iterator[TestClient]:
    from app.core import company_profile_router
    from app.core.partner_pack import discovery
    from app.dependencies import get_current_user_payload

    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(discovery, "get_active_pack", lambda: pack)
    app = FastAPI()
    app.include_router(company_profile_router.router, prefix="/api/v1")

    async def _payload() -> dict[str, str]:
        return {"sub": "admin-under-test", "role": "admin"}

    app.dependency_overrides[get_current_user_payload] = _payload
    with TestClient(app) as client:
        yield client


def test_the_company_profile_asks_for_the_eik_while_the_pack_is_active(admin_with_the_pack: TestClient) -> None:
    options = admin_with_the_pack.get("/api/v1/company-profile/options/").json()
    assert options["company_identifier"]["scheme"] == "eik"
    assert options["company_identifier"]["label"] == "ЕИК"
    assert options["company_identifier"]["country"] == "BG"


def test_a_valid_eik_is_stored_normalised_under_its_name(admin_with_the_pack: TestClient) -> None:
    response = admin_with_the_pack.put(
        "/api/v1/company-profile/", json={"legal_name": "Строй ЕООД", "company_id": "BG 123 456 786"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["company_id"], body["company_id_label"]) == ("123456786", "ЕИК")
    assert admin_with_the_pack.get("/api/v1/company-profile/").json()["company_id"] == "123456786"


def test_a_mistyped_eik_is_refused_and_the_stored_one_kept(admin_with_the_pack: TestClient) -> None:
    assert admin_with_the_pack.put("/api/v1/company-profile/", json={"company_id": "123456786"}).status_code == 200
    response = admin_with_the_pack.put("/api/v1/company-profile/", json={"company_id": "123456787"})
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "invalid_company_id"
    assert response.json()["detail"]["reason"] == "checksum"
    assert admin_with_the_pack.get("/api/v1/company-profile/").json()["company_id"] == "123456786"


def test_clearing_the_eik_clears_its_name_too(admin_with_the_pack: TestClient) -> None:
    admin_with_the_pack.put("/api/v1/company-profile/", json={"legal_name": "Строй ЕООД", "company_id": "123456786"})
    body = admin_with_the_pack.put("/api/v1/company-profile/", json={"company_id": ""}).json()
    assert (body["company_id"], body["company_id_label"]) == ("", "")


def test_without_a_pack_that_names_a_number_there_is_nothing_to_file_it_under(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import company_profile_router
    from app.core.partner_pack import discovery
    from app.dependencies import get_current_user_payload

    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(discovery, "get_active_pack", lambda: None)
    app = FastAPI()
    app.include_router(company_profile_router.router, prefix="/api/v1")

    async def _payload() -> dict[str, str]:
        return {"sub": "admin-under-test", "role": "admin"}

    app.dependency_overrides[get_current_user_payload] = _payload
    with TestClient(app) as client:
        assert client.get("/api/v1/company-profile/options/").json()["company_identifier"] is None
        response = client.put("/api/v1/company-profile/", json={"company_id": "123456786"})
        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "no_company_identifier"


def test_only_a_market_pack_can_name_a_company_number() -> None:
    with pytest.raises(ValueError, match="one market"):
        PartnerPackManifest(
            slug="sector-pack",
            partner_name="Sector Pack",
            metadata={"country": "XX", "industry": "formwork"},
            company_identifier=CompanyIdentifierSpec(scheme="eik", label="ЕИК"),
        )


# -- ЗУТ ------------------------------------------------------------------------


def test_the_zut_categories_are_the_six_of_article_137(pack: PartnerPackManifest) -> None:
    (zut,) = pack.project_classifications
    assert zut.key == "bg_zut_category"
    assert [option.value for option in zut.options] == ["I", "II", "III", "IV", "V", "VI"]
    assert "137" in (zut.statute or "")
    assert all(option.hint and option.hint_en for option in zut.options)


def test_a_category_outside_the_list_is_refused(pack: PartnerPackManifest) -> None:
    assert classification_errors(pack, {"bg_zut_category": "III"}) == []
    assert classification_errors(pack, {"bg_zut_category": ""}) == []
    assert classification_errors(pack, {"bg_zut_category": None}) == []
    assert classification_errors(pack, {"anything_else": "VII"}) == []
    (error,) = classification_errors(pack, {"bg_zut_category": "VII"})
    assert error["key"] == "bg_zut_category"
    assert classification_errors(pack, {"bg_zut_category": 3})


def test_the_project_service_checks_against_the_pack_of_the_projects_country(pack: PartnerPackManifest) -> None:
    from app.modules.projects.service import _classification_errors_for

    assert _classification_errors_for(None, {"bg_zut_category": "VII"}) == []
    assert _classification_errors_for(pack, {"bg_zut_category": "VII"})


def test_a_bulgarian_project_is_offered_the_categories(
    pack: PartnerPackManifest, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.projects.country_configuration import configuration_pack

    chosen, source = configuration_pack(region="Bulgaria", country_code=None, active_pack=pack, shipped=lambda: [pack])
    payload = classifications_payload(chosen, country="BG", source=source)
    assert payload["pack_slug"] == "bulgaria-bg"
    assert payload["locale"] == "bg"
    assert [c["key"] for c in payload["classifications"]] == ["bg_zut_category"]
    assert classifications_payload(None, country="HU", source="country_without_pack")["classifications"] == []


def test_the_region_bulgaria_names_the_country() -> None:
    from app.core.classification_registry import normalise_region

    assert normalise_region("Bulgaria") == "BG"


# -- vocabulary -----------------------------------------------------------------


def test_the_vocabulary_overlay_is_current_with_the_shipped_locale() -> None:
    result = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, str(PACK / "tools" / "build_vocabulary.py"), "--check"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def test_the_overlay_names_the_bill_one_way(pack: PartnerPackManifest) -> None:
    assert pack.additional_locales == {"bg": "locales/bg.json"}
    entries = json.loads(OVERLAY.read_text(encoding="utf-8"))["translation"]
    loan_word = re.compile(r"(?<![\w/{.\-])(?:BOQs|BOQ|BoQ)(?![\w/}])")
    rival = re.compile(r"(?<![а-яА-Я-])[Кк]оличествен(?:а|ата|и|ите) сметк")
    exchange = re.compile(r"^nav\.[a-z]+_boq_exchange$")
    leftovers = [k for k, v in entries.items() if not exchange.match(k) and (loan_word.search(v) or rival.search(v))]
    assert leftovers == []
    assert entries["nav.boq"] == "КСС"
    assert entries["nav.tendering"] == "Търгове"
    assert len(entries) > 500
