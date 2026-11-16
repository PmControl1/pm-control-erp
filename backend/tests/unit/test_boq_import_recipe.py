"""A spreadsheet read with an import recipe comes out at the file's own total.

Bills come in layouts the heading rules do not know. A recipe (which sheets,
rows and columns hold the bill, and which cell its total) is carried out by
the importer's own code, and the reading is held against the file: the values
it writes on the lines read against its total cell, and each line's quantity
times unit price against the value written on it.

The three workbooks here are invented, in three layouts bills come in: a
budget form whose description column has a heading the rules do not know and
whose prices sit in columns the rules mis-read, a check list with no heading
row on two sheets, and a running КСС whose section headings carry their
subtotals.
"""

from __future__ import annotations

import asyncio
import io

import openpyxl
import pytest

from app.modules.boq.importers import ImporterParseError
from app.modules.boq.importers.excel import ExcelImporter
from app.modules.boq.importers.recipe import (
    ImportRecipe,
    column_index,
    column_letters,
    layout_key,
    parse_recipe,
)


def _book(sheets: dict[str, list[list[object]]]) -> bytes:
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def budget_form(*, title: str = "Искане за плащане") -> bytes:
    """A payment-request budget: "Етап на изграждането" heads the descriptions."""
    lines: list[list[object]] = [
        [None, "Етап 1: Конструкция", None, None, None, "без ДДС", None],
        [None, "Хидроизолация на основи", "м2", None, None, 412386.5, 210849.87],
        [None, "Тухлена зидария 25 см", "м2", 1250, 46, 57500, 29399.28],
        [None, "Вентилационни шахти", "м'", None, None, None, 0],
        [None, "Насипи с уплътняване", "м3", 3400, 12, 41950, 21448.69],
        [None, "Укрепване на изкопа", "сума", None, None, 365000, 186621.54],
        [None, "*Временно ел. захранване на обекта", None, None, None, 28000, 14316.17],
        [None, "Етап 2: Довършителни работи", None, None, None, None, 0],
        [None, "Вътрешна мазилка", "м2", 2600, 18, 46800, 23928.46],
        [None, "Подпрозоречни дъски ", "сума", None, "35 лв/бр.", 9800, 5010.66],
        [None, "Озеленяване", "м2", None, 18450, 18450, 9433.34],
    ]
    total = sum(row[5] for row in lines if isinstance(row[5], (int, float)))
    return _book(
        {
            "Бюджет": [
                [],
                [None, title],
                [],
                [],
                [None, "Етап на изграждането", "мярка", "количество", "ед.цена", "стойност, лв", "стойност €"],
                *lines,
                [],
                [],
                [None, "ОБЩО ЗА ОБЕКТА, лв без ДДС", None, None, None, round(total, 2), round(total / 1.95583, 2)],
            ]
        }
    )


BUDGET_TOTAL = 979886.5
BUDGET_RECIPE = {
    "sheets": [
        {
            "sheet": "Бюджет",
            "header_row": 5,
            "first_row": 6,
            "last_row": 16,
            "columns": {"description": "B", "unit": "C", "quantity": "D", "unit_rate": "E", "total": "F"},
            "file_total": {"row": 19, "column": "F"},
        }
    ],
    "currency": "BGN",
}


def check_list() -> bytes:
    """Two sheets with no heading row: quantities only, as a site check list."""
    return _book(
        {
            "Етаж 1": [
                ["Означения"],
                [None, "редове за уточняване с проектанта"],
                [],
                [None, "Подови настилки", None, None, "Етап"],
                [None, "Ниво +3,20"],
                [None, "(F1) Циментова замазка d=50 мм", "м2", "142.5"],
                [None, "(F4) Ламинат клас 32", "м2", "88"],
            ],
            "Етаж 2": [
                [],
                [None, "Подови настилки"],
                [None, "Ниво +6,40"],
                ["1", "(F1) Циментова замазка d=50 мм", "м2", "133"],
                ["2", "(F2) Гранитогрес 60/60", "м2", "41"],
            ],
        }
    )


CHECK_LIST_RECIPE = {
    "sheets": [
        {"sheet": "Етаж 1", "first_row": 4, "columns": {"description": "B", "unit": "C", "quantity": "D"}},
        {
            "sheet": "Етаж 2",
            "first_row": 2,
            "columns": {"ordinal": "A", "description": "B", "unit": "C", "quantity": "D"},
        },
    ]
}


def running_kss() -> bytes:
    """A running КСС: section headings carry subtotals, the total's label sits under the unit price."""
    header = [
        "№",
        "ЗОНА",
        "ЧАСТ",
        "ВИД СМР",
        "МЯРКА",
        "ЕД. ЦЕНА В ЛЕВА БЕЗ ДДС",
        "К-ВО АКТУВАНО",
        "СТОЙНОСТ В ЛЕВА БЕЗ ДДС",
        "К-ВО ОБЩО",
        "СТОЙНОСТ ОБЩО /лв без ДДС/",
    ]
    return _book(
        {
            "КСС": [
                ["Обект:", None, None, "ЖИЛИЩНА СГРАДА, БЛОК В"],
                [],
                header,
                [None, None, None, "ОСНОВНА СМЕТКА"],
                [None, None, "ЗР", "ЗЕМНИ РАБОТИ", None, None, None, 15949.0, None, 18261.6],
                [104, "ОБЩИ", "ЗР", "Разваляне на стара настилка", "m3", 12.4, 186.5, 2312.6, 186.5, 2312.6],
                [106, "ОБЩИ", "ЗР", "Хидроизолация на покрив", "m2", 38.9, 410, 15949.0, 410, 15949.0],
                [None, "Б", "ЕЛ", "ОСВЕТЛЕНИЕ", None, None, 0, 0, 0, 0],
                [2210, "Б", "ЕЛ", "Монтаж на LED осветително тяло", "бр.", 62.3, 4, 249.2, 4, 249.2],
                [None, None, None, None, None, 9.8, 120, 1176.0, 120, 1176.0],
                [2275, "Б", "ЕЛ", "Изтегляне на кабел NYM 3x2,5", "м", 3.65, 820, 2993.0, 820, 3008.45],
                [None, None, None, None, None, "ОБЩО ПО КСС БЕЗ НЕПРЕДВИДЕНИ", 0, 0, None, 22695.25],
                [None, None, None, "ОБЩО С ДДС", None, None, None, None, None, 27234.3],
            ]
        }
    )


RUNNING_KSS_RECIPE = {
    "sheets": [
        {
            "sheet": "КСС",
            "header_row": 3,
            "first_row": 4,
            "last_row": 11,
            "columns": {
                "ordinal": "A",
                "description": "D",
                "unit": "E",
                "unit_rate": "F",
                "quantity": "I",
                "total": "J",
            },
            "file_total": {"row": 12, "column": "J"},
        }
    ],
    "currency": "BGN",
}


def _read(content: bytes, recipe: dict[str, object], mapping: dict[int, str] | None = None):
    return asyncio.run(ExcelImporter.parse(content, column_mapping=mapping, recipe=parse_recipe(recipe)))


def _lines(imported):
    return [p for p in imported.positions if not p.is_section]


def _by_description(imported, text: str):
    return next(p for p in imported.positions if p.description.strip() == text)


# ── The budget form ─────────────────────────────────────────────────────────


def test_the_budget_form_comes_out_at_its_own_total() -> None:
    imported = _read(budget_form(), BUDGET_RECIPE)
    check = imported.metadata["reading"]["check"]

    assert check["file_total"] == BUDGET_TOTAL
    assert check["values_sum"] == BUDGET_TOTAL
    assert check["total_matches"] is True and check["ok"] is True
    assert check["file_total_cell"] == "F19"
    assert imported.currency == "BGN"


def test_a_value_only_line_is_a_lump_sum_that_keeps_its_unit_in_the_note() -> None:
    imported = _read(budget_form(), BUDGET_RECIPE)

    formwork = _by_description(imported, "Хидроизолация на основи")
    assert (formwork.unit, formwork.quantity, formwork.unit_rate) == ("сума", 1.0, 412386.5)
    assert formwork.metadata["amount_only"] is True
    assert formwork.metadata["source_unit"] == "м2"
    assert "м2" in formwork.metadata["comment"]

    # A line with no unit at all is a lump sum too, and a "сума" line stays one.
    estimate = _by_description(imported, "*Временно ел. захранване на обекта")
    assert (estimate.unit, estimate.unit_rate) == ("сума", 28000.0)
    wall = _by_description(imported, "Укрепване на изкопа")
    assert (wall.unit, wall.quantity, wall.unit_rate) == ("сума", 1.0, 365000.0)
    assert "source_unit" not in wall.metadata
    assert any(w.get("code") == "value_only_lines" for w in imported.warnings)


def test_a_line_whose_value_is_not_quantity_times_price_is_imported_as_written_and_flagged() -> None:
    imported = _read(budget_form(), BUDGET_RECIPE)
    check = imported.metadata["reading"]["check"]

    excavation = _by_description(imported, "Насипи с уплътняване")
    assert (excavation.quantity, excavation.unit_rate) == (3400.0, 12.0)
    assert excavation.metadata["value_differs"] == 1150.0
    assert "41 950,00" in excavation.metadata["comment"]
    assert check["mismatch_count"] == 1
    assert check["mismatches"][0]["row"] == 10 and check["mismatches"][0]["difference"] == 1150.0
    assert check["imported_sum"] == round(BUDGET_TOTAL - 1150, 2)
    flagged = [w for w in imported.warnings if w.get("code") == "value_differs"]
    assert [w["params"]["row"] for w in flagged] == [10]


def test_words_in_a_price_cell_go_to_the_note_and_the_line_keeps_its_value() -> None:
    imported = _read(budget_form(), BUDGET_RECIPE)

    stairs = _by_description(imported, "Подпрозоречни дъски")
    assert (stairs.unit, stairs.quantity, stairs.unit_rate) == ("сума", 1.0, 9800.0)
    assert "35 лв/бр." in stairs.metadata["comment"]
    assert not imported.errors


def test_sections_and_empty_lines_are_read_as_the_form_has_them() -> None:
    imported = _read(budget_form(), BUDGET_RECIPE)

    sections = [p.description for p in imported.positions if p.is_section]
    assert sections == ["Етап 1: Конструкция", "Етап 2: Довършителни работи"]
    chimney = _by_description(imported, "Вентилационни шахти")
    assert (chimney.quantity, chimney.unit_rate) == (0.0, 0.0)
    assert len(_lines(imported)) == 9


def test_the_heading_rules_alone_do_not_price_the_budget_form() -> None:
    """Why the form needs a recipe: read by its headings, not one line is priced."""
    imported = asyncio.run(ExcelImporter.parse(budget_form()))

    assert not any(p.unit_rate for p in _lines(imported))


# ── The check list ──────────────────────────────────────────────────────────


def test_a_check_list_without_a_heading_row_is_read_on_both_sheets() -> None:
    imported = _read(check_list(), CHECK_LIST_RECIPE)
    check = imported.metadata["reading"]["check"]

    lines = _lines(imported)
    assert [(p.unit, p.quantity) for p in lines] == [("м2", 142.5), ("м2", 88.0), ("м2", 133.0), ("м2", 41.0)]
    assert check["file_total"] is None and check["total_matches"] is None and check["ok"] is True
    assert imported.metadata["header_language"] == "bg"
    assert imported.metadata["item_sheets"] == ["Етаж 1", "Етаж 2"]


# ── The running КСС ─────────────────────────────────────────────────────────


def test_a_heading_carrying_its_subtotal_stays_a_heading() -> None:
    imported = _read(running_kss(), RUNNING_KSS_RECIPE)

    heading = _by_description(imported, "ЗЕМНИ РАБОТИ")
    assert heading.is_section


def test_the_running_kss_comes_out_at_its_total_with_the_priced_row_that_has_no_description() -> None:
    imported = _read(running_kss(), RUNNING_KSS_RECIPE)
    check = imported.metadata["reading"]["check"]

    assert check["values_sum"] == check["file_total"] == 22695.25
    assert check["total_matches"] is True
    unnamed = next(p for p in _lines(imported) if p.metadata.get("no_description"))
    assert (unnamed.quantity, unnamed.unit_rate) == (120.0, 9.8)
    assert "ред 10" in unnamed.description
    assert check["mismatch_count"] == 1 and check["mismatches"][0]["difference"] == 15.45


def test_the_total_cell_is_found_below_the_bill_when_the_recipe_names_none() -> None:
    recipe = {**RUNNING_KSS_RECIPE, "sheets": [{**RUNNING_KSS_RECIPE["sheets"][0], "file_total": None}]}
    imported = _read(running_kss(), recipe)
    check = imported.metadata["reading"]["check"]

    assert check["file_total"] == 22695.25
    assert check["file_total_cell"] == "J12"


def test_a_recipe_reading_the_wrong_rows_says_the_total_differs() -> None:
    recipe = {**RUNNING_KSS_RECIPE, "sheets": [{**RUNNING_KSS_RECIPE["sheets"][0], "last_row": 7}]}
    imported = _read(running_kss(), recipe)
    check = imported.metadata["reading"]["check"]

    assert check["total_matches"] is False and check["ok"] is False
    assert any(w.get("code") == "file_total_differs" for w in imported.warnings)


# ── The recipe itself ───────────────────────────────────────────────────────


def test_the_columns_the_person_chose_are_laid_over_the_recipe() -> None:
    # Column F (index 5) is the value column; reading it as nothing leaves value-only lines unpriced.
    imported = _read(budget_form(), BUDGET_RECIPE, mapping={5: ""})
    recipe = imported.metadata["reading"]["recipe"]

    assert "total" not in {k for k, v in recipe["sheets"][0]["columns"].items() if v}
    assert _by_description(imported, "Хидроизолация на основи").unit_rate == 0.0

    moved = ImportRecipe.model_validate(BUDGET_RECIPE).with_columns({6: "total"})
    assert moved.sheets[0].columns.total == "G"


@pytest.mark.parametrize(
    "broken",
    [
        {"sheets": []},
        {"sheets": [{"sheet": "S", "first_row": 2, "columns": {"description": "B", "quantity": "B"}}]},
        {"sheets": [{"sheet": "S", "first_row": 2, "columns": {"description": "B"}}]},
        {"sheets": [{"sheet": "S", "first_row": 2, "columns": {"description": "B2", "unit": "C"}}]},
        {"sheets": [{"sheet": "S", "header_row": 4, "first_row": 3, "columns": {"description": "B", "unit": "C"}}]},
        {"sheets": [{"sheet": "S", "first_row": 9, "last_row": 3, "columns": {"description": "B", "unit": "C"}}]},
    ],
)
def test_a_recipe_that_cannot_be_carried_out_is_refused(broken: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        parse_recipe(broken)


def test_a_recipe_naming_a_sheet_the_file_lacks_is_refused_with_a_code() -> None:
    recipe = {"sheets": [{**BUDGET_RECIPE["sheets"][0], "sheet": "Липсващ"}]}
    with pytest.raises(ImporterParseError) as raised:
        _read(budget_form(), recipe)
    assert raised.value.code == "recipe_sheet_missing"
    assert raised.value.params == {"sheet": "Липсващ"}


def test_column_letters_and_indices_are_each_others_inverse() -> None:
    for index in (0, 1, 25, 26, 27, 701, 702, 16383):
        assert column_index(column_letters(index)) == index
    assert column_letters(27) == "AB"


def test_two_files_of_one_layout_share_a_layout_key_and_another_layout_does_not() -> None:
    recipe = ImportRecipe.model_validate(BUDGET_RECIPE)

    def key(content: bytes) -> str | None:
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            return layout_key(workbook, recipe)
        finally:
            workbook.close()

    same = key(budget_form())
    assert same is not None
    assert key(budget_form(title="Друг обект")) == same
    assert key(running_kss()) is None  # no sheet "Бюджет"
    other = _book({"Бюджет": [[], [], [], [], [None, "Описание", "мярка", "количество", "ед.цена", "стойност"]]})
    assert key(other) != same
