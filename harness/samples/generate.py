"""Build the synthetic edge-case pack: what real public samples cannot cover.

  python3 harness/samples/generate.py [--tier pr|nightly]   (nightly includes pr)

Bulgarian office documents and drawings, file names that break naive code,
broken and hostile files, a 40-file batch and, in the nightly tier, files
near and over the proxy's 500 MB upload limit. All content is invented.

Writes harness/.samples/generated/<id>/<name> and harness/.samples/generated.json.

Each entry's "expect" says what the app must do with the file:
  accepted  upload succeeds and the file downloads back byte for byte
  rejected  upload is refused with a readable message (4xx), never a 5xx
  either    accepted or refused with a readable message, never a 5xx
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import zipfile
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / ".samples" / "generated"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

rng = random.Random(20261116)
entries: list[dict] = []


def emit(
    id: str,
    name: str,
    data: bytes,
    *,
    kind: str,
    tier: str = "pr",
    expect: str = "accepted",
    notes: str = "",
    upload_name: str | None = None,
) -> None:
    """Write one file. upload_name: the name to upload it under when the disk
    here cannot hold it (Linux allows 255 bytes per name; Windows allows 255
    characters, which is up to 510 bytes of Cyrillic)."""
    folder = OUT / id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    entries.append(
        {
            "id": id,
            "name": upload_name or name,
            "kind": kind,
            "tier": tier,
            "path": str(path),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "expect": expect,
            "generated": True,
            **({"notes": notes} if notes else {}),
        }
    )


def emit_big(id: str, name: str, size: int, *, tier: str, expect: str, notes: str) -> None:
    """A stored (uncompressed) ZIP of random bytes, written in chunks."""
    folder = OUT / id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    digest = hashlib.sha256()
    chunk = 8 * 1024 * 1024
    with (
        zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf,
        zf.open("данни.bin", "w", force_zip64=True) as member,
    ):
        remaining = size
        while remaining > 0:
            block = rng.randbytes(min(chunk, remaining))
            member.write(block)
            remaining -= len(block)
    data_size = path.stat().st_size
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    entries.append(
        {
            "id": id,
            "name": name,
            "kind": "zip",
            "tier": tier,
            "path": str(path),
            "bytes": data_size,
            "sha256": digest.hexdigest(),
            "expect": expect,
            "generated": True,
            "notes": notes,
        }
    )


# ── PDFs ─────────────────────────────────────────────────────────────────────


def _canvas(buf: io.BytesIO, pagesize):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    if "DejaVu" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVu", FONT))
    return canvas.Canvas(buf, pagesize=pagesize, invariant=1)


def text_pdf(title: str, lines: list[str], pages: int = 1) -> bytes:
    from reportlab.lib.pagesizes import A4

    buf = io.BytesIO()
    c = _canvas(buf, A4)
    c.setTitle(title)
    for page in range(1, pages + 1):
        c.setFont("DejaVu", 14)
        c.drawString(50, 790, title)
        c.setFont("DejaVu", 10)
        y = 760
        for line in lines:
            c.drawString(50, y, line)
            y -= 16
        c.drawString(50, 40, f"Страница {page} от {pages}")
        c.showPage()
    c.save()
    return buf.getvalue()


def drawing_pdf() -> bytes:
    """A1 landscape floor plan: walls, a grid, dimensions and a title block."""
    from reportlab.lib.pagesizes import A1, landscape

    w, h = landscape(A1)
    buf = io.BytesIO()
    c = _canvas(buf, (w, h))
    c.setTitle("Разпределение партер")
    c.setLineWidth(0.25)
    for i, x in enumerate(range(100, int(w) - 300, 180)):
        c.line(x, 80, x, h - 80)
        c.setFont("DejaVu", 12)
        c.drawString(x - 4, h - 70, chr(ord("А") + i))
    for j, y in enumerate(range(100, int(h) - 100, 160)):
        c.line(80, y, w - 320, y)
        c.drawString(60, y - 4, str(j + 1))
    c.setLineWidth(3)
    c.rect(180, 180, w - 700, h - 420)
    c.line(180, h / 2, w - 520, h / 2)
    c.line(w / 2, 180, w / 2, h - 240)
    c.setLineWidth(0.5)
    c.setFont("DejaVu", 10)
    c.drawString(w / 2 - 60, 160, "36 000 мм")
    c.drawString(200, h / 2 + 10, "Дневна 32,40 м²")
    c.drawString(w / 2 + 20, h / 2 + 10, "Кухня 18,75 м²")
    c.rect(w - 300, 40, 260, 120)
    c.setFont("DejaVu", 9)
    for k, label in enumerate(
        [
            "Обект: Жилищна сграда, гр. Пловдив",
            "Част: Архитектура",
            "Чертеж: Разпределение партер",
            "М 1:100   Лист А-101",
        ]
    ):
        c.drawString(w - 290, 140 - 22 * k, label)
    c.showPage()
    c.save()
    return buf.getvalue()


def scanned_pdf() -> bytes:
    """An image-only PDF, like a scanned signed protocol."""
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader

    img = Image.new("L", (1654, 2339), 248)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 34)
    for i, line in enumerate(
        [
            "ПРОТОКОЛ",
            "за откриване на строителна площадка",
            "и определяне на строителна линия и ниво",
            "",
            "Днес, 03.03.2027 г., в гр. Пловдив ...",
        ]
    ):
        draw.text((140, 180 + 60 * i), line, fill=20, font=font)
    for _ in range(4000):  # scanner speckle
        x, y = rng.randrange(1654), rng.randrange(2339)
        draw.point((x, y), fill=rng.randrange(120, 200))
    png = io.BytesIO()
    img.save(png, "PNG")
    buf = io.BytesIO()
    c = _canvas(buf, A4)
    c.drawImage(ImageReader(io.BytesIO(png.getvalue())), 0, 0, *A4)
    c.showPage()
    c.save()
    return buf.getvalue()


def encrypted_pdf(source: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(source)))
    writer.encrypt(user_password="parola123", owner_password="sobstvenik", algorithm="AES-256")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# ── Office ───────────────────────────────────────────────────────────────────

KSS_ROWS = [
    ("Изкоп с багер в земни почви", "м3", 420.0, 8.50),
    ("Обратен насип с уплътняване", "м3", 160.0, 6.20),
    ("Подложен бетон C12/15", "м3", 18.5, 118.00),
    ("Кофраж за фундаменти", "м2", 210.0, 14.80),
    ("Армировка B500B", "кг", 9850.0, 1.62),
    ("Бетон C25/30 за фундаменти", "м3", 96.0, 142.00),
    ("Хидроизолация на фундаменти", "м2", 260.0, 11.40),
    ("Кофраж за колони", "м2", 180.0, 17.20),
    ("Бетон C30/37 за колони", "м3", 24.0, 158.00),
    ("Кофраж за плоча", "м2", 640.0, 15.60),
    ("Бетон C25/30 за плоча", "м3", 112.0, 145.00),
    ("Зидария с керамични блокове 25 см", "м2", 820.0, 24.50),
    ("Вътрешна варова мазилка", "м2", 2150.0, 9.80),
    ("Топлоизолация EPS 10 см", "м2", 940.0, 21.30),
    ("Дограма PVC с троен стъклопакет", "м2", 118.0, 165.00),
]


def kss_xlsx() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "КСС"
    ws.append(["КОЛИЧЕСТВЕНО-СТОЙНОСТНА СМЕТКА"])
    ws.append(["Обект: Жилищна сграда, УПИ III-512, кв. 48, гр. Пловдив"])
    ws.append([])
    ws.append(["№", "Наименование на СМР", "Мярка", "Количество", "Ед. цена (EUR)", "Стойност (EUR)"])
    for cell in ws[4]:
        cell.font = Font(bold=True)
    for i, (name, unit, qty, price) in enumerate(KSS_ROWS, start=1):
        r = 4 + i
        ws.append([i, name, unit, qty, price, f"=D{r}*E{r}"])
    last = 4 + len(KSS_ROWS)
    ws.append(["", "Общо без ДДС", "", "", "", f"=SUM(F5:F{last})"])
    ws.append(["", "ДДС 20%", "", "", "", f"=F{last + 1}*0.2"])
    ws.append(["", "Всичко с ДДС", "", "", "", f"=F{last + 1}+F{last + 2}"])
    for col, width in zip("ABCDEF", (6, 46, 8, 12, 14, 16)):
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def contract_docx() -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading("ДОГОВОР ЗА СТРОИТЕЛСТВО № 17/2027", 0)
    doc.add_paragraph("Днес, 01.03.2027 г., в гр. Пловдив, между:")
    doc.add_paragraph("„Примерен Възложител“ ЕООД, ЕИК 000000000, наричано ВЪЗЛОЖИТЕЛ, и")
    doc.add_paragraph("„Примерен Строител“ АД, ЕИК 111111111, наричано ИЗПЪЛНИТЕЛ,")
    doc.add_paragraph("се сключи настоящият договор за следното:")
    for n in range(1, 13):
        doc.add_heading(f"Чл. {n}.", level=2)
        doc.add_paragraph(
            "ИЗПЪЛНИТЕЛЯТ се задължава да изпълни строително-монтажните работи съгласно "
            "одобрения инвестиционен проект, количествено-стойностната сметка и действащите "
            "нормативни актове, в срок и с качество, отговарящо на изискванията на ЗУТ."
        )
    table = doc.add_table(rows=1, cols=3)
    table.rows[0].cells[0].text, table.rows[0].cells[1].text, table.rows[0].cells[2].text = (
        "Етап",
        "Срок",
        "Стойност (EUR)",
    )
    for stage, days, value in [("Груб строеж", "120 дни", "412 000"), ("Довършителни работи", "90 дни", "238 000")]:
        row = table.add_row().cells
        row[0].text, row[1].text, row[2].text = stage, days, value
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── Images ───────────────────────────────────────────────────────────────────


def photo(width: int, height: int, fmt: str) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(0, height, 8):  # sky-to-ground gradient, so it is not trivially compressible
        shade = int(200 - 120 * y / height)
        draw.rectangle([0, y, width, y + 8], fill=(shade, shade + 20 if shade < 235 else 255, 255 - shade // 3))
    for _ in range(300):
        x, y = rng.randrange(width), rng.randrange(height)
        draw.rectangle(
            [x, y, x + rng.randrange(20, 200), y + rng.randrange(20, 200)],
            fill=tuple(rng.randrange(256) for _ in range(3)),
        )
    # Sensor noise: a real 20 MP JPEG is several MB, not a few hundred KB.
    img = Image.blend(img, Image.effect_noise((width, height), 60).convert("RGB"), 0.3)
    buf = io.BytesIO()
    img.save(buf, fmt, **({"quality": 92} if fmt == "JPEG" else {}))
    return buf.getvalue()


# ── Schedules ────────────────────────────────────────────────────────────────

TASKS = [
    "Мобилизация",
    "Изкопни работи",
    "Фундаменти",
    "Груб строеж",
    "Покрив",
    "Фасада",
    "Инсталации",
    "Довършителни работи",
    "Предаване",
]


def msproject_xml() -> bytes:
    start = date(2027, 3, 1)
    rows, cursor = [], start
    for uid, name in enumerate(TASKS, start=1):
        days = 5 + 10 * (uid % 4)
        finish = cursor + timedelta(days=days)
        pred = (
            f"<PredecessorLink><PredecessorUID>{uid - 1}</PredecessorUID><Type>1</Type></PredecessorLink>"
            if uid > 1
            else ""
        )
        rows.append(
            f"<Task><UID>{uid}</UID><ID>{uid}</ID><Name>{name}</Name><OutlineLevel>1</OutlineLevel>"
            f"<Start>{cursor}T08:00:00</Start><Finish>{finish}T17:00:00</Finish>"
            f"<Duration>PT{days * 8}H0M0S</Duration><DurationFormat>7</DurationFormat>{pred}</Task>"
        )
        cursor = finish
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Project xmlns="http://schemas.microsoft.com/project">'
        "<Name>Жилищна сграда Пловдив</Name><Title>График</Title>"
        f"<StartDate>{start}T08:00:00</StartDate><FinishDate>{cursor}T17:00:00</FinishDate>"
        "<Tasks>" + "".join(rows) + "</Tasks></Project>\n"
    )
    return xml.encode()


# ── The pack ─────────────────────────────────────────────────────────────────


def build(tier: str) -> None:
    protocol = text_pdf(
        "Протокол обр. 2 – откриване на строителна площадка", [f"Ред {i}: текст на протокола." for i in range(1, 30)]
    )

    # Real-looking documents a Bulgarian firm uploads every week
    emit("kss-xlsx", "КСС_Жилищна_сграда_Пловдив.xlsx", kss_xlsx(), kind="xlsx")
    emit("contract-docx", "Договор_за_строителство_17-2027.docx", contract_docx(), kind="docx")
    emit("protocol-pdf", "Протокол_обр_2.pdf", protocol, kind="pdf")
    emit(
        "drawing-a1-pdf",
        "А-101_Разпределение_партер.pdf",
        drawing_pdf(),
        kind="pdf",
        notes="A1 vector plan, for preview and PDF takeoff.",
    )
    emit("scanned-pdf", "Сканиран_протокол.pdf", scanned_pdf(), kind="pdf", notes="Image-only, no text layer.")
    emit(
        "multipage-pdf",
        "Технически_спецификации_60_стр.pdf",
        text_pdf("Технически спецификации", ["Раздел " + str(i) for i in range(1, 40)], pages=60),
        kind="pdf",
    )
    emit("schedule-mspdi", "График_Жилищна_сграда.xml", msproject_xml(), kind="mspdi")
    emit(
        "notes-txt",
        "Бележки от оглед.txt",
        "Оглед на обекта на 04.03.2027 г.\nБетонът на плочата е положен.\n".encode(),
        kind="txt",
    )
    emit(
        "list-csv",
        "Списък_материали.csv",
        "Материал;Мярка;Количество\nБетон C25/30;м3;96\nАрматура B500B;кг;9850\n".encode(),
        kind="csv",
    )
    emit("photo-20mp-jpg", "IMG_20270304_101500.jpg", photo(5472, 3648, "JPEG"), kind="jpg", notes="20 MP site photo.")
    emit("photo-png", "Екранна_снимка.png", photo(1920, 1080, "PNG"), kind="png")
    emit("photo-webp", "снимка.webp", photo(1600, 1200, "WEBP"), kind="webp")

    # Names that break naive code
    emit("name-cyrillic-punctuation", "Чертеж № 5 – Фасада (окончателен) v2.pdf", protocol, kind="pdf")
    emit("name-special-chars", "100%_план#1 & ревизия;'final'.pdf", protocol, kind="pdf")
    emit("name-emoji", "план 🏗️ етаж 2.pdf", protocol, kind="pdf")
    emit(
        "name-very-long",
        "long-name.pdf",
        protocol,
        kind="pdf",
        upload_name=("Многостранична_техническа_документация_за_обект_" * 5)[:200] + ".pdf",
        notes="200 Cyrillic characters (404 bytes): legal on Windows, longer than Linux allows in one file name.",
    )
    emit("name-no-extension", "Протокол без разширение", protocol, kind="pdf", expect="either")
    emit("name-upper-extension", "ПЛАН_ЕТАЖ.PDF", protocol, kind="pdf")
    emit(
        "duplicate-a",
        "План.pdf",
        text_pdf("План – вариант А", ["Първи файл със същото име."]),
        kind="pdf",
        notes="Same name as duplicate-b, different content: both must survive, neither overwrites the other.",
    )
    emit("duplicate-b", "План.pdf", text_pdf("План – вариант Б", ["Втори файл със същото име."]), kind="pdf")

    # Broken and hostile files
    emit("empty-pdf", "празен.pdf", b"", kind="pdf", expect="either", notes="Zero bytes.")
    emit(
        "truncated-pdf",
        "прекъснат.pdf",
        protocol[: len(protocol) // 2],
        kind="pdf",
        expect="either",
        notes="Upload cut in half.",
    )
    emit(
        "encrypted-pdf",
        "защитен_с_парола.pdf",
        encrypted_pdf(protocol),
        kind="pdf",
        expect="either",
        notes="Password parola123.",
    )
    emit(
        "exe-as-pdf",
        "фактура.pdf",
        b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff" + bytes(200),
        kind="pdf",
        expect="rejected",
        notes="A Windows executable named .pdf: must be refused.",
    )
    emit(
        "pdf-as-dwg",
        "не_е_чертеж.dwg",
        protocol,
        kind="dwg",
        expect="either",
        notes="A PDF renamed .dwg: must be explained, not crash a parser.",
    )

    # A batch, as when someone drops a whole folder
    for n in range(1, 41):
        emit(
            f"batch-{n:02d}",
            f"Протокол-{n:02d}.pdf",
            text_pdf(f"Протокол № {n}", [f"Партида от 40 файла, файл {n}."]),
            kind="pdf",
            notes="Part of the 40-file batch.",
        )

    if tier == "nightly":
        emit_big(
            "big-200mb-zip",
            "Архив_200MB.zip",
            200 * 1024 * 1024,
            tier="nightly",
            expect="accepted",
            notes="Large upload well inside the proxy's 500 MB limit.",
        )
        emit_big(
            "big-480mb-zip",
            "Архив_480MB.zip",
            480 * 1024 * 1024,
            tier="nightly",
            expect="accepted",
            notes="Just under the proxy's 500 MB limit.",
        )
        emit_big(
            "too-big-520mb-zip",
            "Архив_520MB.zip",
            520 * 1024 * 1024,
            tier="nightly",
            expect="rejected",
            notes="Over the proxy's 500 MB limit: the user must be told the file is too large.",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tier", choices=["pr", "nightly"], default="pr")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    build(args.tier)
    (OUT.parent / "generated.json").write_text(
        json.dumps({"tier": args.tier, "samples": entries}, indent=2, ensure_ascii=False)
    )
    total = sum(e["bytes"] for e in entries)
    print(f"{len(entries)} generated files, {total / 1e6:.1f} MB, in {OUT}")
