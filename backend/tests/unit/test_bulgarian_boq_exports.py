"""Bulgarian workbook text retains the shared export/import contract."""

from __future__ import annotations

import io
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from app.modules.boq.importers.excel import ExcelImporter, _is_export_fx_appendix
from app.modules.boq.router import _render_boq_csv, _render_boq_xlsx


def _bill() -> tuple[SimpleNamespace, SimpleNamespace]:
    position = SimpleNamespace(
        id=uuid.uuid4(),
        parent_id=None,
        ordinal="1",
        description="Кофраж",
        unit="м2",
        quantity=Decimal("2"),
        unit_rate=Decimal("100"),
        total=Decimal("200"),
        classification={},
        metadata={},
        cad_element_ids=[],
        source="manual",
        confidence=None,
        wbs_id=None,
    )
    flat = SimpleNamespace(name="КСС", positions=[position])
    structured = SimpleNamespace(
        name="КСС",
        sections=[],
        positions=[position],
        markups=[],
        direct_cost=Decimal("200"),
        net_total=Decimal("200"),
        grand_total=Decimal("200"),
    )
    return flat, structured


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", ["en", "bg"])
async def test_frozen_fx_appendix_is_not_reimported_as_work(locale: str) -> None:
    flat, structured = _bill()
    content = _render_boq_xlsx(
        flat,
        structured,
        custom_columns=[],
        project_line=None,
        base_ccy="EUR",
        fx_map={"BGN": "0.511292"},
        locale=locale,
    )
    parsed = await ExcelImporter.parse(content, locale=locale)
    assert not parsed.errors
    assert len(parsed.positions) == 1
    assert parsed.positions[0].position_id == str(flat.positions[0].id)
    assert parsed.positions[0].description == "Кофраж"
    assert parsed.positions[0].quantity == 2
    assert parsed.positions[0].unit_rate == 100
    if locale == "bg":
        rows = list(load_workbook(io.BytesIO(content), data_only=True).active.iter_rows(values_only=True))
        assert any(row[1] == "Обща стойност" and row[5] == 200 for row in rows)
        assert not any(row[1] == "Всичко с ДДС" for row in rows)


@pytest.mark.asyncio
async def test_canonical_csv_also_excludes_its_frozen_fx_appendix() -> None:
    _, structured = _bill()
    content = _render_boq_csv(structured, "EUR", {"BGN": "0.511292"}).encode("utf-8")
    parsed = await ExcelImporter.parse(content)
    assert not parsed.errors
    assert len(parsed.positions) == 1
    assert parsed.positions[0].description == "Кофраж"


def test_a_work_item_that_mentions_the_appendix_title_is_not_an_appendix() -> None:
    assert not _is_export_fx_appendix(["1", "FX Rates (frozen at export)", "h", 2, 100, 200])
    assert not _is_export_fx_appendix([None, "Валутни курсове (към износа)", "ч", 2, 100, 200])
