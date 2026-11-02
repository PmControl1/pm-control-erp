# PM Project Management - tests for the Bulgarian КСС rule set.
# Licensed under the GNU AGPL v3.0 or later, like the rest of this program.
"""A Bulgarian bill is checked the way a tender reads it, and nothing else.

Two questions: does the priced КСС keep the количествена сметка it was issued
with (descriptions, units, quantities, no added lines), and does it close with
one ДДС line at 20 % on the whole "Общо без ДДС". A Bulgarian project reaches
these through the country row and the pack, and no longer gets DIN 276, which
failed every line of an ordinary КСС.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.core.validation.messages import translate
from app.core.validation.rules.bulgaria_kss import (
    BULGARIA_RULE_SET,
    BULGARIA_RULES,
    BulgarianKssMatchesTenderBill,
    BulgarianVatChargedOnce,
    BulgarianVatLinePresent,
    BulgarianVatOnWholeTotal,
    BulgarianVatRate,
    is_vat_line,
    match_lines,
)
from app.modules.boq.kss_tender import load_kss_tender, with_kss_tender_bill
from app.modules.boq.router import _build_rule_sets

# ── Fixtures ───────────────────────────────────────────────────────────────────

TENDER = [
    # (id, parent, ordinal, description, unit, quantity)
    ("s1", None, "I.", "ЗЕМНИ РАБОТИ", "", 0),
    ("t1", "s1", "1", "Изкоп с багер на транспорт", "м3", 1250),
    ("t2", "s1", "2", "Ръчен изкоп за фундаменти", "куб.м", 85),
    ("s2", None, "II.", "БЕТОНОВИ РАБОТИ", "", 0),
    ("t3", "s2", "3", "Кофраж за стени", "кв. м.", 1340.5),
    ("t4", "s2", "4", "Армировка B500B", "кг", 52000),
]


def _positions(rows: list[tuple], *, prefix: str = "", rate: float = 0.0) -> list[dict[str, Any]]:
    out = []
    for pid, parent, ordinal, description, unit, quantity in rows:
        section = not unit and not quantity
        out.append(
            {
                "id": prefix + pid,
                "parent_id": prefix + parent if parent else None,
                "ordinal": ordinal,
                "description": description,
                "unit": unit,
                "quantity": quantity,
                "unit_rate": 0.0 if section else rate,
                "total": 0.0 if section else quantity * rate,
                "type": "section" if section else "position",
                "metadata": {},
            }
        )
    return out


def _tender(rows: list[tuple] = TENDER) -> dict[str, Any]:
    return {"boq_id": "tender-bill", "name": "КС Жилищна сграда", "positions": _positions(rows)}


def _run(rule: Any, data: dict[str, Any], locale: str = "en") -> list[Any]:
    return asyncio.run(rule.validate(ValidationContext(data=data, metadata={"locale": locale})))


def _failures(results: list[Any]) -> list[Any]:
    return [r for r in results if not r.passed]


def _priced(markups: list[dict[str, Any]]) -> dict[str, Any]:
    return {"positions": _positions(TENDER, rate=10.0), "markups": markups}


def _markup(name: str, category: str = "tax", percentage: str = "20.0", **extra: Any) -> dict[str, Any]:
    return {
        "id": name,
        "name": name,
        "category": category,
        "markup_type": "percentage",
        "percentage": percentage,
        "fixed_amount": "0",
        "apply_to": "direct_cost",
        "sort_order": 0,
        "is_active": True,
        "scope_position_id": None,
        **extra,
    }


# ── Registration and reach ─────────────────────────────────────────────────────


def test_the_bulgaria_set_holds_its_five_rules() -> None:
    ids = {entry["rule_id"] for entry in rule_registry.list_rules(rule_set=BULGARIA_RULE_SET)}
    assert ids == {rule.rule_id for rule in BULGARIA_RULES}
    assert len(ids) == 5


def test_a_bulgarian_project_gets_the_bulgarian_rules_and_not_din276() -> None:
    sets = _build_rule_sets(["boq_quality"], "", "", "BG")
    assert "bulgaria" in sets
    assert "din276" not in sets


def test_a_bulgarian_project_that_chose_din276_still_gets_it() -> None:
    sets = _build_rule_sets(["boq_quality"], "din276", "", "BG")
    assert {"bulgaria", "din276"} <= set(sets)


def test_the_bulgaria_pack_switches_the_set_on() -> None:
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[3] / "packs/bulgaria-bg/src/openconstructionerp_bulgaria_bg/manifest.py"
    ).read_text(encoding="utf-8")
    block = text.split("validation_rule_sets=[", 1)[1].split("]", 1)[0]
    assert '"bulgaria"' in block
    assert "din276" not in block


@pytest.mark.parametrize("locale", ["en", "bg", "de", "ru"])
def test_every_message_renders_in_the_languages_people_use_here(locale: str) -> None:
    params = {
        "count": 2,
        "names": '"ДДС", "VAT"',
        "name": "ДДС",
        "rate": "9",
        "ordinal": "3",
        "bill": "КС",
        "description": "Кофраж",
        "tender_description": "Кофраж за стени",
        "unit": "м",
        "tender_unit": "м2",
        "quantity": "1340",
        "tender_quantity": "1340.5",
    }
    keys = [
        "bulgaria.vat_line_present.fail",
        "bulgaria.vat_charged_once.fail",
        "bulgaria.vat_rate.fail",
        "bulgaria.vat_rate.not_percentage",
        "bulgaria.vat_on_whole_total.base",
        "bulgaria.vat_on_whole_total.after",
        "bulgaria.kss_matches_tender_bill.missing",
        "bulgaria.kss_matches_tender_bill.extra",
        "bulgaria.kss_matches_tender_bill.description",
        "bulgaria.kss_matches_tender_bill.unit",
        "bulgaria.kss_matches_tender_bill.quantity",
        "bulgaria.kss_matches_tender_bill.unmatched",
    ]
    for key in keys:
        text = translate(key, locale=locale, **params)
        assert text and key not in text and "{" not in text, (locale, key, text)


# ── ДДС ─────────────────────────────────────────────────────────────────────


def test_the_bulgarian_stack_passes_every_vat_rule() -> None:
    data = _priced([_markup("ДДС")])
    for rule in (BulgarianVatLinePresent(), BulgarianVatChargedOnce(), BulgarianVatRate(), BulgarianVatOnWholeTotal()):
        assert _failures(_run(rule, data)) == [], rule.rule_id


def test_a_bill_without_vat_is_a_warning_only() -> None:
    (result,) = _run(BulgarianVatLinePresent(), _priced([]))
    assert not result.passed
    assert result.severity == Severity.WARNING


def test_an_unpriced_bill_is_not_asked_for_vat() -> None:
    assert _run(BulgarianVatLinePresent(), {"positions": _positions(TENDER), "markups": []}) == []


def test_an_inactive_vat_line_does_not_count() -> None:
    (result,) = _run(BulgarianVatLinePresent(), _priced([_markup("ДДС", is_active=False)]))
    assert not result.passed


def test_a_line_named_dds_is_vat_whatever_its_category() -> None:
    assert is_vat_line({"name": "ДДС 20%", "category": "overhead"})
    assert is_vat_line({"name": "VAT", "category": "other"})
    assert not is_vat_line({"name": "Непредвидени разходи", "category": "contingency"})


def test_two_vat_lines_charge_the_tax_twice() -> None:
    data = _priced([_markup("ДДС", sort_order=1), _markup("ДДС 20%", category="overhead", sort_order=2)])
    (result,) = _run(BulgarianVatChargedOnce(), data)
    assert not result.passed
    assert result.severity == Severity.ERROR
    assert result.details["vat_lines"] == ["ДДС", "ДДС 20%"]


@pytest.mark.parametrize("rate", ["9", "0", "21", "18.0"])
def test_vat_at_another_rate_is_an_error(rate: str) -> None:
    (result,) = _run(BulgarianVatRate(), _priced([_markup("ДДС", percentage=rate)]))
    assert not result.passed
    assert result.severity == Severity.ERROR


def test_vat_as_a_fixed_amount_is_an_error() -> None:
    (result,) = _run(BulgarianVatRate(), _priced([_markup("ДДС", markup_type="fixed", fixed_amount="1000")]))
    assert not result.passed
    assert "fixed amount" in result.message


def test_a_section_level_vat_line_is_held_to_the_rate_too() -> None:
    data = _priced([_markup("ДДС"), _markup("ДДС раздел II", percentage="0", scope_position_id="s2")])
    results = _run(BulgarianVatRate(), data)
    assert [r.passed for r in results] == [True, False]


def test_vat_on_the_direct_cost_leaves_out_a_contingency_line() -> None:
    data = _priced(
        [
            _markup("Непредвидени разходи", category="contingency", percentage="10", sort_order=1),
            _markup("ДДС", sort_order=2),
        ]
    )
    (result,) = _run(BulgarianVatOnWholeTotal(), data)
    assert not result.passed
    assert result.details["lines"] == ["Непредвидени разходи"]


def test_cumulative_vat_after_a_contingency_line_passes() -> None:
    data = _priced(
        [
            _markup("Непредвидени разходи", category="contingency", percentage="10", sort_order=1),
            _markup("ДДС", sort_order=2, apply_to="cumulative"),
        ]
    )
    assert _failures(_run(BulgarianVatOnWholeTotal(), data)) == []


def test_a_line_after_vat_falls_outside_the_total_with_vat() -> None:
    data = _priced(
        [
            _markup("ДДС", sort_order=1, apply_to="cumulative"),
            _markup("Печалба", category="profit", percentage="5", sort_order=2),
        ]
    )
    (result,) = _run(BulgarianVatOnWholeTotal(), data)
    assert not result.passed
    assert "Печалба" in result.message


def test_the_sofia_demo_stack_passes() -> None:
    data = _priced(
        [
            _markup("Непредвидени разходи (Contingency)", category="contingency", percentage="3.0", sort_order=0),
            _markup("ДДС 20%", sort_order=1, apply_to="cumulative"),
        ]
    )
    for rule in (BulgarianVatChargedOnce(), BulgarianVatRate(), BulgarianVatOnWholeTotal()):
        assert _failures(_run(rule, data)) == [], rule.rule_id


# ── КСС against its количествена сметка ──────────────────────────────────────


def _kss(rows: list[tuple] = TENDER) -> list[dict[str, Any]]:
    return _positions(rows, prefix="k", rate=12.5)


def _check(kss: list[dict[str, Any]], tender: dict[str, Any] | None = None, locale: str = "en") -> list[Any]:
    data: dict[str, Any] = {"positions": kss}
    if tender is not False:
        data["kss_tender"] = tender if tender is not None else _tender()
    return _run(BulgarianKssMatchesTenderBill(), data, locale)


def test_a_bill_that_names_no_tender_bill_is_not_checked() -> None:
    assert _run(BulgarianKssMatchesTenderBill(), {"positions": _kss()}) == []


def test_the_kss_priced_as_issued_passes_line_by_line() -> None:
    results = _check(_kss())
    assert len(results) == 4
    assert all(r.passed for r in results)


def test_spelling_of_units_case_and_spacing_are_not_changes() -> None:
    rows = [
        ("s1", None, "I.", "ЗЕМНИ РАБОТИ", "", 0),
        ("t1", "s1", "1", "ИЗКОП  с багер на транспорт.", "m3", 1250.0),
        ("t2", "s1", "2", "Ръчен изкоп за фундаменти", "м3", 85.0004),
        ("s2", None, "II.", "БЕТОНОВИ РАБОТИ", "", 0),
        ("t3", "s2", "3", "Кофраж за стени", "м²", 1340.50),
        ("t4", "s2", "4", "Армировка B500B", "kg", 52000),
    ]
    assert _failures(_check(_kss(rows))) == []


def test_a_changed_description_unit_or_quantity_is_an_error_naming_the_line() -> None:
    rows = list(TENDER)
    rows[1] = ("t1", "s1", "1", "Изкоп с багер", "м3", 1250)
    rows[2] = ("t2", "s1", "2", "Ръчен изкоп за фундаменти", "м2", 85)
    rows[4] = ("t3", "s2", "3", "Кофраж за стени", "кв. м.", 1300)
    failures = _failures(_check(_kss(rows)))
    assert [(f.details["difference"], f.details["ordinal"]) for f in failures] == [
        ("description", "1"),
        ("unit", "2"),
        ("quantity", "3"),
    ]
    assert all(f.severity == Severity.ERROR for f in failures)
    assert failures[0].element_ref == "kt1"
    assert "1300" in failures[2].message and "1340.5" in failures[2].message


def test_a_dropped_line_and_an_added_line_are_both_errors() -> None:
    rows = [row for row in TENDER if row[0] != "t2"] + [("t9", "s2", "9", "Бетон C25/30", "м3", 120)]
    failures = _failures(_check(_kss(rows)))
    assert sorted(f.details["difference"] for f in failures) == ["extra", "missing"]


def test_the_contingency_allowance_is_not_a_line_of_work() -> None:
    kss = _kss()
    kss.append(
        {
            "id": "kc",
            "parent_id": None,
            "ordinal": "",
            "description": "Непредвидени разходи 10%",
            "unit": "сума",
            "quantity": 1,
            "unit_rate": 5000,
            "total": 5000,
            "type": "position",
            "metadata": {"contingency": True},
        }
    )
    assert _failures(_check(kss)) == []


def test_numbering_that_restarts_in_every_section_is_matched_under_its_section() -> None:
    rows = [
        ("s1", None, "I", "ЗЕМНИ РАБОТИ", "", 0),
        ("t1", "s1", "1", "Изкоп с багер на транспорт", "м3", 1250),
        ("t2", "s1", "2", "Ръчен изкоп за фундаменти", "м3", 85),
        ("s2", None, "II", "БЕТОНОВИ РАБОТИ", "", 0),
        ("t3", "s2", "1", "Кофраж за стени", "м2", 1340.5),
        ("t4", "s2", "2", "Армировка B500B", "кг", 52000),
    ]
    pairs, extra = match_lines(_positions(rows), _kss(rows))
    assert extra == []
    assert [(t["description"], k["description"]) for t, k in pairs] == [(r[3], r[3]) for r in rows if r[4]]
    assert _failures(_check(_kss(rows), _tender(rows))) == []


def test_lines_that_cannot_be_told_apart_are_one_warning() -> None:
    rows = [("t1", None, "1", "Изкоп", "м3", 10), ("t2", None, "1", "Насип", "м3", 5)]
    (result,) = _check(_kss(rows), _tender(rows))
    assert not result.passed
    assert result.severity == Severity.WARNING


def test_a_link_to_a_bill_that_is_gone_is_a_warning() -> None:
    (result,) = _check(_kss(), {"boq_id": "gone", "missing": True})
    assert not result.passed
    assert result.severity == Severity.WARNING


def test_the_bulgarian_message_names_the_tender_bill() -> None:
    rows = [row for row in TENDER if row[0] != "t4"]
    (failure,) = _failures(_check(_kss(rows), locale="bg"))
    assert "количествената сметка „КС Жилищна сграда“" in failure.message


# ── Loading the tender bill ──────────────────────────────────────────────────


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Rows:
        return self

    def all(self) -> list[Any]:
        return self._rows


class _Session:
    def __init__(self, bills: dict[uuid.UUID, Any], positions: list[Any]) -> None:
        self.bills = bills
        self.positions = positions

    async def get(self, _model: Any, key: uuid.UUID) -> Any:
        return self.bills.get(key)

    async def execute(self, _statement: Any) -> _Rows:
        return _Rows(self.positions)


def _bill(project: uuid.UUID, name: str, metadata: dict[str, Any] | None = None) -> Any:
    return SimpleNamespace(id=uuid.uuid4(), project_id=project, name=name, metadata_=metadata or {})


def _row(ordinal: str, description: str, unit: str, quantity: float, parent: Any = None) -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        parent_id=parent,
        ordinal=ordinal,
        description=description,
        unit=unit,
        quantity=quantity,
        unit_rate=0,
        metadata_={},
    )


def test_the_tender_bill_is_loaded_with_its_lines() -> None:
    project = uuid.uuid4()
    tender = _bill(project, "КС")
    section = _row("I.", "ЗЕМНИ РАБОТИ", "", 0)
    line = _row("1", "Изкоп", "м3", 1250, parent=section.id)
    kss = _bill(project, "КСС", {"kss_tender_bill_id": str(tender.id)})
    session = _Session({tender.id: tender, kss.id: kss}, [section, line])
    loaded = asyncio.run(load_kss_tender(session, kss.id))
    assert loaded["name"] == "КС"
    assert [(p["ordinal"], p["type"]) for p in loaded["positions"]] == [("I.", "section"), ("1", "position")]
    payload = asyncio.run(with_kss_tender_bill(session, kss.id, {"positions": []}))
    assert payload["kss_tender"]["boq_id"] == str(tender.id)


def test_no_link_adds_nothing() -> None:
    project = uuid.uuid4()
    kss = _bill(project, "КСС")
    session = _Session({kss.id: kss}, [])
    assert asyncio.run(with_kss_tender_bill(session, kss.id, {"positions": []})) == {"positions": []}


@pytest.mark.parametrize("case", ["other_project", "self", "deleted", "not_an_id"])
def test_a_link_that_does_not_hold_is_reported_missing(case: str) -> None:
    project = uuid.uuid4()
    foreign = _bill(uuid.uuid4(), "чужда")
    kss = _bill(project, "КСС")
    target = {"other_project": str(foreign.id), "self": str(kss.id), "deleted": str(uuid.uuid4()), "not_an_id": "x"}
    kss.metadata_ = {"kss_tender_bill_id": target[case]}
    session = _Session({kss.id: kss, foreign.id: foreign}, [])
    loaded = asyncio.run(load_kss_tender(session, kss.id))
    assert loaded == {"boq_id": target[case], "missing": True}
