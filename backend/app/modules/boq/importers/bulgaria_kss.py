# PM Project Management - Bulgarian КСС reading, on top of the spreadsheet importer.
# Licensed under the GNU AGPL v3.0 or later, like the rest of this program.
"""What a Bulgarian КСС needs beyond the generic spreadsheet reader.

The generic reader (``excel.py``) recognises a КСС by its Bulgarian headings,
which its ``bg`` tables now list in the spellings the trade uses. Three things
it cannot do on its own:

* **Units.** The same unit is written five ways across one firm's archive:
  "м2", "м²", "кв.м", "кв. м." and "m2". Kept as typed they are five units, so
  two bills of the same building never line up. :func:`canonical_unit` folds
  each to the one form Bulgarian estimates print.
* **Currency.** A КСС names its money in the price headings, "Ед. цена (лв.
  без ДДС)" or "Стойност, €". The generic reader drops that bracket to match
  the heading. :func:`money_currency` reads it back: ``BGN``, ``EUR`` or
  ``""`` when the headings do not say.
* **Lev to euro.** Since 1 January 2026 Bulgarian projects are kept in euro,
  while every КСС written before then is in лева. :func:`convert_to_euro`
  turns a lev bill's rates into euro by ЗВЕРБ чл. 12 (divide by 1.95583, round
  the result to the cent on the third decimal, half up) and keeps every lev
  figure on its line, so the original can always be shown next to it.

Pure functions, no database: the router decides when a conversion applies,
because only it knows the project's currency.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.core.euro_conversion import fixed_euro_rate, is_replaced_by_euro, to_euro
from app.modules.boq.importers._base import ImporterParseError

# ── Units ───────────────────────────────────────────────────────────────────

# Folded spelling -> the form a Bulgarian КСС prints. The key is the unit with
# spaces and dots removed, lower case, superscripts as digits ("кв. м." ->
# "квм", "м²" -> "м2"). Latin spellings come in from bills typed on a Latin
# keyboard ("m2", "m3", "br").
_UNIT_FORMS: dict[str, str] = {
    # area
    "м2": "м2",
    "квм": "м2",
    "кв": "м2",
    "m2": "м2",
    "sqm": "м2",
    # volume
    "м3": "м3",
    "кубм": "м3",
    "куб": "м3",
    "m3": "м3",
    # length
    "м": "м",
    "лм": "м",
    "мл": "м",
    "линм": "м",
    "линейнаметър": "м",
    "m": "м",
    # count
    "бр": "бр.",
    "броя": "бр.",
    "брой": "бр.",
    "br": "бр.",
    "pcs": "бр.",
    # set
    "компл": "компл.",
    "комплект": "компл.",
    "кт": "компл.",
    "к-т": "компл.",
    # mass
    "кг": "кг",
    "kg": "кг",
    "т": "т",
    "тон": "т",
    "тона": "т",
    "t": "т",
    # time and lump sums
    "чч": "ч.ч.",
    "часа": "ч",
    "ч": "ч",
    "мсм": "м.см.",
    "машсм": "м.см.",
    "ден": "ден",
    "дни": "ден",
    "сума": "сума",
    "общо": "сума",
    "аккорд": "сума",
}

_SUPERSCRIPTS = str.maketrans({"²": "2", "³": "3"})


def _unit_key(unit: str) -> str:
    folded = unicodedata.normalize("NFKC", unit).translate(_SUPERSCRIPTS).casefold()
    # Keep the hyphen of "к-т" out of the key too: "кт" carries the same reading.
    return re.sub(r"[\s.\-]+", "", folded)


def canonical_unit(unit: str) -> str:
    """The Bulgarian КСС form of ``unit``, or ``unit`` unchanged when unknown.

    >>> canonical_unit("кв. м.")
    'м2'
    >>> canonical_unit("л.м.")
    'м'
    >>> canonical_unit("Бр")
    'бр.'
    """
    text = (unit or "").strip()
    if not text:
        return text
    return _UNIT_FORMS.get(_unit_key(text), text)


# ── Currency named in the price headings ──────────────────────────────────

# Matched as whole words in the lowered heading, brackets included: the
# generic reader strips "(лв. без ДДС)" to match the column, and that bracket
# is exactly where the currency is written.
_LEV_WORDS = re.compile(r"(?<![а-яa-z])(лв|лева|лев|bgn)(?![а-яa-z])")
_EURO_WORDS = re.compile(r"(?<![а-яa-z])(евро|eur|euro)(?![а-яa-z])|€")


def _money_currencies(headings: list[Any] | tuple[Any, ...]) -> set[str]:
    """Every currency stated by a set of headings, before choosing one."""
    seen: set[str] = set()
    for heading in headings or ():
        if heading is None:
            continue
        text = unicodedata.normalize("NFKC", str(heading)).casefold()
        if _LEV_WORDS.search(text):
            seen.add("BGN")
        if _EURO_WORDS.search(text):
            seen.add("EUR")
    return seen


def money_currency(headings: list[Any] | tuple[Any, ...]) -> str:
    """The currency the price headings name: ``"BGN"``, ``"EUR"`` or ``""``.

    ``""`` also when the headings name both, which a bill with a lev column
    beside a euro column does. ``workbook_currency`` refuses that ambiguity
    before an import can convert or persist its rates.
    """
    seen = _money_currencies(headings)
    return seen.pop() if len(seen) == 1 else ""


def workbook_currency(sheet_headings: list[list[Any] | tuple[Any, ...]]) -> str:
    """One currency for every item sheet; refuse a bill we cannot convert safely.

    Dual-currency columns and worksheets in different currencies need a
    per-column/per-sheet choice the importer does not offer yet. A sheet
    without a stated currency must not inherit another sheet's BGN conversion.
    All-unstated bills keep the existing warning and import-as-written behavior.
    """
    currencies = [_money_currencies(headings) for headings in sheet_headings]
    stated = set().union(*currencies) if currencies else set()
    if len(stated) > 1 or (stated and any(not codes for codes in currencies)):
        raise ImporterParseError(
            "The bill has mixed or ambiguous currencies. Use one currency in all price headings "
            "and item sheets before importing; no rates were imported.",
            code="spreadsheet_currency_ambiguous",
        )
    return next(iter(stated), "")


# ── Lev to euro ─────────────────────────────────────────────────────────────


def convert_to_euro(imported: Any, currency: str) -> dict[str, Any] | None:
    """Convert every rate of ``imported`` from ``currency`` to euro, in place.

    ``imported`` is an :class:`~app.modules.boq.importers.ImportedBOQ`. Each
    converted line keeps what it was written as under ``metadata["original_
    currency"]`` (``{"currency": "BGN", "unit_rate": 12.5, "rate": "1.95583"}``),
    so a document can print the lev figure beside the euro one and an auditor
    can check every line. Quantities do not change.

    Returns a summary for the import response, or ``None`` when ``currency``
    is not one the euro replaced at a fixed rate (nothing is touched then).
    """
    code = (currency or "").strip().upper()
    if not is_replaced_by_euro(code):
        return None
    rate = fixed_euro_rate(code)
    converted = 0
    for position in imported.positions:
        if position.is_section or not position.unit_rate:
            continue
        original = float(position.unit_rate)
        position.unit_rate = float(to_euro(original, code))
        metadata = dict(position.metadata or {})
        metadata["original_currency"] = {"currency": code, "unit_rate": original, "rate": str(rate)}
        position.metadata = metadata
        converted += 1
    imported.currency = "EUR"
    summary = {"from": code, "to": "EUR", "rate": str(rate), "lines": converted}
    imported.metadata = {**(imported.metadata or {}), "currency_conversion": summary}
    imported.warnings.append(
        {
            "code": "currency_converted_to_euro",
            "params": {"from": code, "rate": str(rate), "lines": converted},
            # The fields the import dialog words the note from.
            "text": str(rate),
            "count": converted,
            "message": (
                f"The bill is priced in {code}. {converted} rates were converted to euro at the fixed "
                f"{rate} (ЗВЕРБ чл. 12); each line keeps its original {code} rate."
            ),
        }
    )
    return summary
