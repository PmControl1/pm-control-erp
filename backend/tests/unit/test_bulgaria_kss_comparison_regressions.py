"""Compare real Bulgarian workbooks after native import persistence."""

from __future__ import annotations

import io
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from openpyxl import Workbook

from app.core.validation.engine import ValidationContext
from app.core.validation.rules.bulgaria_kss import BulgarianKssMatchesTenderBill
from app.modules.boq.importers.excel import ExcelImporter
from app.modules.boq.router import _persist_imported_boq


class _RecordingService:
    """Preserve the real service's unique-ordinal invariant without a database."""

    def __init__(self) -> None:
        self.positions: list[Any] = []

    async def get_boq_with_positions(self, _boq_id: Any) -> Any:
        return SimpleNamespace(positions=list(self.positions))

    async def add_position(self, data: Any) -> Any:
        if any(position.ordinal == data.ordinal for position in self.positions):
            raise HTTPException(409, f"Position with ordinal '{data.ordinal}' already exists in this BOQ")
        position = SimpleNamespace(
            id=uuid.uuid4(),
            parent_id=data.parent_id,
            ordinal=data.ordinal,
            description=data.description,
            unit=data.unit,
            quantity=data.quantity,
            metadata_=data.metadata,
        )
        self.positions.append(position)
        return position

    async def list_markups(self, _boq_id: Any) -> list[Any]:
        return []


def _workbook(*, priced: bool, omit: tuple[int, int] | None = None, numbered_sections: bool = True) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    headers = ["№ по ред", "Наименование на видовете СМР", "Ед. мярка", "Количество"]
    if priced:
        headers += ["Ед. цена, €", "Стойност, €"]
    sheet.append(headers)
    for section_index, (roman, title, lines) in enumerate(
        [
            ("I.", "ЗЕМНИ РАБОТИ", [("Изкоп", "куб.м", 10.1234), ("Насип", "м3", 4)]),
            ("II.", "БЕТОНОВИ РАБОТИ", [("Бетон", "м3", 12), ("Арматура", "кг", 100)]),
        ],
        start=1,
    ):
        sheet.append([roman if numbered_sections else None, title, None, None])
        for ordinal, (description, unit, quantity) in enumerate(lines, start=1):
            if omit == (section_index, ordinal):
                continue
            row: list[Any] = [ordinal, description, "м3" if priced and unit == "куб.м" else unit, quantity]
            if priced:
                row += [5, round(quantity * 5, 2)]
            sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


async def _import(content: bytes) -> tuple[Any, list[dict[str, Any]]]:
    imported = await ExcelImporter.parse(content, locale="bg")
    assert imported.errors == []
    service = _RecordingService()
    summary = await _persist_imported_boq(
        uuid.uuid4(),
        imported,
        file_name="КСС.xlsx",
        service=service,  # type: ignore[arg-type]
    )
    assert summary["apply_errors"] == []
    assert summary["created"] == len(imported.positions)
    rows = [
        {
            "id": str(position.id),
            "parent_id": str(position.parent_id) if position.parent_id else None,
            "ordinal": position.ordinal,
            "description": position.description,
            "unit": position.unit,
            "quantity": position.quantity,
            "type": "section" if position.unit == "section" else "position",
            "metadata": position.metadata_,
        }
        for position in service.positions
    ]
    return imported, rows


@pytest.mark.asyncio
@pytest.mark.parametrize("numbered_sections", [True, False])
async def test_quantity_only_and_priced_workbooks_keep_all_restarted_lines(numbered_sections: bool) -> None:
    _, tender = await _import(_workbook(priced=False, numbered_sections=numbered_sections))
    imported, priced = await _import(_workbook(priced=True, numbered_sections=numbered_sections))
    ordinals = [position.ordinal for position in imported.positions]
    assert len(ordinals) == len(set(ordinals))
    work = [position for position in priced if position["type"] == "position"]
    assert len(work) == 4
    assert all(position["parent_id"] for position in work)
    assert [position["metadata"]["kss_source_ordinal"] for position in work] == ["1", "2", "1", "2"]
    results = await BulgarianKssMatchesTenderBill().validate(
        ValidationContext(data={"positions": priced, "kss_tender": {"name": "КС", "positions": tender}})
    )
    assert len(results) == 4
    assert all(result.passed for result in results)


@pytest.mark.asyncio
@pytest.mark.parametrize("numbered_sections", [True, False])
async def test_a_missing_row_does_not_shift_its_neighbours_comparison_keys(numbered_sections: bool) -> None:
    _, tender = await _import(_workbook(priced=False, numbered_sections=numbered_sections))
    _, priced = await _import(_workbook(priced=True, omit=(2, 2), numbered_sections=numbered_sections))
    results = await BulgarianKssMatchesTenderBill().validate(
        ValidationContext(data={"positions": priced, "kss_tender": {"name": "КС", "positions": tender}})
    )
    failures = [result for result in results if not result.passed]
    assert len(failures) == 1
    assert failures[0].details["difference"] == "missing"
    assert failures[0].details["description"] == "Арматура"


@pytest.mark.asyncio
async def test_ambiguous_duplicate_numbers_inside_one_section_stay_invalid() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["№ по ред", "Наименование на видовете СМР", "Ед. мярка", "Количество"])
    sheet.append(["I.", "ЗЕМНИ РАБОТИ", None, None])
    sheet.append([1, "Изкоп", "м3", 10])
    sheet.append([1, "Насип", "м3", 4])
    output = io.BytesIO()
    workbook.save(output)
    imported = await ExcelImporter.parse(output.getvalue(), locale="bg")
    assert [position.ordinal for position in imported.positions] == ["I.", "1", "1"]
