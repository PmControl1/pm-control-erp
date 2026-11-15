"""A bill sheet with no heading row is read from what its columns hold.

A working list of quantities (a КСС checked on site) is often a bare table: a
legend on top, then the description in column B, the unit in C, the quantity
in D and notes in F, with no row naming any column. Read for a heading, it
named nothing and the import said "the header row does not name a description
column". Its columns are now read from their cells, every such sheet of the
workbook is read, and the import says it did so.

A file that uses a number twice keeps both lines: the later one is numbered
"9-2" instead of being refused when the bill is saved.
"""

from __future__ import annotations

import asyncio
import io
from typing import Any

import pytest
from openpyxl import Workbook

from app.modules.boq.importers import ImportedBOQ
from app.modules.boq.importers._base import ImporterParseError
from app.modules.boq.importers.excel import ExcelImporter, _infer_columns


def _workbook(sheets: dict[str, list[list[Any]]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for row in rows:
            ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _parse(content: bytes) -> ImportedBOQ:
    return asyncio.run(ExcelImporter.parse(content, locale="bg"))


FLOOR_1 = [
    ["Означения"],
    [None, "редове за уточняване с проектанта"],
    [None, "редове, приети от надзора"],
    [],
    [],
    [None, "Подови настилки", None, None, "Етап"],
    [None, "Ниво +3,20"],
    [None, "(F1) Циментова замазка d=50 мм", "м2", 142.5],
    [None, "(F4) Ламинат клас 32", "м2", 88],
    [None, "Ниво +6,40"],
    [None, "(F1) Циментова замазка d=50 мм", "м2", 37, None, "уточни дебелината"],
    [None, "бетонна основа 12 см.", "м3", 8.5, None, "по последния чертеж"],
]

FLOOR_2 = [
    [],
    [None, "Довършителни работи"],
    [12, "Кухня"],
    [1, "Гипсова шпакловка", "м2", 31.5],
    [2, "Грундиране на стени", "м2", 31.5],
    [9, "Офис"],
    [9, "Боядисване на стени с латекс", "м2", 84],
    [12, "Полагане на теракота", "м2", 19],
]


def _sections(result: ImportedBOQ) -> list[str]:
    return [p.description for p in result.positions if p.is_section]


def _lines(result: ImportedBOQ) -> list[tuple[str, str, float]]:
    return [(p.description, p.unit, p.quantity) for p in result.positions if not p.is_section]


def test_a_sheet_without_a_heading_is_read_from_its_columns() -> None:
    result = _parse(_workbook({"Етаж 1": FLOOR_1}))
    assert result.metadata["column_mapping"] == {"1": "description", "2": "unit", "3": "quantity"}
    assert result.metadata["header_language"] == "bg"
    assert _lines(result) == [
        ("(F1) Циментова замазка d=50 мм", "м2", 142.5),
        ("(F4) Ламинат клас 32", "м2", 88.0),
        ("(F1) Циментова замазка d=50 мм", "м2", 37.0),
        ("бетонна основа 12 см.", "м3", 8.5),
    ]
    # The legend above the empty rows is not part of the bill; the headings
    # over the first line are.
    assert _sections(result) == ["Подови настилки", "Ниво +3,20", "Ниво +6,40"]
    (note,) = [w for w in result.warnings if w.get("code") == "columns_inferred"]
    assert note["params"] == {"sheet": "Етаж 1", "description": "B", "unit": "C", "quantity": "D"}


def test_every_sheet_without_a_heading_is_read() -> None:
    result = _parse(_workbook({"Етаж 1": FLOOR_1, "Етаж 2": FLOOR_2}))
    assert result.metadata["item_sheets"] == ["Етаж 1", "Етаж 2"]
    assert "Етаж 2" in _sections(result)
    assert ("Полагане на теракота", "м2", 19.0) in _lines(result)
    assert len([w for w in result.warnings if w.get("code") == "columns_inferred"]) == 2


def test_a_number_used_twice_keeps_both_lines() -> None:
    result = _parse(_workbook({"Етаж 2": FLOOR_2}))
    ordinals = [p.ordinal for p in result.positions]
    assert len(ordinals) == len(set(ordinals))
    by_text = {p.description: p for p in result.positions}
    # Every line is there, and the room headings keep their numbers.
    assert {"Боядисване на стени с латекс", "Полагане на теракота"} <= set(by_text)
    assert (by_text["Кухня"].ordinal, by_text["Офис"].ordinal) == ("12", "9")
    # A line repeating a number is qualified by its section where the file's
    # sections allow ("9.12"), and given a suffix where they do not.
    assert by_text["Полагане на теракота"].ordinal != "12"
    assert by_text["Боядисване на стени с латекс"].ordinal != "9"


def test_a_number_repeated_in_one_section_gets_a_suffix() -> None:
    rows = [
        [None, "Стени"],
        [1, "Шпакловка", "м2", 10],
        [2, "Грунд", "м2", 10],
        [2, "Боядисване", "м2", 10],
    ]
    result = _parse(_workbook({"Лист": rows}))
    assert [(p.ordinal, p.description) for p in result.positions if not p.is_section] == [
        ("1", "Шпакловка"),
        ("2", "Грунд"),
        ("2-2", "Боядисване"),
    ]
    assert result.positions[-1].metadata["source_ordinal"] == "2"
    (note,) = [w for w in result.warnings if w.get("code") == "repeated_numbers_kept"]
    assert note["params"] == {"count": 1, "example": "2 → 2-2"}


def test_rate_and_total_are_read_when_the_total_is_quantity_times_rate() -> None:
    rows = [
        [1, "Изкоп", "м3", 10, 5, 50],
        [2, "Насип", "м3", 4, 3.5, 14],
        [3, "Бетон", "м3", 2, 150, 300],
        [4, "Кофраж", "м2", 12.5, 28.6, 357.5],
    ]
    mapping, start = _infer_columns([tuple(row) for row in rows])  # type: ignore[misc]
    assert mapping == {0: "ordinal", 1: "description", 2: "unit", 3: "quantity", 4: "unit_rate", 5: "total"}
    assert start == 1


def test_two_number_columns_that_are_not_rate_and_total_are_left_out() -> None:
    rows = [[f"Ред {n}", "м2", 10 + n, 7 * n] for n in range(1, 6)]
    mapping, _ = _infer_columns([tuple(row) for row in rows])  # type: ignore[misc]
    assert mapping == {0: "description", 1: "unit", 2: "quantity"}


@pytest.mark.parametrize(
    "rows",
    [
        [["Бележки"], ["само текст", "без мерки"], ["още текст"]],
        [["Изкоп", "м3"], ["Насип", "м3"], ["Бетон", "м3"]],  # units, no quantity
        [["м2", 1], ["м3", 2], ["бр", 3]],  # no description
    ],
)
def test_a_sheet_that_is_not_a_bill_is_still_refused(rows: list[list[Any]]) -> None:
    assert _infer_columns([tuple(row) for row in rows]) is None
    try:
        result = _parse(_workbook({"Лист": rows}))
    except ImporterParseError:
        return
    # Read as before: whatever it was, it was not taken for a bill's lines.
    assert not [w for w in result.warnings if w.get("code") == "columns_inferred"]


def test_a_sheet_with_a_heading_is_read_by_its_heading() -> None:
    rows = [
        ["№", "Наименование на СМР", "Мярка", "Количество", "Бележка"],
        [1, "Изкоп", "м3", 10, 4],
        [2, "Насип", "м3", 4, 5],
        [3, "Бетон", "м3", 2, 6],
    ]
    result = _parse(_workbook({"КСС": rows}))
    assert not [w for w in result.warnings if w.get("code") == "columns_inferred"]
    assert [p.quantity for p in result.positions] == [10.0, 4.0, 2.0]
