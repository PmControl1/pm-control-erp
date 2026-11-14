# PM Project Management - a bill printed to PDF, read as the table it was printed from.
# Licensed under the GNU AGPL v3.0 or later, like the rest of this program.
"""A КСС (or any bill) saved as PDF from Excel or an estimating program.

Such a PDF is a ruled table: the cell borders are lines in the page, and
``pdfplumber`` reads the cells back between them. The rows go through the
spreadsheet reader unchanged (:class:`~.excel.ExcelImporter`), so a PDF bill
gets exactly what its workbook would: the Bulgarian headings, sections and
their numerals, summary rows left out, units folded, the currency read from
the price headings and a lev bill converted to euro by the route.

A PDF without ruled cells (printed without borders, or scanned) has no table
this can read without guessing at columns. That raises ``pdf_no_table``, and
the import route hands the file to the workspace AI instead. A guess at
columns would put a шифър into the № or a rate into the quantity without a
word, which is worse than asking.

Nothing here leaves the server.
"""

from __future__ import annotations

import asyncio
import io
import re
from typing import Any, ClassVar

from app.modules.boq.importers._base import ImportedBOQ, ImporterParseError

# Rows of the first table that later pages repeat on top: the heading and the
# row of column numbers, printed on every page as print titles.
_REPEATED_TITLE_ROWS = 3


def _cell(value: Any) -> str:
    """One cell as one line: a wrapped description is one description."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _signature(row: list[str]) -> tuple[str, ...]:
    return tuple(cell.casefold() for cell in row)


def pdf_table_rows(content: bytes) -> tuple[list[list[str]], int]:
    """Every row of every ruled table in the PDF, in page order, and the page count.

    The heading rows a later page repeats at its top are dropped, so a
    forty-page bill has one heading, not forty lines called "Наименование".
    """
    import pdfplumber

    rows: list[list[str]] = []
    titles: set[tuple[str, ...]] | None = None
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        pages = len(pdf.pages)
        for page in pdf.pages:
            for table in page.extract_tables():
                cleaned = [[_cell(cell) for cell in row] for row in table]
                cleaned = [row for row in cleaned if any(row)]
                if not cleaned:
                    continue
                if titles is None:
                    titles = {_signature(row) for row in cleaned[:_REPEATED_TITLE_ROWS]}
                else:
                    while cleaned and _signature(cleaned[0]) in titles:
                        cleaned.pop(0)
                rows.extend(cleaned)
    return rows, pages


def _as_workbook(rows: list[list[str]]) -> bytes:
    """The rows as a one-sheet workbook, every cell kept as the text printed."""
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "PDF"
    width = max(len(row) for row in rows)
    for row in rows:
        sheet.append(row + [""] * (width - len(row)))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class PdfTableImporter:
    """A bill printed to PDF with ruled cells, read through the spreadsheet reader."""

    format_id: ClassVar[str] = "pdf_table"
    extensions: ClassVar[tuple[str, ...]] = (".pdf",)
    display_name: ClassVar[str] = "PDF bill (ruled table)"
    rule_packs: ClassVar[tuple[str, ...]] = ("boq_quality",)

    @classmethod
    def detect(cls, head_bytes: bytes, filename: str) -> bool:
        return head_bytes.lstrip()[:5] == b"%PDF-"

    @classmethod
    async def parse(
        cls,
        content: bytes,
        *,
        locale: str = "en",
        column_mapping: dict[int, str] | None = None,
    ) -> ImportedBOQ:
        from app.modules.boq.importers.excel import ExcelImporter

        try:
            rows, pages = await asyncio.to_thread(pdf_table_rows, content)
        except Exception as exc:  # noqa: BLE001 - a PDF pdfplumber cannot open
            raise ImporterParseError(
                "The PDF could not be opened. It may be damaged or password-protected.",
                code="pdf_unreadable",
            ) from exc
        if not rows:
            raise ImporterParseError(
                "The PDF has no table with ruled cells to read (it may be scanned or printed "
                "without borders). It can be read with the workspace AI instead.",
                code="pdf_no_table",
                params={"pages": pages},
            )
        workbook = await asyncio.to_thread(_as_workbook, rows)
        result = await ExcelImporter.parse(workbook, locale=locale, column_mapping=column_mapping)
        result.source_format = "pdf"
        result.metadata = {**(result.metadata or {}), "pdf_pages": pages, "pdf_table_rows": len(rows)}
        return result


def has_bill(result: ImportedBOQ) -> bool:
    """Whether a reading found any line of work, not only headings."""
    return any(not position.is_section for position in result.positions)
