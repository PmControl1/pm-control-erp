"""A country priced on the neutral stack still gets its own VAT line.

Egypt and Mexico have no regional markup stack, so their bills are
seeded with ``DEFAULT``, which carries no tax line. The tax seed knows each of
their rates and the bill resolved them, but there was no tax line to put the
rate on, so the bill showed no VAT at all. :func:`resolve_region_lines` now
appends one line named after the country's seeded tax when it is told the
country, and only then.

Croatia was the third example here until it got a stack of its own, a single
PDV line (a troškovnik prices on all-in rates); its seeded name is still
checked below because the stack's line and the seed must agree. Bulgaria
followed for the same reason (a КСС prices on all-in rates) and was replaced
here by Egypt. Its stack line is named ДДС, the way a Bulgarian bill prints
it, while the seed keeps DDS as the code; the last test pins that choice.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.modules.boq.markup_templates import (
    _TAX_SEED_PATH,
    DEFAULT_MARKUP_TEMPLATES,
    REGION_BY_COUNTRY,
    region_key_for_country,
    region_lines_for_country,
    resolve_region_lines,
    seeded_tax_line_names,
)


def _tax_lines(lines: list[dict[str, object]]) -> list[dict[str, object]]:
    return [line for line in lines if line.get("category") == "tax"]


@pytest.mark.parametrize(
    ("country", "rate", "name"),
    [("EG", "14", "VAT"), ("MX", "16", "IVA")],
)
def test_a_country_on_the_neutral_stack_gets_one_line_of_its_own_tax(country: str, rate: str, name: str) -> None:
    assert country not in REGION_BY_COUNTRY
    region = region_key_for_country(country)

    lines = resolve_region_lines(region, vat_rate=rate, country_code=country)

    taxes = _tax_lines(lines)
    assert len(taxes) == 1
    assert taxes[0]["name"] == name
    assert taxes[0]["percentage"] == rate
    assert taxes[0]["apply_to"] == "cumulative"
    assert taxes[0]["vat_override"] is True
    # The stack's own lines are untouched and the tax line comes last.
    assert [line["name"] for line in lines[:-1]] == [line["name"] for line in DEFAULT_MARKUP_TEMPLATES["DEFAULT"]]
    assert lines[-1] is taxes[0]
    assert int(str(taxes[0]["sort_order"])) > max(int(str(line["sort_order"])) for line in lines[:-1])


@pytest.mark.parametrize("country", ["US", "CA"])
def test_a_sales_tax_country_gets_no_line(country: str) -> None:
    """Sales tax is levied per state or province, so no one line describes it."""
    region = region_key_for_country(country)

    lines = resolve_region_lines(region, vat_rate="5", country_code=country)

    assert _tax_lines(lines) == _tax_lines(resolve_region_lines(region, vat_rate="5"))
    assert country not in seeded_tax_line_names()


def test_a_zero_rate_country_gets_no_line() -> None:
    lines = resolve_region_lines("DEFAULT", vat_rate="0", country_code="HK")

    assert _tax_lines(lines) == []
    assert "HK" not in seeded_tax_line_names()


def test_no_rate_and_no_country_add_nothing() -> None:
    assert _tax_lines(resolve_region_lines("DEFAULT", vat_rate=None, country_code="MX")) == []
    assert _tax_lines(resolve_region_lines("DEFAULT", vat_rate="0", country_code="MX")) == []
    assert _tax_lines(resolve_region_lines("DEFAULT", vat_rate="20")) == []


def test_a_stack_that_already_has_a_tax_line_is_not_given_a_second() -> None:
    """Idempotence: a stack with a tax line only has its rate swapped."""
    lines = resolve_region_lines("CZ", vat_rate="16", country_code="MX")

    taxes = _tax_lines(lines)
    assert len(taxes) == 1
    assert taxes[0]["name"] == "DPH"


def test_applying_twice_gives_the_same_single_line() -> None:
    first = resolve_region_lines("DEFAULT", vat_rate="16", country_code="MX")
    second = resolve_region_lines("DEFAULT", vat_rate="16", country_code="MX")

    assert first == second
    assert len(_tax_lines(second)) == 1


def test_the_methodology_side_never_sees_the_appended_line() -> None:
    """The catalogue derives templates only for mapped countries and passes no country."""
    assert region_lines_for_country("MX", vat_rate="16") is None
    for country, region in REGION_BY_COUNTRY.items():
        lines = region_lines_for_country(country, vat_rate="18")
        assert lines is not None
        assert len(_tax_lines(lines)) == len(_tax_lines(DEFAULT_MARKUP_TEMPLATES[region])), country


def test_the_name_map_is_what_the_seed_says() -> None:
    """The map is computed from the seed, so it must equal an independent reading of it."""
    rows = json.loads(_TAX_SEED_PATH.read_text(encoding="utf-8"))
    latest: dict[str, dict[str, object]] = {}
    for row in sorted(rows, key=lambda r: str(r.get("effective_from") or "")):
        if row.get("is_default"):
            latest[str(row["country_code"])] = row
    expected = {
        country: str(row["tax_code"])
        for country, row in latest.items()
        if row["combination"] == "national" and row["tax_type"] in ("vat", "gst") and Decimal(str(row["rate_pct"])) > 0
    }

    assert seeded_tax_line_names() == expected
    assert seeded_tax_line_names()["HR"] == "PDV"


def test_a_bulgarian_bill_prints_its_tax_the_way_the_market_names_it() -> None:
    """The BG stack is one ДДС line at 20 on the direct cost; the seed's code stays DDS.

    A КСС closes with "ДДС 20 %" in Cyrillic, which is what the bill shows. The
    seed's ``tax_code`` is an identifier, not a label, and the two are allowed
    to differ here on purpose; the rate is what has to agree.
    """
    assert REGION_BY_COUNTRY["BG"] == "BG"
    lines = resolve_region_lines(region_key_for_country("BG"), vat_rate="20", country_code="BG")

    assert [(line["category"], line["name"], line["percentage"]) for line in lines] == [("tax", "ДДС", "20")]
    assert lines[0]["apply_to"] == "direct_cost"
    assert seeded_tax_line_names()["BG"] == "DDS"
