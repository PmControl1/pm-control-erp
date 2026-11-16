"""A layout the AI worked out is kept, and the next file laid out the same way is read with it.

The second file of a layout (the same form for another site, next month's
payment request) needs no AI call: its recipe is found by the layout key of
its sheets and headings, and its reading is used when it still adds up.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.boq import import_reading
from app.modules.boq.import_reading import read_spreadsheet, remember
from app.modules.boq.importers.excel import ExcelImporter
from app.modules.boq.importers.recipe import parse_recipe
from app.modules.boq.models import BOQImportRecipe
from tests.unit.test_boq_import_recipe import BUDGET_RECIPE, budget_form, running_kss

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pg_session():
    from tests._pg import isolated_engine

    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            yield session


async def _ai_reading(content: bytes):
    imported = await ExcelImporter.parse(content, recipe=parse_recipe(BUDGET_RECIPE))
    return import_reading.mark(imported, "ai")


async def _no_ai(*_args, **_kwargs):
    raise AssertionError("the workspace AI was asked")


async def test_a_recipe_the_ai_wrote_reads_the_next_file_of_its_layout(pg_session, monkeypatch) -> None:
    first = budget_form()
    await remember(pg_session, first, await _ai_reading(first), file_name="Бюджет май.xlsx", user_id=None)

    saved = (await pg_session.execute(select(BOQImportRecipe))).scalars().all()
    assert [(row.source, row.file_name, row.sheet_names, row.uses) for row in saved] == [
        ("ai", "Бюджет май.xlsx", ["Бюджет"], 1)
    ]

    monkeypatch.setattr(import_reading, "workspace_ai", _no_ai)
    second = budget_form(title="Искане за плащане - юни")
    imported = await read_spreadsheet(
        second,
        file_name="Бюджет юни.xlsx",
        locale="bg",
        overrides=None,
        recipe=None,
        session=pg_session,
        user_id=None,
    )

    reading = imported.metadata["reading"]
    assert reading["source"] == "saved"
    assert reading["saved_from"] == "Бюджет май.xlsx"
    assert reading["check"]["total_matches"] is True


async def test_a_file_of_another_layout_is_not_read_with_it(pg_session, monkeypatch) -> None:
    first = budget_form()
    await remember(pg_session, first, await _ai_reading(first), file_name="Бюджет.xlsx", user_id=None)

    async def no_ai(*_args, **_kwargs):
        return None

    monkeypatch.setattr(import_reading, "workspace_ai", no_ai)
    imported = await read_spreadsheet(
        running_kss(),
        file_name="КСС.xlsx",
        locale="bg",
        overrides=None,
        recipe=None,
        session=pg_session,
        user_id=None,
    )

    assert imported.metadata["reading"]["source"] == "rules"


async def test_the_columns_a_person_chose_replace_the_kept_recipe(pg_session) -> None:
    content = budget_form()
    await remember(pg_session, content, await _ai_reading(content), file_name="a.xlsx", user_id=None)

    edited = await ExcelImporter.parse(content, column_mapping={6: "total"}, recipe=parse_recipe(BUDGET_RECIPE))
    await remember(pg_session, content, import_reading.mark(edited, "person"), file_name="b.xlsx", user_id=None)

    row = (await pg_session.execute(select(BOQImportRecipe))).scalar_one()
    assert row.source == "person"
    assert row.file_name == "b.xlsx"
    assert row.recipe["sheets"][0]["columns"]["total"] == "G"
    assert row.uses == 2


async def test_a_reading_by_the_rules_is_not_kept(pg_session) -> None:
    content = running_kss()
    imported = import_reading.mark(await ExcelImporter.parse(content), "rules")

    await remember(pg_session, content, imported, file_name="КСС.xlsx", user_id=None)

    assert (await pg_session.execute(select(BOQImportRecipe))).scalars().all() == []


async def test_a_recipe_sent_back_from_the_preview_is_kept_as_what_it_came_from(pg_session) -> None:
    content = budget_form()
    by_ai = parse_recipe({**BUDGET_RECIPE, "origin": "ai"})
    by_rules = parse_recipe({**BUDGET_RECIPE, "origin": "rules"})

    previewed = import_reading.mark(await ExcelImporter.parse(content, recipe=by_rules), "preview")
    await remember(pg_session, content, previewed, file_name="rules.xlsx", user_id=None)
    assert (await pg_session.execute(select(BOQImportRecipe))).scalars().all() == []

    previewed = import_reading.mark(await ExcelImporter.parse(content, recipe=by_ai), "preview")
    await remember(pg_session, content, previewed, file_name="ai.xlsx", user_id=None)
    row = (await pg_session.execute(select(BOQImportRecipe))).scalar_one()
    assert (row.source, row.file_name) == ("ai", "ai.xlsx")
