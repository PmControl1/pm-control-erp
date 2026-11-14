"""A КСС saved as PDF imports like the workbook it came from, or is read by the AI.

A PDF printed from Excel or an estimating program is a ruled table. It is read
cell by cell and handed to the spreadsheet reader, so it gets the Bulgarian
headings, the section numerals, the totals left out and the lev currency, and
nothing goes to an AI. A PDF with no ruled table is refused as ``pdf_no_table``
by that reader; the import route then has the workspace AI copy the bill out,
and its rows go through the same row reader.

The PDFs here are drawn with reportlab, in the font the app's own PDFs use.
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from typing import Any

import pytest

from app.modules.boq.importers import REGISTERED_IMPORTERS, ImportedBOQ
from app.modules.boq.importers._base import ImporterParseError
from app.modules.boq.importers.pdf_table import PdfTableImporter, has_bill

HEADING = ["№", "Шифър", "Наименование на СМР", "Мярка", "Количество", "Ед. цена (лв. без ДДС)", "Стойност (лв.)"]
BILL = [
    HEADING,
    ["1", "2", "3", "4", "5", "6", "7"],
    ["", "", "I. ЗЕМНИ РАБОТИ", "", "", "", ""],
    ["1", "02.01.01", "Изкоп с багер на транспорт", "м3", "1 250,00", "12,50", "15 625,00"],
    ["2", "", "Обратен насип", "куб.м", "85,50", "8,00", "684,00"],
    ["", "", "Общо за раздел I.", "", "", "", "16 309,00"],
    ["", "", "II. БЕТОНОВИ РАБОТИ", "", "", "", ""],
    ["3", "", "Кофраж за стени", "кв. м.", "340,50", "28,60", "9 738,30"],
    ["", "", "Общо за раздел II.", "", "", "", "9 738,30"],
    ["", "", "ОБЩО:", "", "", "", "26 047,30"],
    ["", "", "ДДС 20%", "", "", "", "5 209,46"],
]


def _font() -> str:
    from app.core.pdf_fonts import pdf_font, register_pdf_fonts

    if not register_pdf_fonts():
        pytest.skip("no Cyrillic PDF font in this environment")
    return pdf_font("Helvetica")


def _pdf(pages: list[list[list[str]]], *, ruled: bool = True) -> bytes:
    """A landscape A4 PDF with one table per page, ruled or as bare text."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import PageBreak, SimpleDocTemplate, Table, TableStyle

    font = _font()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
    story: list[Any] = []
    for number, rows in enumerate(pages):
        table = Table(rows, colWidths=[30, 60, 260, 50, 80, 120, 100])
        style = [("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 8)]
        if ruled:
            style.append(("GRID", (0, 0), (-1, -1), 0.5, colors.black))
        table.setStyle(TableStyle(style))
        story.append(table)
        if number < len(pages) - 1:
            story.append(PageBreak())
    doc.build(story)
    return buffer.getvalue()


def _parse(content: bytes) -> ImportedBOQ:
    return asyncio.run(PdfTableImporter.parse(content, locale="bg"))


def _work(result: ImportedBOQ) -> list[Any]:
    return [p for p in result.positions if not p.is_section]


# -- a ruled PDF -----------------------------------------------------------------


def test_a_pdf_is_claimed_by_its_header_not_its_name() -> None:
    assert PdfTableImporter in REGISTERED_IMPORTERS
    assert PdfTableImporter.detect(b"%PDF-1.7\n...", "kss.pdf")
    assert PdfTableImporter.detect(b"%PDF-1.4\n...", "kss")
    assert not PdfTableImporter.detect(b"PK\x03\x04", "kss.pdf")


def test_a_ruled_kss_pdf_reads_as_its_workbook_would() -> None:
    result = _parse(_pdf([BILL]))
    assert result.source_format == "pdf"
    assert result.currency == "BGN"
    assert [(p.ordinal, p.description) for p in result.positions if p.is_section] == [
        ("I", "I. ЗЕМНИ РАБОТИ"),
        ("II", "II. БЕТОНОВИ РАБОТИ"),
    ]
    assert [(p.ordinal, p.unit, p.quantity, p.unit_rate) for p in _work(result)] == [
        ("1", "м3", 1250.0, 12.5),
        ("2", "м3", 85.5, 8.0),
        ("3", "м2", 340.5, 28.6),
    ]
    assert _work(result)[0].classification == {"code": "02.01.01"}
    texts = " | ".join(p.description for p in result.positions).casefold()
    assert "общо" not in texts and "ддс" not in texts


def test_the_heading_repeated_on_every_page_is_read_once() -> None:
    first = BILL[:5]
    second = [HEADING, ["1", "2", "3", "4", "5", "6", "7"], *BILL[5:]]
    result = _parse(_pdf([first, second]))
    assert result.metadata["pdf_pages"] == 2
    assert [p.ordinal for p in _work(result)] == ["1", "2", "3"]
    assert not any("наименование" in p.description.casefold() for p in result.positions)


def test_a_heading_clipped_at_its_cell_edge_still_names_its_column() -> None:
    from app.modules.boq.importers.excel import normalise_label

    # A PDF cuts "Ед. цена (лв. без ДДС)" at the border of its cell.
    assert normalise_label("Ед. цена (лв. без Д") == "ед цена"
    clipped = [[cell.replace("(лв. без ДДС)", "(лв. без Д") for cell in row] for row in BILL]
    assert [p.unit_rate for p in _work(_parse(_pdf([clipped])))] == [12.5, 8.0, 28.6]


def test_a_pdf_without_a_ruled_table_is_refused_for_the_ai() -> None:
    with pytest.raises(ImporterParseError) as error:
        _parse(_pdf([BILL], ruled=False))
    assert error.value.code == "pdf_no_table"


def test_a_damaged_pdf_is_refused_in_words() -> None:
    with pytest.raises(ImporterParseError) as error:
        _parse(b"%PDF-1.7\nnot really a pdf")
    assert error.value.code == "pdf_unreadable"


# -- the AI reading --------------------------------------------------------------

AI_ROWS = {
    "currency": "BGN",
    "rows": [
        {"is_section": True, "ordinal": "", "description": "I. ЗЕМНИ РАБОТИ"},
        {
            "ordinal": "1",
            "code": "02.01.01",
            "description": "Изкоп с багер на транспорт",
            "unit": "куб.м",
            "quantity": 1250,
            "unit_rate": 12.5,
            "total": 15625,
        },
        {"ordinal": "", "description": "Общо за раздел I.", "unit": None, "quantity": None, "total": 15625},
        {"ordinal": "", "description": "Непредвидени разходи 10%", "total": 1562.5},
    ],
}


def test_the_ai_answer_becomes_rows_the_row_reader_knows() -> None:
    from app.modules.boq.ai_bill_reader import rows_from_answer
    from app.modules.boq.importers.excel import _rows_to_positions

    rows, currency = rows_from_answer(AI_ROWS)
    assert currency == "BGN"
    result = _rows_to_positions(rows, source="smart_import_ai", header_language="bg")
    assert [(p.ordinal, p.is_section) for p in result.positions] == [("I", True), ("1", False), ("2", False)]
    line, reserve = _work(result)
    assert (line.unit, line.quantity, line.unit_rate, line.classification) == ("м3", 1250.0, 12.5, {"code": "02.01.01"})
    assert (reserve.unit, reserve.unit_rate, reserve.metadata.get("contingency")) == ("сума", 1562.5, True)


def test_an_answer_naming_no_known_currency_names_none() -> None:
    from app.modules.boq.ai_bill_reader import rows_from_answer

    assert rows_from_answer({"currency": "USD", "rows": []}) == ([], "")
    assert rows_from_answer([{"description": "Изкоп", "quantity": 1}])[1] == ""


def test_long_text_is_sent_in_page_chunks_never_cut_inside_a_line() -> None:
    from app.modules.boq.ai_bill_reader import chunk_pages

    pages = ["\n".join(f"ред {n}" * 50 for n in range(20)) for _ in range(3)]
    chunks = chunk_pages(pages, limit=2000)
    assert len(chunks) > 3
    joined = "\n".join(text for _, text in chunks)
    assert joined.split("\n") == [line for page in pages for line in page.split("\n")]
    assert all(len(text) <= 2000 for _, text in chunks)


def test_the_ai_reads_every_chunk_and_a_bad_answer_stops_the_import() -> None:
    from app.modules.boq.ai_bill_reader import read_pdf_bill

    prompts: list[str] = []

    async def ask(prompt: str) -> str:
        prompts.append(prompt)
        return json.dumps(AI_ROWS, ensure_ascii=False)

    content = _pdf([BILL, BILL], ruled=False)
    rows, currency, facts = asyncio.run(read_pdf_bill(content, filename="kss.pdf", ask=ask, parse_json=json.loads))
    assert currency == "BGN" and facts["language"] == "bg" and facts["pages"] == 2
    assert len(prompts) == facts["ai_calls"] >= 1
    assert "Изкоп с багер" in prompts[0] and "UNTRUSTED_USER_CONTENT" in prompts[0]
    assert len(rows) == len(AI_ROWS["rows"]) * len(prompts)

    async def nonsense(prompt: str) -> str:
        return "Sorry, I cannot help with that."

    def strict(text: str) -> Any:
        try:
            return json.loads(text)
        except ValueError:
            return None

    from app.modules.boq.ai_bill_reader import UnreadableAnswer

    with pytest.raises(UnreadableAnswer, match="pages"):
        asyncio.run(read_pdf_bill(content, filename="kss.pdf", ask=nonsense, parse_json=strict))


def test_a_scan_is_refused_before_any_ai_call() -> None:
    from reportlab.pdfgen import canvas

    from app.modules.boq.ai_bill_reader import PdfHasNoText, read_pdf_bill

    buffer = io.BytesIO()
    page = canvas.Canvas(buffer)
    page.rect(50, 50, 200, 200, fill=1)
    page.save()

    async def ask(prompt: str) -> str:  # pragma: no cover - must not be called
        raise AssertionError("no text, no AI call")

    with pytest.raises(PdfHasNoText):
        asyncio.run(read_pdf_bill(buffer.getvalue(), filename="scan.pdf", ask=ask, parse_json=json.loads))


# -- the route ------------------------------------------------------------------


class _Service:
    def __init__(self) -> None:
        self.session = None

    async def get_boq(self, boq_id: uuid.UUID) -> Any:
        return type("Bill", (), {"project_id": uuid.uuid4()})()


def test_the_route_imports_an_ai_reading_like_a_spreadsheet(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.ai import ai_client
    from app.modules.boq import router

    async def call_ai(**kwargs: Any) -> tuple[str, int]:
        assert "never estimate" in kwargs["system"]
        return json.dumps(AI_ROWS, ensure_ascii=False), 10

    saved: list[ImportedBOQ] = []

    async def smart_native_result(boq_id: Any, imported: ImportedBOQ, *args: Any, **kwargs: Any) -> dict[str, Any]:
        saved.append(imported)
        return {"imported": len(imported.positions), "warnings": imported.warnings}

    monkeypatch.setattr(ai_client, "call_ai", call_ai)
    monkeypatch.setattr(router, "_smart_native_result", smart_native_result)
    result = asyncio.run(
        router._ai_pdf_import(
            uuid.uuid4(),
            _pdf([BILL], ruled=False),
            file_name="kss.pdf",
            provider="deepseek",
            api_key="k",
            model=None,
            workspace_managed=True,
            service=_Service(),  # type: ignore[arg-type]
            user_id=str(uuid.uuid4()),
        )
    )
    (bill,) = saved
    assert result["method"] == "ai" and result["model_used"] is None
    assert bill.currency == "BGN" and bill.source_format == "pdf" and bill.metadata["read_by"] == "ai"
    assert [p.ordinal for p in bill.positions] == ["I", "1", "2"]
    assert all(p.source == "smart_import_ai" for p in bill.positions)
    assert "read_by_ai" in [w.get("code") for w in bill.warnings]


def test_a_ruled_pdf_never_reaches_the_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.boq import router

    native = asyncio.run(router._native_pdf_import(_pdf([BILL])))
    assert native is not None and has_bill(native)
    assert asyncio.run(router._native_pdf_import(_pdf([BILL], ruled=False))) is None
    assert asyncio.run(router._pdf_has_table_bill(_pdf([BILL]), None))
    assert not asyncio.run(router._pdf_has_table_bill(_pdf([BILL], ruled=False), None))
