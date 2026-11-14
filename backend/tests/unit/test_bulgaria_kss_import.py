"""A Bulgarian КСС imports as the bill it is.

The workbook below has the shape the firm's КСС files take: a title block, the
heading row in the trade's own words, the row of column numbers under it,
Roman-numbered sections each closed by "Общо за раздел", then "ОБЩО",
"Непредвидени разходи 10%", "ДДС 20%" and "ВСИЧКО С ДДС". Totals are values,
as Excel saves them.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from app.modules.boq.importers import ImportedBOQ, ImportedPosition
from app.modules.boq.importers._base import ImporterParseError
from app.modules.boq.importers.bulgaria_kss import canonical_unit, convert_to_euro, money_currency
from app.modules.boq.importers.excel import ExcelImporter

LINES = [
    # (ordinal, шифър, description, unit, quantity, rate)
    (1, "02.01.01", "Изкоп с багер на транспорт", "м3", 1250, 12.5),
    (2, "02.01.12", "Ръчен изкоп за фундаменти", "куб.м", 85, 35),
    (3, None, "Кофраж за стени", "кв. м.", 1340.5, 28.6),
    (4, None, "Армировка B500B", "кг", 52000, 2.15),
    (5, None, "Перваз", "л.м.", 640, 4.2),
    (6, None, "Монтаж на PVC дограма", "бр", 46, 385),
]


def _kss(rate_heading: str = "Ед. цена (лв. без ДДС)", total_heading: str = "Стойност (лв. без ДДС)") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "КСС"
    ws.append([None, None, "КОЛИЧЕСТВЕНО-СТОЙНОСТНА СМЕТКА"])
    ws.append(["Обект: Жилищна сграда, гр. София"])
    ws.append([])
    ws.append(
        ["№ по ред", "Шифър", "Наименование на видовете СМР", "Ед. мярка", "Количество", rate_heading, total_heading]
    )
    ws.append([1, 2, 3, 4, 5, 6, 7])

    def line(n: int) -> list:
        o, code, text, unit, qty, rate = LINES[n]
        return [o, code, text, unit, qty, rate, round(qty * rate, 2)]

    first = [line(0), line(1)]
    second = [line(2), line(3)]
    third = [line(4), line(5)]
    total = 0.0
    for numeral, title, rows in (
        ("I.", "ЗЕМНИ РАБОТИ", first),
        ("II.", "БЕТОНОВИ РАБОТИ", second),
        ("III.", "ДОВЪРШИТЕЛНИ РАБОТИ", third),
    ):
        ws.append([None, None, f"{numeral} {title}"])
        for row in rows:
            ws.append(row)
        subtotal = round(sum(r[6] for r in rows), 2)
        total += subtotal
        ws.append([None, None, f"Общо за раздел {numeral}", None, None, None, subtotal])
    total = round(total, 2)
    contingency = round(total * 0.1, 2)
    vat = round((total + contingency) * 0.2, 2)
    ws.append([None, None, "ОБЩО:", None, None, None, total])
    ws.append([None, None, "Непредвидени разходи 10%", None, None, None, contingency])
    ws.append([None, None, "ДДС 20%", None, None, None, vat])
    ws.append([None, None, "ВСИЧКО С ДДС:", None, None, None, round(total + contingency + vat, 2)])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _parse(content: bytes) -> ImportedBOQ:
    return asyncio.run(ExcelImporter.parse(content, locale="bg"))


def _work(result: ImportedBOQ) -> list[ImportedPosition]:
    return [p for p in result.positions if not p.is_section and not (p.metadata or {}).get("contingency")]


# -- reading the bill ----------------------------------------------------------


def test_every_line_of_work_comes_in_with_its_numbers() -> None:
    result = _parse(_kss())
    work = _work(result)
    assert [p.description for p in work] == [line[2] for line in LINES]
    assert [p.quantity for p in work] == [float(line[4]) for line in LINES]
    assert [p.unit_rate for p in work] == [float(line[5]) for line in LINES]
    assert [p.ordinal for p in work] == [str(line[0]) for line in LINES]
    assert result.errors == []


def test_the_row_of_column_numbers_is_not_a_line() -> None:
    result = _parse(_kss())
    assert not any(p.description.strip() == "3" for p in result.positions)


def test_sections_are_sections_and_totals_and_tax_are_not_imported() -> None:
    result = _parse(_kss())
    sections = [p.description for p in result.positions if p.is_section]
    assert sections == ["I. ЗЕМНИ РАБОТИ", "II. БЕТОНОВИ РАБОТИ", "III. ДОВЪРШИТЕЛНИ РАБОТИ"]
    texts = " | ".join(p.description for p in result.positions).casefold()
    for not_work in ("общо за раздел", "общо:", "ддс 20%", "всичко с ддс"):
        assert not_work not in texts


def test_the_contingency_comes_in_as_a_lump_sum_with_its_amount() -> None:
    result = _parse(_kss())
    (reserve,) = [p for p in result.positions if (p.metadata or {}).get("contingency")]
    work_total = sum(p.quantity * p.unit_rate for p in _work(result))
    assert reserve.quantity == 1.0
    assert reserve.unit_rate == pytest.approx(round(work_total * 0.1, 2))


def test_sections_are_numbered_by_the_numeral_in_their_heading() -> None:
    # The № column is blank on a КСС section heading; the heading used to take
    # the next free line number, so I, II and III showed as 7, 10 and 13.
    result = _parse(_kss())
    assert [p.ordinal for p in result.positions if p.is_section] == ["I", "II", "III"]
    assert [p.ordinal for p in _work(result)] == ["1", "2", "3", "4", "5", "6"]


def test_restarted_line_numbers_are_qualified_by_their_section_numeral() -> None:
    from app.modules.boq.importers.bulgaria_kss import normalise_section_ordinals

    wb = Workbook()
    ws = wb.active
    ws.append(["№ по ред", "Наименование на видовете СМР", "Ед. мярка", "Количество", "Ед. цена (лв.)"])
    ws.append([None, "I. ЗЕМНИ РАБОТИ"])
    ws.append([1, "Изкоп", "м3", 10, 5])
    ws.append([None, "II. БЕТОНОВИ РАБОТИ"])
    ws.append([1, "Бетон", "м3", 4, 150])
    buffer = io.BytesIO()
    wb.save(buffer)
    result = _parse(buffer.getvalue())
    normalise_section_ordinals(result)
    assert [p.ordinal for p in result.positions] == ["I", "I.1", "II", "II.1"]


@pytest.mark.parametrize(
    ("heading", "numeral"),
    [
        ("I. ЗЕМНИ РАБОТИ", "I"),
        ("Раздел IV - Ел. инсталации", "IV"),
        ("раздел III: ВиК", "III"),
        ("ІІ. Бетонови работи", "II"),  # Cyrillic І
        ("XIV) Покриви", "XIV"),
        ("Хидроизолация", ""),  # Cyrillic Х opening a word
        ("Част Архитектура", ""),
        ("X-ray", ""),
        ("IIII. Не е число", ""),
    ],
)
def test_section_numeral(heading: str, numeral: str) -> None:
    from app.modules.boq.importers.bulgaria_kss import section_numeral

    assert section_numeral(heading) == numeral


def test_the_contingency_is_a_lump_sum_in_the_bill_s_own_unit() -> None:
    from app.modules.boq.units import is_lump_sum_unit

    (reserve,) = [p for p in _parse(_kss()).positions if (p.metadata or {}).get("contingency")]
    assert reserve.unit == "сума"
    assert is_lump_sum_unit("сума")


def test_units_are_folded_to_the_form_a_kss_prints() -> None:
    result = _parse(_kss())
    assert [p.unit for p in _work(result)] == ["м3", "м3", "м2", "кг", "м", "бр."]


def test_the_shifur_stays_a_price_norm_code() -> None:
    result = _parse(_kss())
    first, second, third = _work(result)[:3]
    assert first.classification == {"code": "02.01.01"}
    assert second.classification == {"code": "02.01.12"}
    assert third.classification == {}


# -- currency ----------------------------------------------------------------


def test_lev_headings_make_a_lev_bill() -> None:
    assert _parse(_kss()).currency == "BGN"


def test_euro_headings_make_a_euro_bill() -> None:
    assert _parse(_kss("Ед. цена, €", "Обща стойност, €")).currency == "EUR"
    assert _parse(_kss("Единична цена (евро)", "Стойност (евро)")).currency == "EUR"


def test_headings_without_a_currency_are_flagged() -> None:
    result = _parse(_kss("Ед. цена", "Стойност"))
    assert result.currency == ""
    assert "currency_not_stated" in [w.get("code") for w in result.warnings]


def _currency_sheets(currencies: tuple[str, ...], *, identical_rows: bool = False) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for number, currency in enumerate(currencies, start=1):
        ws = wb.create_sheet(f"Раздел {number}")
        ws.append(["№ по ред", "Наименование на видовете СМР", "Ед. мярка", "Количество", f"Ед. цена {currency}"])
        line_number = 1 if identical_rows else number
        ws.append([line_number, f"Работа {line_number}", "м2", 1, 100])
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


@pytest.mark.parametrize("currencies", [("(лв.)", "(€)"), ("(€)", "(лв.)"), ("", "(лв.)"), ("(лв.)", "")])
def test_mixed_or_partly_unspecified_sheet_currencies_are_refused(currencies: tuple[str, ...]) -> None:
    # Otherwise the first sheet decides whether EVERY sheet is divided by
    # 1.95583, silently repricing a sheet already in euro (or missing BGN).
    with pytest.raises(ImporterParseError) as error:
        _parse(_currency_sheets(currencies))
    assert error.value.code == "spreadsheet_currency_ambiguous"


@pytest.mark.parametrize("currencies", [("(лв.)", "(€)"), ("(€)", "(лв.)"), ("", "(лв.)"), ("(лв.)", "")])
def test_duplicate_rows_do_not_hide_conflicting_sheet_currencies(currencies: tuple[str, ...]) -> None:
    with pytest.raises(ImporterParseError) as error:
        _parse(_currency_sheets(currencies, identical_rows=True))
    assert error.value.code == "spreadsheet_currency_ambiguous"


@pytest.mark.parametrize("currency,expected", [("(лв.)", "BGN"), ("(€)", "EUR"), ("", "")])
def test_same_currency_duplicate_sheets_are_still_deduplicated(currency: str, expected: str) -> None:
    result = _parse(_currency_sheets((currency, currency), identical_rows=True))
    assert result.currency == expected
    assert len([p for p in result.positions if not p.is_section]) == 1
    assert any(note.get("reason") == "duplicate" for note in result.warnings)


@pytest.mark.parametrize("currency,expected", [("(лв.)", "BGN"), ("(€)", "EUR"), ("", "")])
def test_same_currency_across_item_sheets_still_imports(currency: str, expected: str) -> None:
    result = _parse(_currency_sheets((currency, currency)))
    assert result.currency == expected
    assert [p.unit_rate for p in result.positions if not p.is_section] == [100, 100]


def test_a_cover_sheet_without_price_headings_does_not_hide_the_item_currency() -> None:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(_currency_sheets(("(лв.)", "(лв.)"))))
    cover = wb.create_sheet("Заглавна страница", 0)
    cover.append(["Обект: Жилищна сграда"])
    output = io.BytesIO()
    wb.save(output)
    result = _parse(output.getvalue())
    assert result.currency == "BGN"
    assert len([p for p in result.positions if not p.is_section]) == 2


def test_dual_currency_price_columns_are_refused() -> None:
    with pytest.raises(ImporterParseError) as error:
        _parse(_kss("Ед. цена (лв.)", "Стойност (€)"))
    assert error.value.code == "spreadsheet_currency_ambiguous"


def test_dual_currency_csv_columns_are_refused() -> None:
    content = "Наименование на видовете СМР;Ед. мярка;Количество;Ед. цена (лв.);Стойност (€)\nИзкоп;м3;1;100;51.13\n"
    with pytest.raises(ImporterParseError) as error:
        _parse(content.encode("utf-8"))
    assert error.value.code == "spreadsheet_currency_ambiguous"


@pytest.mark.parametrize(
    ("headings", "currency"),
    [
        (["Ед. цена (лв. без ДДС)"], "BGN"),
        (["Стойност в лева"], "BGN"),
        (["Цена BGN"], "BGN"),
        (["Ед. цена, €"], "EUR"),
        (["Стойност EUR"], "EUR"),
        (["Ед. цена (лв.)", "Ед. цена (€)"], ""),
        (["Количество", "Мярка"], ""),
        # "лв" inside a longer word is not the lev.
        (["Плевня"], ""),
    ],
)
def test_money_currency(headings: list[str], currency: str) -> None:
    assert money_currency(headings) == currency


@pytest.mark.parametrize(
    ("written", "canonical"),
    [
        ("м2", "м2"),
        ("м²", "м2"),
        ("кв.м", "м2"),
        ("кв. м.", "м2"),
        ("m2", "м2"),
        ("куб.м", "м3"),
        ("м³", "м3"),
        ("л.м.", "м"),
        ("м.л.", "м"),
        ("Бр", "бр."),
        ("броя", "бр."),
        ("к-т", "компл."),
        ("тона", "т"),
        ("бал", "бал"),
        ("", ""),
    ],
)
def test_canonical_unit(written: str, canonical: str) -> None:
    assert canonical_unit(written) == canonical


# -- lev to euro -------------------------------------------------------------


def test_a_lev_bill_converts_to_euro_and_keeps_its_lev_rates() -> None:
    result = _parse(_kss())
    lev_rates = [p.unit_rate for p in _work(result)]
    summary = convert_to_euro(result, result.currency)

    assert summary == {"from": "BGN", "to": "EUR", "rate": "1.95583", "lines": len(LINES) + 1}
    assert result.currency == "EUR"
    work = _work(result)
    for position, lev in zip(work, lev_rates, strict=True):
        # ЗВЕРБ чл. 12: divide by 1.95583, round to the cent half up.
        expected = (Decimal(str(lev)) / Decimal("1.95583")).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
        assert position.unit_rate == float(expected)
        assert position.metadata["original_currency"] == {"currency": "BGN", "unit_rate": lev, "rate": "1.95583"}
    assert work[0].unit_rate == 6.39  # 12.50 лв.
    assert all(p.unit_rate == 0 for p in result.positions if p.is_section)
    assert "currency_converted_to_euro" in [w.get("code") for w in result.warnings]


def test_a_currency_the_euro_did_not_replace_is_left_alone() -> None:
    result = _parse(_kss("Ед. цена, €", "Обща стойност, €"))
    before = [p.unit_rate for p in result.positions]
    assert convert_to_euro(result, "EUR") is None
    assert convert_to_euro(result, "USD") is None
    assert [p.unit_rate for p in result.positions] == before


# -- the import route converts only into a euro project -----------------------


@pytest.mark.parametrize(("project_currency", "converted"), [("EUR", True), ("BGN", False), ("", False)])
def test_the_route_converts_a_lev_bill_only_for_a_euro_project(
    monkeypatch: pytest.MonkeyPatch, project_currency: str, converted: bool
) -> None:
    from app.modules.boq import router
    from app.modules.projects import repository

    project = SimpleNamespace(currency=project_currency)

    class _Repo:
        def __init__(self, session: object) -> None:
            pass

        async def get_by_id(self, project_id: object) -> SimpleNamespace:
            return project

    class _Service:
        session = object()

        async def get_boq(self, boq_id: object) -> SimpleNamespace:
            return SimpleNamespace(project_id=uuid.uuid4())

    monkeypatch.setattr(repository, "ProjectRepository", _Repo)
    result = _parse(_kss())
    first_rate = _work(result)[0].unit_rate
    asyncio.run(router._convert_replaced_currency_to_euro(uuid.uuid4(), result, _Service()))

    assert (result.currency == "EUR") is converted
    assert (_work(result)[0].unit_rate == 6.39) is converted
    if not converted:
        assert _work(result)[0].unit_rate == first_rate


# -- the bill toolbar's import (/import/smart/) converts the same way ---------
#
# The toolbar sends every spreadsheet to /import/smart/, not /import/auto/, so
# the conversion above has to happen there too: a лева КСС going into a euro
# project used to be saved with each лев rate read as a euro rate.


def _smart_route(monkeypatch: pytest.MonkeyPatch, project_currency: str) -> list[ImportedBOQ]:
    """Point the smart route at a project in ``project_currency``; collect what it would save."""
    from app.modules.boq import router
    from app.modules.projects import repository

    project = SimpleNamespace(currency=project_currency)
    saved: list[ImportedBOQ] = []

    class _Repo:
        def __init__(self, session: object) -> None:
            pass

        async def get_by_id(self, project_id: object) -> SimpleNamespace:
            return project

    async def _persist(boq_id: object, imported: ImportedBOQ, **kwargs: object) -> dict:
        saved.append(imported)
        return {"created": 0, "updated": 0, "unchanged": 0, "apply_errors": []}

    monkeypatch.setattr(repository, "ProjectRepository", _Repo)
    monkeypatch.setattr(router, "_persist_imported_boq", _persist)
    return saved


class _SmartService:
    session = object()

    async def get_boq(self, boq_id: object) -> SimpleNamespace:
        return SimpleNamespace(project_id=uuid.uuid4())


@pytest.mark.parametrize(("project_currency", "converted"), [("EUR", True), ("BGN", False), ("", False)])
def test_the_toolbar_import_converts_a_lev_bill_only_for_a_euro_project(
    monkeypatch: pytest.MonkeyPatch, project_currency: str, converted: bool
) -> None:
    from app.modules.boq import router

    saved = _smart_route(monkeypatch, project_currency)
    native = asyncio.run(router._native_spreadsheet_import(_kss()))
    assert native is not None and native.currency == "BGN"

    response = asyncio.run(router._smart_native_result(uuid.uuid4(), native, "kss.xlsx", _SmartService(), "u"))

    (bill,) = saved
    assert (bill.currency == "EUR") is converted
    assert response["currency"] == ("EUR" if converted else "BGN")
    # 12.50 лв is 6.39 €, never 12.50 €.
    assert _work(bill)[0].unit_rate == (6.39 if converted else 12.5)
    codes = [w.get("code") for w in response["warnings"]]
    assert ("currency_converted_to_euro" in codes) is converted


@pytest.mark.parametrize("currencies", [("(лв.)", "(€)"), ("", "(лв.)")])
def test_the_toolbar_import_refuses_mixed_currencies_instead_of_guessing(currencies: tuple[str, ...]) -> None:
    # Swallowing the refusal used to hand the rows to the text reader and the
    # AI, which import the rates as written in whatever currency they are.
    from fastapi import HTTPException

    from app.modules.boq import router

    with pytest.raises(HTTPException) as error:
        asyncio.run(router._native_spreadsheet_import(_currency_sheets(currencies)))
    assert error.value.status_code == 400
    assert error.value.detail["code"] == "spreadsheet_currency_ambiguous"


def test_a_file_the_spreadsheet_reader_cannot_open_still_falls_through() -> None:
    from app.modules.boq import router

    assert asyncio.run(router._native_spreadsheet_import(b"not a workbook")) is None
