"""A file whose numbers the bill already has is refused whole, or replaces the bill's lines.

Each colliding row used to be refused on its own: a КСС imported into a bill
that already had its numbers came in not at all ("could not be saved, no rows
were imported") or with some of its lines silently missing. The import now
refuses the file before writing anything (409 ``import_bill_has_lines``),
and imports it in place of the bill's lines when the person chose to replace
them. A file imported again on purpose (``append_on_collision``) still appends
with new numbers, and a refusal that writes nothing carries its reason.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.boq.importers import ImportedBOQ, ImportedPosition
from app.modules.boq.router import _persist_imported_boq


class _Bill:
    """The service calls an import makes, over a list, with the unique-number guard."""

    def __init__(self, ordinals: list[str]) -> None:
        self.positions: list[Any] = [
            SimpleNamespace(id=uuid.uuid4(), parent_id=None, ordinal=o, description=f"стар {o}") for o in ordinals
        ]
        self.deleted: list[str] = []

    async def get_boq_with_positions(self, _boq_id: Any) -> Any:
        return SimpleNamespace(positions=list(self.positions))

    async def delete_position(self, position_id: Any, *, cascade: bool = False) -> None:
        assert cascade
        gone = {position_id} | {p.id for p in self.positions if p.parent_id == position_id}
        self.deleted += [p.ordinal for p in self.positions if p.id in gone]
        self.positions = [p for p in self.positions if p.id not in gone]

    async def add_position(self, data: Any) -> Any:
        if any(p.ordinal == data.ordinal for p in self.positions):
            raise HTTPException(409, f"Position with ordinal '{data.ordinal}' already exists in this BOQ")
        position = SimpleNamespace(
            id=uuid.uuid4(), parent_id=data.parent_id, ordinal=data.ordinal, description=data.description
        )
        self.positions.append(position)
        return position

    async def list_markups(self, _boq_id: Any) -> list[Any]:
        return []


def _kss() -> ImportedBOQ:
    return ImportedBOQ(
        positions=[
            ImportedPosition(description="I. ЗЕМНИ РАБОТИ", ordinal="I", unit="section", is_section=True),
            ImportedPosition(description="Изкоп", ordinal="1", unit="м3", quantity=10, unit_rate=5),
            ImportedPosition(description="Насип", ordinal="2", unit="м3", quantity=4, unit_rate=3),
        ]
    )


def _persist(bill: _Bill, **options: Any) -> dict[str, Any]:
    return asyncio.run(_persist_imported_boq(uuid.uuid4(), _kss(), file_name="kss.xlsx", service=bill, **options))  # type: ignore[arg-type]


def test_an_empty_bill_takes_the_file() -> None:
    bill = _Bill([])
    assert _persist(bill)["created"] == 3
    assert [p.ordinal for p in bill.positions] == ["I", "1", "2"]


def test_a_bill_with_the_files_numbers_refuses_it_before_writing_anything() -> None:
    bill = _Bill(["I", "1", "2", "3"])
    with pytest.raises(HTTPException) as refused:
        _persist(bill)
    assert refused.value.status_code == 409
    detail = refused.value.detail
    assert detail["code"] == "import_bill_has_lines"
    assert detail["params"] == {"lines": 4, "taken": "I, 1, 2"}
    assert [p.description for p in bill.positions] == ["стар I", "стар 1", "стар 2", "стар 3"]


def test_one_taken_number_is_enough_to_refuse_a_partial_bill() -> None:
    bill = _Bill(["2"])
    with pytest.raises(HTTPException) as refused:
        _persist(bill)
    assert refused.value.detail["params"]["taken"] == "2"
    assert len(bill.positions) == 1


def test_a_bill_whose_numbers_the_file_does_not_use_takes_it() -> None:
    bill = _Bill(["10", "11"])
    assert _persist(bill)["created"] == 3
    assert [p.ordinal for p in bill.positions] == ["10", "11", "I", "1", "2"]


def test_replace_puts_the_files_lines_in_place_of_the_bills() -> None:
    bill = _Bill(["I", "1", "2", "3"])
    child = SimpleNamespace(id=uuid.uuid4(), parent_id=bill.positions[0].id, ordinal="I.1", description="стар I.1")
    bill.positions.append(child)
    assert _persist(bill, replace=True)["created"] == 3
    assert sorted(bill.deleted) == sorted(["I", "I.1", "1", "2", "3"])
    assert [(p.ordinal, p.description) for p in bill.positions] == [
        ("I", "I. ЗЕМНИ РАБОТИ"),
        ("1", "Изкоп"),
        ("2", "Насип"),
    ]


def test_importing_again_on_purpose_still_appends_with_new_numbers() -> None:
    bill = _Bill(["I", "1", "2"])
    assert _persist(bill, append_on_collision=True)["created"] == 3
    assert len(bill.positions) == 6
