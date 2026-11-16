# PM Project Management - an import recipe: how one spreadsheet layout is read.
# Licensed under the GNU AGPL v3.0 or later, like the rest of this program.
"""An import recipe says where a bill is in a workbook and what each column holds.

Bills come in every layout: a КСС with "Ед. цена (лв.)", a running КСС with
progress columns, a check list with no heading row, a budget form whose
description column is headed "Етап на изграждането". Heading rules read the
layouts they were written for and misread the rest. A recipe is the reading
written down: which sheets, which row heads them, which rows are the bill,
which column is the description, unit, quantity, unit price and value, and
which cell holds the file's own total.

A recipe is data, never code. The workspace AI may write one
(:mod:`app.modules.boq.ai_recipe`), a person may correct one in the import
preview, and one is kept for every layout imported with it
(:class:`~app.modules.boq.models.BOQImportRecipe`); whoever wrote it, the
importer's own code carries it out (``ExcelImporter.parse(recipe=...)``), so
a cell in an uploaded file can never become something the server runs.

:func:`check_reading` then holds the reading against the file: quantity times
unit price against the value written on each line, and the values against
the file's total. A recipe whose values do not add up to that total is
wrong, whoever wrote it.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# The fields a column can hold, in the order a bill lists them. ``code`` is the
# шифър / price-norm code, read into the line's classification.
FIELDS: tuple[str, ...] = ("ordinal", "code", "description", "unit", "quantity", "unit_rate", "total")
# What the spreadsheet reader calls each field.
CANONICAL: dict[str, str] = {
    "ordinal": "ordinal",
    "code": "classification",
    "description": "description",
    "unit": "unit",
    "quantity": "quantity",
    "unit_rate": "unit_rate",
    "total": "total",
}
_LETTERS = re.compile(r"^[A-Z]{1,3}$")
# The widest workbook a recipe addresses (Excel's own limit).
_MAX_COLUMN = 16384


def column_index(letters: str) -> int:
    """``"A"`` -> 0, ``"AB"`` -> 27."""
    index = 0
    for letter in letters:
        index = index * 26 + (ord(letter) - 64)
    return index - 1


def column_letters(index: int) -> str:
    """0 -> ``"A"``, 27 -> ``"AB"``."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _letter(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().upper()
    if not _LETTERS.match(text) or column_index(text) >= _MAX_COLUMN:
        raise ValueError(f"{value!r} is not a column letter")
    return text


class RecipeColumns(BaseModel):
    """Which column holds which field. A field the sheet does not have is ``None``."""

    model_config = ConfigDict(extra="ignore")

    ordinal: str | None = None
    code: str | None = None
    description: str
    unit: str | None = None
    quantity: str | None = None
    unit_rate: str | None = None
    total: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _letters(cls, value: Any) -> str | None:
        return _letter(value)

    @model_validator(mode="after")
    def _a_column_holds_one_field(self) -> RecipeColumns:
        used = [letter for letter in self.as_dict().values()]
        if len(used) != len(set(used)):
            raise ValueError("a column can hold only one field")
        if not (self.quantity or self.unit or self.unit_rate or self.total):
            raise ValueError("a bill needs a unit, quantity, unit price or value column")
        return self

    def as_dict(self) -> dict[str, str]:
        """``{field: letter}`` for the fields the sheet has."""
        return {field: letter for field in FIELDS if (letter := getattr(self, field))}


class FileTotal(BaseModel):
    """The cell holding the file's own total of the bill, before ДДС."""

    model_config = ConfigDict(extra="ignore")

    row: int = Field(ge=1)
    column: str

    @field_validator("column", mode="before")
    @classmethod
    def _letters(cls, value: Any) -> str:
        letter = _letter(value)
        if letter is None:
            raise ValueError("a total cell needs its column")
        return letter


class RecipeSheet(BaseModel):
    """One sheet of the bill: its heading row (``None`` when it has none), its rows and its columns."""

    model_config = ConfigDict(extra="ignore")

    sheet: str = Field(min_length=1, max_length=200)
    header_row: int | None = Field(default=None, ge=1)
    first_row: int = Field(ge=1)
    last_row: int | None = Field(default=None, ge=1)
    columns: RecipeColumns
    file_total: FileTotal | None = None

    @model_validator(mode="after")
    def _rows_in_order(self) -> RecipeSheet:
        if self.header_row is not None and self.header_row >= self.first_row:
            raise ValueError("the bill starts below its heading row")
        if self.last_row is not None and self.last_row < self.first_row:
            raise ValueError("the bill ends after it starts")
        return self


class ImportRecipe(BaseModel):
    """How a workbook's bill is read. See the module docstring."""

    model_config = ConfigDict(extra="ignore")

    version: Literal[1] = 1
    sheets: list[RecipeSheet] = Field(min_length=1, max_length=30)
    # The currency of the unit price and value columns: "" when the file does not say.
    currency: Literal["BGN", "EUR", ""] = ""
    prices_include_vat: bool = False
    notes: str = Field(default="", max_length=600)
    # Who worked the recipe out: the heading rules, the workspace AI or a
    # person choosing columns in the preview. Set by the server, so a recipe
    # sent back with an import is kept (or not) as what it came from.
    origin: Literal["", "rules", "ai", "person"] = ""

    @field_validator("currency", mode="before")
    @classmethod
    def _currency(cls, value: Any) -> str:
        text = str(value or "").strip().upper()
        return {"ЛВ": "BGN", "ЛВ.": "BGN", "ЛЕВА": "BGN", "BGL": "BGN", "€": "EUR", "ЕВРО": "EUR"}.get(text, text)

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)

    def with_columns(self, overrides: dict[int, str]) -> ImportRecipe:
        """The recipe with the person's column choices from the preview laid over its first sheet.

        ``overrides`` is ``{column index: field}`` as the preview sends it,
        ``""`` leaving a column out. A field moved to another column leaves
        the one it was in.
        """
        if not overrides:
            return self
        first = self.sheets[0]
        letters = first.columns.as_dict()
        by_canonical = {canonical: field for field, canonical in CANONICAL.items()}
        for index, target in overrides.items():
            letter = column_letters(int(index))
            for field, current in list(letters.items()):
                if current == letter:
                    del letters[field]
            field = by_canonical.get(target, target) if target else ""
            if field in FIELDS:
                letters[field] = letter
        columns = RecipeColumns(**letters)
        sheets = [first.model_copy(update={"columns": columns}), *self.sheets[1:]]
        return self.model_copy(update={"sheets": sheets, "origin": "person"})


def parse_recipe(text: str | dict[str, Any] | None) -> ImportRecipe | None:
    """A recipe from its JSON (or the dict of it); ``None`` for nothing. Raises ``ValueError`` when malformed."""
    if text in (None, ""):
        return None
    data = json.loads(text) if isinstance(text, str) else text
    try:
        return ImportRecipe.model_validate(data)
    except Exception as exc:  # pydantic's error names each wrong field
        raise ValueError(str(exc)) from exc


# ── Which layout a recipe is for ────────────────────────────────────────────


def _cell_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value if value is not None else "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _header_cells(workbook: Any, sheet: RecipeSheet) -> tuple[Any, ...]:
    if sheet.header_row is None:
        return ()
    rows = workbook[sheet.sheet].iter_rows(min_row=sheet.header_row, max_row=sheet.header_row, values_only=True)
    return next(iter(rows), ())


def layout_key(workbook: Any, recipe: ImportRecipe) -> str | None:
    """The layout ``recipe`` reads, as it appears in ``workbook``: its sheets and their headings.

    Two files of one layout (the same form filled in for another site, next
    month's КСС from the same contractor) have the same key, and a file of
    another layout does not. A sheet read without a heading row is known by
    its name and the columns read off it. ``None`` when the workbook lacks a
    sheet of the recipe.
    """
    parts: list[Any] = []
    for sheet in recipe.sheets:
        if sheet.sheet not in workbook.sheetnames:
            return None
        if sheet.header_row is not None:
            header = [_cell_key(cell) for cell in _header_cells(workbook, sheet)]
            while header and not header[-1]:
                header.pop()
            parts.append([sheet.sheet, sheet.header_row, header])
        else:
            parts.append([sheet.sheet, None, sorted(sheet.columns.as_dict().items())])
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


# ── Reading a workbook with a recipe ────────────────────────────────────────

_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)
# Rows after the bill looked through for its total, when the recipe names no total cell.
_TOTAL_SEARCH_ROWS = 40
_LETTERS_IN = re.compile(r"[^\W\d_]")


def _number_cell(value: Any) -> tuple[float | None, str | None]:
    """A number cell as ``(number, text)``: the number it holds, and its text when that says more.

    ``"35 лв/бр."`` is ``(35.0, "35 лв/бр.")``: the price, and the words
    beside it, which go into the line's note. A cell with no number in it
    (``"без ДДС"``) is ``(None, its text)``; an empty cell ``(None, None)``.
    """
    from app.modules.boq.importers._encoding import parse_numeric_cell

    if value is None or isinstance(value, bool):
        return None, None
    if isinstance(value, (int, float)):
        number = float(value)
        return (number, None) if number == number and abs(number) != float("inf") else (None, None)
    text = str(value).strip()
    if not text:
        return None, None
    number, error = parse_numeric_cell(text)
    if error is not None or number is None:
        return None, text
    return float(number), (text if _LETTERS_IN.search(text) else None)


def _money(value: float, language: str | None) -> str:
    whole = f"{value:,.2f}"
    return whole.replace(",", " ").replace(".", ",") if language == "bg" else whole


_NOTES = {
    "value_only": {
        "bg": "Във файла редът има само стойност; внесен е като сума (1 × стойността).",
        "en": "The file gives only a value for this line; it was imported as a lump sum (1 × the value).",
    },
    "source_unit": {"bg": "Мярка във файла: {unit}.", "en": "Unit in the file: {unit}."},
    "rate_text": {"bg": "Ед. цена във файла: „{text}“.", "en": "Unit price in the file: '{text}'."},
    "quantity_text": {"bg": "Количество във файла: „{text}“.", "en": "Quantity in the file: '{text}'."},
    "rate_from_value": {
        "bg": "Ед. цена не е дадена във файла; изчислена е от стойността ({value}) / количеството.",
        "en": "The file gives no unit price; it was worked out as the value ({value}) / the quantity.",
    },
    "no_description": {
        "bg": "Редът няма описание във файла (ред {row}).",
        "en": "The line has no description in the file (row {row}).",
    },
    "value_differs": {
        "bg": "Стойност във файла: {value}; количество × ед. цена = {computed}.",
        "en": "Value in the file: {value}; quantity × unit price = {computed}.",
    },
}


def note(key: str, language: str | None, **params: Any) -> str:
    """The line note ``key`` in the bill's language (Bulgarian or English)."""
    words = _NOTES[key]["bg" if language == "bg" else "en"]
    return words.format(**params)


def _line_value(row: dict[str, Any]) -> float:
    if row.get("total") is not None:
        return float(row["total"])
    if row.get("quantity") is not None and row.get("unit_rate") is not None:
        return float(row["quantity"]) * float(row["unit_rate"])
    return 0.0


def _heads_its_lines(rows: list[dict[str, Any]], index: int, candidates: set[int]) -> bool:
    """Whether the value on the heading at ``index`` is the sum of the lines under it.

    A КСС writes each section's subtotal on its heading row ("ЗЕМНИ
    РАБОТИ ... 18 261,60"). Read as a line, that subtotal would count the
    section twice. The lines following it are added up, past the headings
    of its subsections, until they reach its value or pass it.
    """
    target = float(rows[index]["total"])
    tolerance = max(0.05, abs(target) * 1e-6)
    running = 0.0
    for later in range(index + 1, len(rows)):
        if later in candidates:
            continue
        running += _line_value(rows[later])
        if abs(running - target) <= tolerance:
            return True
        if running > target + tolerance:
            return False
    return False


def _settle_values(rows: list[dict[str, Any]], numbers: list[int], language: str | None) -> dict[str, int]:
    """Make each row read as the bill means it, in place; returns how many of each kind there were.

    * A number cell holding words ("35 лв/бр.") keeps its number, and the
      words go into the line's note; one with no number is left empty.
    * A heading whose value is the sum of the lines under it is a heading:
      its value is the subtotal, not a line.
    * A line with a value but no quantity is a lump sum: "сума", 1 × the
      value, with the unit the file wrote kept in its note.
    * A line with a quantity and a value but no unit price gets the price the
      two imply, and says so.
    * A line with a value but no description is kept, named by its row, so
      the bill still adds up to the file's total.

    Every line remembers the value the file wrote (``source_value``), which
    :func:`apply_checks` holds its quantity times unit price against.
    """
    from app.modules.boq.units import is_lump_sum_unit

    lump_sum = "сума" if language == "bg" else "lsum"
    counts = {"value_only": 0, "rate_from_value": 0, "no_description": 0, "section_subtotals": 0}
    for row in rows:
        notes: list[str] = row.setdefault("_notes", [])
        for field in ("quantity", "unit_rate", "total"):
            if field not in row:
                continue
            number, text = _number_cell(row[field])
            if number is None:
                row.pop(field)
            else:
                row[field] = number
            if text and field in ("quantity", "unit_rate"):
                notes.append(note("quantity_text" if field == "quantity" else "rate_text", language, text=text))

    def unit_of(row: dict[str, Any]) -> str:
        return str(row.get("unit") or "").strip()

    # Total, tax and recap rows, and the contingency line, are left as the
    # file has them: the row reader reports the first and prices the second.
    from app.modules.boq.importers.excel import _contingency_amount, partition_summary_rows

    _kept, summary = partition_summary_rows(rows, row_numbers=numbers)
    contingencies = {
        number
        for row, number in zip(rows, numbers, strict=True)
        if _contingency_amount(row, str(row.get("description") or "")) is not None
    }
    left_alone = {report["row"] for report in summary} | contingencies

    candidates = {
        index
        for index, row in enumerate(rows)
        if numbers[index] not in left_alone
        and not unit_of(row)
        and row.get("quantity") in (None, 0.0)
        and row.get("unit_rate") in (None, 0.0)
        and (row.get("total") or 0.0) > 0
    }
    for index in sorted(candidates):
        row = rows[index]
        if str(row.get("description") or "").strip() and _heads_its_lines(rows, index, candidates):
            row.pop("total")
            row.pop("quantity", None)
            row.pop("unit_rate", None)
            counts["section_subtotals"] += 1

    for row, number in zip(rows, numbers, strict=True):
        if number in contingencies:
            row.setdefault("_meta", {})["source_value"] = round(float(row["total"]), 6)
        if number in left_alone:
            continue
        notes = row["_notes"]
        meta: dict[str, Any] = row.setdefault("_meta", {})
        value = row.get("total")
        quantity = row.get("quantity")
        rate = row.get("unit_rate")
        unit = unit_of(row)
        if value is not None:
            meta["source_value"] = round(value, 6)
        described = bool(str(row.get("description") or "").strip())
        if not described and (value or (quantity and rate)):
            row["description"] = (
                f"(ред {number} без описание)" if language == "bg" else f"(row {number}, no description)"
            )
            meta["no_description"] = True
            notes.append(note("no_description", language, row=number))
            counts["no_description"] += 1
        if value and not quantity:
            # A value and no quantity (or a quantity of nought): the line is the value.
            if unit and not is_lump_sum_unit(unit):
                meta["source_unit"] = unit
                notes.append(note("source_unit", language, unit=unit))
            if rate and abs(rate - value) > 0.005:
                notes.append(note("rate_text", language, text=_money(rate, language)))
            row["unit"] = lump_sum if not unit or not is_lump_sum_unit(unit) else unit
            row["quantity"] = 1.0
            row["unit_rate"] = value
            meta["amount_only"] = True
            notes.insert(0, note("value_only", language))
            counts["value_only"] += 1
        elif value and quantity and rate is None:
            row["unit_rate"] = value / quantity
            meta["rate_from_value"] = True
            notes.append(note("rate_from_value", language, value=_money(value, language)))
            counts["rate_from_value"] += 1
        elif rate and quantity is None and unit and is_lump_sum_unit(unit):
            row["quantity"] = 1.0
    return counts


def read_rows(content: bytes, recipe: ImportRecipe) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read a workbook's bill the way ``recipe`` says: ``(rows, import metadata)``.

    The rows are what :func:`~app.modules.boq.importers.excel._rows_to_positions`
    reads, in the shape the heading reader gives it, so a recipe's bill goes
    through the same sections, numbering, units and checks as any other.

    Raises:
        ImporterParseError: the workbook has no sheet the recipe names.
    """
    from app.modules.boq.importers._base import ImporterParseError
    from app.modules.boq.importers._workbook import open_workbook
    from app.modules.boq.importers.bulgaria_kss import workbook_currency
    from app.modules.boq.importers.excel import _join_sheets, _report_mapping, header_language

    workbook = open_workbook(content)
    try:
        read: list[dict[str, Any]] = []
        file_total: float | None = None
        candidates: list[dict[str, Any]] = []
        price_headings: list[list[Any]] = []
        for sheet in recipe.sheets:
            if sheet.sheet not in workbook.sheetnames:
                raise ImporterParseError(
                    f"The workbook has no sheet {sheet.sheet!r}, which the reading names.",
                    code="recipe_sheet_missing",
                    params={"sheet": sheet.sheet},
                )
            worksheet = workbook[sheet.sheet]
            letters = sheet.columns.as_dict()
            column_map = {column_index(letter): CANONICAL[field] for field, letter in letters.items()}
            ends = [sheet.last_row, sheet.file_total.row if sheet.file_total else None]
            end = None if sheet.last_row is None else max(row for row in ends if row is not None)
            # With no total cell named, the rows after the bill are looked
            # through for one: the first value there that the lines add up to.
            look_for_total = sheet.file_total is None and sheet.last_row is not None and "total" in letters
            if look_for_total and end is not None:
                end += _TOTAL_SEARCH_ROWS
            header: tuple[Any, ...] = ()
            rows: list[dict[str, Any]] = []
            numbers: list[int] = []
            total_cell: Any = None
            for number, raw in enumerate(worksheet.iter_rows(min_row=1, max_row=end, values_only=True), start=1):
                if number == sheet.header_row:
                    header = tuple(raw)
                if sheet.file_total is not None and number == sheet.file_total.row:
                    index = column_index(sheet.file_total.column)
                    total_cell = raw[index] if index < len(raw) else None
                if look_for_total and sheet.last_row is not None and number > sheet.last_row:
                    index = column_index(letters["total"])
                    amount, _text = _number_cell(raw[index] if index < len(raw) else None)
                    if amount:
                        candidates.append(
                            {"sheet": worksheet.title, "row": number, "column": letters["total"], "value": amount}
                        )
                if number < sheet.first_row or (sheet.last_row is not None and number > sheet.last_row):
                    continue
                row: dict[str, Any] = {}
                for index, canonical in column_map.items():
                    value = raw[index] if index < len(raw) else None
                    if value is None or (isinstance(value, str) and not value.strip()):
                        continue
                    row[canonical] = value
                if row:
                    rows.append(row)
                    numbers.append(number)
            if sheet.file_total is not None:
                amount, _text = _number_cell(total_cell)
                if amount is not None:
                    file_total = (file_total or 0.0) + amount
            price_headings.append(
                [
                    header[column_index(letter)] if column_index(letter) < len(header) else None
                    for field, letter in letters.items()
                    if field in ("unit_rate", "total")
                ]
            )
            width = max([len(header), *(index + 1 for index in column_map)])
            read.append(
                {
                    "title": worksheet.title,
                    "rows": rows,
                    "row_numbers": numbers,
                    "header_row": sheet.header_row or sheet.first_row,
                    "headers": header,
                    "column_map": column_map,
                    "original_columns": [
                        str(header[index]).strip()
                        if index < len(header) and header[index] is not None
                        else column_letters(index)
                        for index in range(width)
                    ],
                }
            )
    finally:
        workbook.close()

    first = read[0]
    language = next((lang for sheet in read if (lang := header_language(sheet["headers"]))), None)
    if language is None:
        texts = [str(row.get("description") or "") for sheet in read for row in sheet["rows"][:200]]
        if texts and sum(1 for text in texts if _CYRILLIC.search(text)) * 2 >= len(texts):
            # A sheet without a heading row says its language only in its lines.
            language = "bg"
    counts = {"value_only": 0, "rate_from_value": 0, "no_description": 0, "section_subtotals": 0}
    for sheet in read:
        for key, count in _settle_values(sheet["rows"], sheet["row_numbers"], language).items():
            counts[key] += count
    if len(read) == 1:
        rows, row_numbers = first["rows"], first["row_numbers"]
        row_sheets = [first["title"]] * len(rows)
    else:
        rows, row_numbers, row_sheets = _join_sheets(read)

    currency = recipe.currency
    if not currency and language == "bg":
        currency = workbook_currency([headings for headings in price_headings if any(headings)])
    meta: dict[str, Any] = {
        "original_columns": first["original_columns"],
        "header_row": recipe.sheets[0].header_row,
        "column_mapping": _report_mapping(first["column_map"]),
        "column_mapping_applied": False,
        "mapping_notes": [],
        "header_language": language,
        "bg_currency": currency if language == "bg" else None,
        "currency": currency,
        "header_report": None,
        "sheet_names": [sheet["title"] for sheet in read],
        "item_sheet": first["title"],
        "item_sheets": [sheet["title"] for sheet in read],
        "inferred_columns": [],
        "sheet_notes": [],
        "total_rows": len(rows),
        "row_numbers": row_numbers,
        "row_sheets": row_sheets,
        "file_total": file_total,
        "total_candidates": candidates if len(recipe.sheets) == 1 else [],
        "value_counts": counts,
    }
    return rows, meta


# ── Holding a reading against the file ──────────────────────────────────────


def _tolerance(amount: float) -> float:
    return max(1.0, abs(amount) * 0.0005)


def apply_checks(
    imported: Any,
    recipe: ImportRecipe,
    file_total: float | None,
    language: str | None,
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Hold a recipe's reading against the file, flag what disagrees and say how it stands.

    * ``values_sum`` is what the file writes in its value column on the
      lines read, ``file_total`` the file's own total cell, and
      ``total_matches`` whether the two agree: a recipe reading the wrong
      rows or the wrong column does not.
    * ``imported_sum`` is quantity times unit price over the lines as
      imported. It differs from ``values_sum`` by the ``mismatches``, lines
      whose written value is not their quantity times their unit price.
      Those are imported as written, each with a warning and a note, and
      never corrected.

    With no total cell in the recipe, ``candidates`` (the values below the
    bill in its value column) are looked through for the total: the first
    the lines add up to is taken as it, and named in ``file_total_cell``.

    Amounts are in the file's currency, before any conversion into the
    project's. The result is also kept in ``imported.metadata["reading"]``.
    """
    lines = [position for position in imported.positions if not position.is_section]
    values_sum = 0.0
    has_values = False
    imported_sum = 0.0
    mismatches: list[dict[str, Any]] = []
    for position in lines:
        meta = position.metadata if position.metadata is not None else {}
        amount = float(position.quantity) * float(position.unit_rate)
        imported_sum += amount
        written = meta.get("source_value")
        if written is None:
            continue
        has_values = True
        values_sum += float(written)
        if abs(amount - float(written)) > max(0.05, abs(float(written)) * 0.0005):
            row = meta.get("import_row_index")
            difference = round(float(written) - amount, 2)
            mismatches.append(
                {
                    "row": row,
                    "sheet": meta.get("import_sheet"),
                    "ordinal": position.ordinal,
                    "value": round(float(written), 2),
                    "computed": round(amount, 2),
                    "difference": difference,
                }
            )
            text = note(
                "value_differs", language, value=_money(float(written), language), computed=_money(amount, language)
            )
            meta["value_differs"] = difference
            meta["comment"] = f"{meta['comment']} {text}" if meta.get("comment") else text
            position.metadata = meta
            imported.warnings.append(
                {
                    "row": row,
                    "ordinal": position.ordinal,
                    "code": "value_differs",
                    "params": {
                        "row": row,
                        "value": round(float(written), 2),
                        "computed": round(amount, 2),
                        "difference": difference,
                    },
                    "severity": "warning",
                    "message": (
                        f"Row {row}: the file gives the value {float(written):,.2f}, but its quantity times its "
                        f"unit price is {amount:,.2f}. Imported as written; check the line."
                    ),
                    **({"sheet": meta["import_sheet"]} if meta.get("import_sheet") else {}),
                }
            )
    compared = values_sum if has_values else imported_sum
    total_cell: str | None = None
    if file_total is None:
        found = next((c for c in candidates or () if abs(compared - c["value"]) <= _tolerance(c["value"])), None)
        if found is not None:
            file_total, total_cell = float(found["value"]), f"{found['column']}{found['row']}"
    else:
        named = next((s for s in recipe.sheets if s.file_total is not None), None)
        if named is not None and named.file_total is not None:
            total_cell = f"{named.file_total.column}{named.file_total.row}"
    total_matches = None if file_total is None else abs(compared - file_total) <= _tolerance(file_total)
    check = {
        "lines": len(lines),
        "priced": sum(1 for position in lines if position.unit_rate),
        "value_only": sum(1 for position in lines if (position.metadata or {}).get("amount_only")),
        "values_sum": round(values_sum, 2) if has_values else None,
        "imported_sum": round(imported_sum, 2),
        "file_total": round(file_total, 2) if file_total is not None else None,
        "file_total_cell": total_cell,
        "total_matches": total_matches,
        "mismatches": mismatches[:50],
        "mismatch_count": len(mismatches),
        "currency": imported.currency or recipe.currency,
    }
    check["ok"] = bool(lines) and total_matches is not False
    if total_matches is False:
        imported.warnings.append(
            {
                "code": "file_total_differs",
                "params": {"sum": round(compared, 2), "total": round(file_total or 0.0, 2)},
                "severity": "warning",
                "message": (
                    f"The lines read add up to {compared:,.2f}, but the file's total is {file_total:,.2f}. "
                    "Check which rows and columns were read."
                ),
            }
        )
    return check


def check_problems(check: dict[str, Any], recipe: ImportRecipe) -> list[str]:
    """What is wrong with a reading, in words an AI can correct its recipe from; empty when nothing."""
    problems: list[str] = []
    if not check["lines"]:
        problems.append("No line of the bill was read: no row in the bill rows has a description and a unit or number.")
    if check["total_matches"] is False:
        sheet = next(s for s in recipe.sheets if s.file_total is not None)
        assert sheet.file_total is not None
        got = check["values_sum"] if check["values_sum"] is not None else check["imported_sum"]
        problems.append(
            f"The values of the lines read add up to {got:,.2f}, but the total cell "
            f"{sheet.file_total.column}{sheet.file_total.row} on sheet {sheet.sheet!r} holds "
            f"{check['file_total']:,.2f}. Rows are missing or counted twice, or a column is the wrong one."
        )
    columns = recipe.sheets[0].columns
    if check["lines"] and not check["priced"] and (columns.unit_rate or columns.total):
        problems.append("A unit price or value column is named, but no line got a price from it.")
    return problems
