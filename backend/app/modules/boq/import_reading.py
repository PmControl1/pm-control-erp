# PM Project Management - which reading of a spreadsheet the import uses.
# Licensed under the GNU AGPL v3.0 or later, like the rest of this program.
"""Choose how a spreadsheet bill is read, and keep the layouts that had to be worked out.

A workbook can be read four ways (see :mod:`app.modules.boq.importers.recipe`):

1. **The preview's reading.** The import preview shows a reading and its
   recipe; the person may change its columns. Importing sends that recipe
   back, so the bill imported is the bill previewed, with no second guess
   and no second AI call.
2. **A saved reading.** A layout read once by the AI, or corrected by a
   person, is kept (:class:`~app.modules.boq.models.BOQImportRecipe`), and
   the next file laid out the same way is read the same way.
3. **The heading rules.** Most КСС are headed in words the rules know. Their
   reading is also written down as a recipe and held against the file's own
   total; where the recipe reads more of the file (a priced line left
   without a description, a line priced only by its value), its reading is
   the one used.
4. **The workspace AI.** When the rules' reading is doubtful (no heading
   row they know, prices in the file but none read, many rows they could
   not read), the AI is asked for a recipe (:mod:`app.modules.boq.ai_recipe`).

Every reading says which it was under ``metadata["reading"]["source"]``
(``preview``, ``person``, ``saved``, ``rules``, ``ai``), with its recipe and
the check of its values against the file.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.importers import ImportedBOQ, ImporterParseError
from app.modules.boq.importers.recipe import (
    ImportRecipe,
    RecipeColumns,
    RecipeSheet,
    column_letters,
    layout_key,
)

logger = logging.getLogger(__name__)

# The column names the preview reports, back to a recipe's fields.
_FIELD_OF_REPORTED = {
    "ordinal": "ordinal",
    "description": "description",
    "unit": "unit",
    "quantity": "quantity",
    "unit_rate": "unit_rate",
    "total": "total",
    "classification": "code",
}
# Saved recipes compared with one workbook.
_SAVED_LOOKUP_LIMIT = 200


def _lines(imported: ImportedBOQ) -> list[Any]:
    return [position for position in imported.positions if not position.is_section]


def _sum(imported: ImportedBOQ) -> float:
    return sum(float(p.quantity) * float(p.unit_rate) for p in _lines(imported))


def _check(imported: ImportedBOQ) -> dict[str, Any] | None:
    return ((imported.metadata or {}).get("reading") or {}).get("check")


def mark(imported: ImportedBOQ, source: str, **extra: Any) -> ImportedBOQ:
    """Say which reading ``imported`` is; see the module docstring."""
    reading = dict((imported.metadata or {}).get("reading") or {})
    reading.update({"source": source, **extra})
    imported.metadata = {**(imported.metadata or {}), "reading": reading}
    return imported


# ── The rules' reading as a recipe ─────────────────────────────────────────


def recipe_of_rules(imported: ImportedBOQ) -> ImportRecipe | None:
    """The heading rules' reading of a one-sheet workbook, written down as a recipe.

    ``None`` when it cannot be written as one: several sheets, a rate split
    into material and labour, a Position ID column (a round trip, which only
    the rules carry), or no description column.
    """
    meta = imported.metadata or {}
    sheets = meta.get("item_sheets") or ([meta["item_sheet"]] if meta.get("item_sheet") else [])
    mapping = meta.get("column_mapping") or {}
    if len(sheets) != 1 or not mapping or meta.get("column_mapping_applied"):
        return None
    reported = list(mapping.values())
    if len(reported) != len(set(reported)) or any(value not in _FIELD_OF_REPORTED for value in reported):
        return None
    columns = {_FIELD_OF_REPORTED[value]: column_letters(int(index)) for index, value in mapping.items()}
    rows = [int((p.metadata or {}).get("import_row_index") or 0) for p in imported.positions]
    rows = [row for row in rows if row > 0]
    if "description" not in columns or not rows:
        return None
    header_row = meta.get("header_row")
    first = min(rows)
    try:
        return ImportRecipe(
            sheets=[
                RecipeSheet(
                    sheet=str(sheets[0]),
                    header_row=header_row if isinstance(header_row, int) and header_row < first else None,
                    first_row=first,
                    last_row=max(rows),
                    columns=RecipeColumns(**columns),
                )
            ],
            currency=imported.currency if imported.currency in ("BGN", "EUR") else "",
            origin="rules",
        )
    except ValueError:
        return None


def _better(candidate: ImportedBOQ, rules: ImportedBOQ) -> bool:
    """Whether the recipe's reading of the rules' layout comes nearer the file than the rules' own."""
    check = _check(candidate) or {}
    target = check.get("file_total") if check.get("file_total") is not None else check.get("values_sum")
    if target is None or not check.get("ok"):
        return False
    return abs(_sum(candidate) - target) + 0.01 < abs(_sum(rules) - target)


def doubtful(imported: ImportedBOQ) -> bool:
    """Whether the heading rules' reading is likely wrong, so the AI should be asked.

    No line read; a heading the rules did not understand (columns guessed
    from what they hold, or a heading naming no description or quantity);
    a price or value column read with no line priced; or many rows that
    could not be read.
    """
    lines = _lines(imported)
    if not lines:
        return True
    if any(w.get("code") == "columns_inferred" for w in imported.warnings):
        return True
    if (imported.metadata.get("header_report") or {}).get("missing"):
        return True
    mapped = set((imported.metadata.get("column_mapping") or {}).values())
    if mapped & {"unit_rate", "total"} and not any(p.unit_rate for p in lines):
        return True
    check = _check(imported)
    if check is not None and check.get("total_matches") is False:
        return True
    return len(imported.errors) > max(3, len(lines) // 20)


# ── Saved readings ──────────────────────────────────────────────────────────


async def _saved_reading(
    session: AsyncSession, content: bytes, read: Callable[[ImportRecipe], Awaitable[ImportedBOQ]]
) -> ImportedBOQ | None:
    """The workbook read with the saved recipe of its layout, when there is one that holds up."""
    from app.modules.boq.importers._workbook import open_workbook
    from app.modules.boq.importers.recipe import parse_recipe
    from app.modules.boq.models import BOQImportRecipe

    query = select(BOQImportRecipe).order_by(BOQImportRecipe.updated_at.desc()).limit(_SAVED_LOOKUP_LIMIT)
    # In a savepoint: a lookup that fails must not leave the import's
    # transaction aborted.
    async with session.begin_nested():
        rows = list((await session.execute(query)).scalars().all())
    if not rows:
        return None
    try:
        workbook = open_workbook(content)
    except Exception:  # noqa: BLE001 - the rules' reader says what is wrong with the file
        return None
    try:
        names = set(workbook.sheetnames)
        match: tuple[Any, ImportRecipe] | None = None
        for row in rows:
            if not set(row.sheet_names or ()) <= names:
                continue
            try:
                recipe = parse_recipe(row.recipe)
            except ValueError:
                continue
            if recipe is not None and layout_key(workbook, recipe) == row.layout_key:
                match = (row, recipe)
                break
    finally:
        workbook.close()
    if match is None:
        return None
    row, recipe = match
    try:
        imported = await read(recipe)
    except ImporterParseError:
        return None
    if not (_check(imported) or {}).get("ok"):
        return None
    return mark(imported, "saved", saved_id=str(row.id), saved_from=row.file_name)


async def remember(
    session: AsyncSession,
    content: bytes,
    imported: ImportedBOQ,
    *,
    file_name: str,
    user_id: uuid.UUID | None,
) -> None:
    """Keep the recipe a bill was imported with, when it had to be worked out (by the AI or a person).

    One recipe per layout: a layout imported again with another recipe keeps
    the newer one. Written in a savepoint of the import's transaction, which
    the import commits. Never raises; a recipe not kept is worked out again
    next time.
    """
    from app.modules.boq.importers._workbook import open_workbook
    from app.modules.boq.importers.recipe import parse_recipe
    from app.modules.boq.models import BOQImportRecipe

    reading = (imported.metadata or {}).get("reading") or {}
    if not reading.get("recipe"):
        return
    try:
        recipe = parse_recipe(reading["recipe"])
        if recipe is None:
            return
        # A recipe sent back from the preview is kept as what it came from.
        source = reading.get("source")
        if source == "person" or recipe.origin == "person":
            source = "person"
        elif source == "ai" or recipe.origin == "ai":
            source = "ai"
        elif source != "saved":
            return
        workbook = open_workbook(content)
        try:
            key = layout_key(workbook, recipe)
        finally:
            workbook.close()
    except Exception:  # noqa: BLE001 - see docstring
        logger.warning("Could not work out the layout of %s to keep its recipe", file_name, exc_info=True)
        return
    if key is None:
        return
    data = recipe.model_dump(mode="json")
    try:
        # In a savepoint, and left to the import to commit: keeping a recipe
        # must never undo the bill it read.
        async with session.begin_nested():
            query = select(BOQImportRecipe).where(BOQImportRecipe.layout_key == key)
            row = (await session.execute(query)).scalar_one_or_none()
            if row is None:
                session.add(
                    BOQImportRecipe(
                        layout_key=key,
                        recipe=data,
                        sheet_names=[sheet.sheet for sheet in recipe.sheets],
                        source="person" if source == "person" else "ai",
                        file_name=file_name[:255],
                        created_by=user_id,
                        uses=1,
                    )
                )
            else:
                if source != "saved":
                    row.recipe = data
                    row.sheet_names = [sheet.sheet for sheet in recipe.sheets]
                    row.source = "person" if source == "person" else row.source
                    row.file_name = file_name[:255]
                row.uses = int(row.uses or 0) + 1
            await session.flush()
    except Exception:  # noqa: BLE001 - see docstring
        logger.warning("Could not keep the import recipe of %s", file_name, exc_info=True)


# ── The workspace AI ────────────────────────────────────────────────────────


async def workspace_ai(session: AsyncSession, user_id: uuid.UUID | str | None) -> tuple[Any, bool] | None:
    """``(ask, workspace_managed)`` for the AI the user may use, or ``None`` when there is none."""
    from app.modules.ai import workspace
    from app.modules.ai.ai_client import call_ai, resolve_provider_key_model
    from app.modules.ai.repository import AISettingsRepository
    from app.modules.boq.ai_recipe import RECIPE_SYSTEM

    if user_id is None:
        return None
    try:
        settings = await AISettingsRepository(session).get_by_user_id(uuid.UUID(str(user_id)))
        provider, api_key, model = resolve_provider_key_model(settings)
    except Exception:  # noqa: BLE001 - no AI configured: the rules' reading stands
        return None
    managed = workspace.current() is not None

    async def ask(prompt: str) -> str:
        raw, _tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=RECIPE_SYSTEM,
            prompt=prompt,
            max_tokens=2000,
            model=model,
        )
        return raw

    return ask, managed


# ── The choice ──────────────────────────────────────────────────────────────


async def read_spreadsheet(
    content: bytes,
    *,
    file_name: str,
    locale: str,
    overrides: dict[int, str] | None,
    recipe: ImportRecipe | None,
    session: AsyncSession | None,
    user_id: uuid.UUID | str | None,
    allow_ai: bool = True,
) -> ImportedBOQ:
    """Read an .xlsx or .xls bill the best way there is; see the module docstring.

    ``recipe`` is the preview's reading, sent back with the import; the
    person's ``overrides`` are laid over it. Without one, ``overrides`` are
    laid over the rules' reading, as they always were.

    Raises:
        ImporterParseError: the file cannot be read at all.
    """
    from app.modules.ai.ai_client import extract_json
    from app.modules.boq.ai_recipe import NoRecipe, write_recipe
    from app.modules.boq.importers.excel import ExcelImporter

    async def read(with_recipe: ImportRecipe) -> ImportedBOQ:
        return await ExcelImporter.parse(content, locale=locale, recipe=with_recipe)

    if recipe is not None:
        imported = await ExcelImporter.parse(content, locale=locale, column_mapping=overrides, recipe=recipe)
        return mark(imported, "person" if overrides else "preview")

    if session is not None and not overrides:
        try:
            saved = await _saved_reading(session, content, read)
        except Exception:  # noqa: BLE001 - a lookup that fails leaves the file to the other readings
            logger.warning("Could not look up a saved reading for %s", file_name, exc_info=True)
            saved = None
        if saved is not None:
            return saved

    rules = await ExcelImporter.parse(content, locale=locale, column_mapping=overrides)
    if overrides:
        return mark(rules, "rules")
    best = mark(rules, "rules")
    written = recipe_of_rules(rules)
    if written is not None:
        try:
            candidate = await read(written)
        except ImporterParseError:
            candidate = None
        if candidate is not None and (_check(candidate) or {}).get("ok"):
            if _better(candidate, rules):
                best = mark(candidate, "rules")
            elif abs(_sum(candidate) - _sum(rules)) < 0.01 and len(_lines(candidate)) == len(_lines(rules)):
                # The same bill either way: the rules' reading, with the
                # recipe the preview can edit and the check of its total.
                best = mark(rules, "rules", **{k: candidate.metadata["reading"][k] for k in ("recipe", "check")})

    if not allow_ai or session is None or not doubtful(best):
        return best
    ai = await workspace_ai(session, user_id)
    if ai is None:
        return best
    ask, managed = ai
    try:
        ai_recipe, ai_reading, calls = await write_recipe(
            content, filename=file_name, ask=ask, parse_json=extract_json, read=read
        )
    except NoRecipe:
        best.warnings.append(_ai_note("ai_layout_unread"))
        return best
    except Exception:  # noqa: BLE001 - the provider's failure; the rules' reading still stands
        logger.warning("The workspace AI could not read the layout of %s", file_name, exc_info=True)
        best.warnings.append(_ai_note("ai_layout_failed"))
        return best
    ai_check = _check(ai_reading) or {}
    if not ai_check.get("ok") and _lines(best):
        best.warnings.append(_ai_note("ai_layout_unread"))
        return best
    ai_reading.warnings.append(
        {
            "code": "layout_read_by_ai",
            "params": {"calls": calls},
            "severity": "info",
            "message": (
                "The headings of this file are not ones the importer knows, so the workspace AI worked out which "
                "rows and columns hold the bill. Check the columns in the preview."
            ),
        }
    )
    logger.info("Workspace AI read the layout of %s in %d calls (managed=%s)", file_name, calls, managed)
    return mark(ai_reading, "ai", ai_calls=calls)


def _ai_note(code: str) -> dict[str, Any]:
    messages = {
        "ai_layout_unread": (
            "The workspace AI was asked where the bill is in this file, but its answer did not read it better. "
            "The file was read by its headings; check the columns in the preview."
        ),
        "ai_layout_failed": (
            "The workspace AI could not be reached to work out this file's layout, so it was read by its "
            "headings. Check the columns in the preview."
        ),
    }
    return {"code": code, "params": {}, "severity": "warning", "message": messages[code]}


def recipe_field(value: str | None) -> ImportRecipe | None:
    """The ``recipe`` form field of an import, or ``None``. Raises ``ValueError`` when it is not a recipe."""
    from app.modules.boq.importers.recipe import parse_recipe

    if value is None or not value.strip():
        return None
    return parse_recipe(value)
