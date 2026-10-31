# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Currencies the euro replaced, and the one rate each of them still has.

When a member state joins the euro area the Council fixes the rate between its
old currency and the euro irrevocably (Article 140(3) TFEU, written into
Council Regulation (EC) No 2866/98). From that day an amount in the old
currency has exactly one euro value. It is not a market quotation any more:
the ECB stops publishing a reference rate for it, so the FX register and the
bundled seed either have no rate for it or a rounded leftover of the old peg,
and either answer is wrong for a contract signed in the old money.

Bulgaria is the case this was written for. The lev was replaced on 1 January
2026 at 1.95583 lev per euro (Council Regulation (EU) 2025/1409 of 8 July 2025,
in force 1 January 2026). Bulgarian practice adds two rules, set by the Закон за
въвеждане на еврото в Република България (ЗВЕРБ), чл. 12: a lev amount is
converted by *dividing* it by the rate, the rate is used as published and is
never rounded or shortened, and the euro result is rounded to the cent on the
third decimal, half up. :func:`to_euro` is that rule and nothing else.

The cost base Bulgarian projects price from (``BG_SOFIA``) was published in
lev. With the fixed rate it converts into a euro project by definition rather
than by a feed that no longer quotes it, which is what lets a Bulgarian
estimate stay in euro while every source price is still a lev figure.

Why only the lev. The kuna was fixed at 7.53450 per euro from 1 January 2023,
but before that it floated, and nothing that asks for a rate here says on which
date. A fixed kuna rate would therefore reprice every pre-2023 kuna figure
wrongly. The lev has no such history: the currency board pegged it to the euro
at this same 1.95583 from 1 January 1999, so the one number is right for every
lev amount the platform can hold. A currency joins this table only when the
fixed rate is right for all of its dates, or when the callers can say a date.

stdlib only, so the FX service, the project service and the BOQ layer can all
import it without importing each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

__all__ = [
    "EURO",
    "IRREVOCABLE_EURO_RATES",
    "FixedEuroRate",
    "fixed_euro_rate",
    "fixed_rate_between",
    "fixed_rate_entries_for_project",
    "is_replaced_by_euro",
    "to_euro",
]

EURO = "EUR"

#: Precision of a fixed cross rate written out as a decimal string. The lev
#: rate itself has five decimals; its reciprocal does not terminate, and
#: twenty-eight significant digits keep the conversion of any amount the
#: platform can hold identical to the division ЗВЕРБ prescribes, to the cent.
_RECIPROCAL_DIGITS = 28

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class FixedEuroRate:
    """One currency the euro replaced.

    Attributes:
        currency: ISO 4217 code of the replaced currency.
        per_euro: Units of the currency per one euro, exactly as the Council
            fixed it.
        euro_since: The day the euro became the country's currency.
        country: ISO 3166-1 alpha-2 of the country that used it.
        legal_basis: The act that fixed the rate.
        label: How the currency is named in its own country, for a project's
            rate table.
    """

    currency: str
    per_euro: Decimal
    euro_since: date
    country: str
    legal_basis: str
    label: str


IRREVOCABLE_EURO_RATES: dict[str, FixedEuroRate] = {
    "BGN": FixedEuroRate(
        currency="BGN",
        per_euro=Decimal("1.95583"),
        euro_since=date(2026, 1, 1),
        country="BG",
        legal_basis="Council Regulation (EU) 2025/1409 of 8 July 2025; ЗВЕРБ чл. 12",
        label="Български лев (фиксиран курс 1,95583 лв. за 1 евро)",
    ),
}


def _code(value: str | None) -> str:
    return (value or "").strip().upper()


def is_replaced_by_euro(currency: str | None) -> bool:
    """Whether ``currency`` is one the euro replaced at a rate in this table."""
    return _code(currency) in IRREVOCABLE_EURO_RATES


def fixed_euro_rate(currency: str | None) -> Decimal | None:
    """Units of ``currency`` per one euro, or ``None`` when it floats."""
    entry = IRREVOCABLE_EURO_RATES.get(_code(currency))
    return entry.per_euro if entry else None


def fixed_rate_between(from_currency: str | None, to_currency: str | None) -> Decimal | None:
    """The fixed rate that turns one ``from_currency`` unit into ``to_currency``.

    Answers only when the pair is fixed by law: a replaced currency and the
    euro, in either direction, or two currencies both replaced by it. Any pair
    with a floating currency in it answers ``None`` and is left to the market
    rates, because a fixed answer there would be invented.

    Args:
        from_currency: ISO code of the amount.
        to_currency: ISO code wanted.

    Returns:
        Target units per one source unit, or ``None``.
    """
    src = _code(from_currency)
    dst = _code(to_currency)
    if not src or not dst:
        return None
    if src == dst:
        return Decimal("1")
    src_per_euro = Decimal("1") if src == EURO else fixed_euro_rate(src)
    dst_per_euro = Decimal("1") if dst == EURO else fixed_euro_rate(dst)
    if src_per_euro is None or dst_per_euro is None:
        return None
    with localcontext() as ctx:
        ctx.prec = _RECIPROCAL_DIGITS
        return +(dst_per_euro / src_per_euro)


def to_euro(amount: object, currency: str | None) -> Decimal:
    """Convert an amount in a replaced currency to euro, the way ЗВЕРБ чл. 12 does.

    Divides by the fixed rate as published and rounds the result to the cent,
    half up on the third decimal. An amount already in euro is only rounded.

    Args:
        amount: Number or numeric string.
        currency: The amount's ISO code.

    Returns:
        The euro amount, two decimals.

    Raises:
        ValueError: When ``currency`` is neither the euro nor a replaced
            currency, or ``amount`` is not a number.
    """
    try:
        value = Decimal(str(amount).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{amount!r} is not an amount") from exc
    code = _code(currency)
    if code == EURO:
        return value.quantize(_CENT, rounding=ROUND_HALF_UP)
    rate = fixed_euro_rate(code)
    if rate is None:
        raise ValueError(f"{code or '(blank)'} has no fixed euro rate")
    with localcontext() as ctx:
        ctx.prec = 50
        return (value / rate).quantize(_CENT, rounding=ROUND_HALF_UP)


def fixed_rate_entries_for_project(base_currency: str | None, country_code: str | None) -> list[dict[str, str]]:
    """The fixed-rate rows a new project should start its rate table with.

    A project's ``fx_rates`` row reads "this many base units per one unit of
    the code". A euro project in a country whose old currency the euro
    replaced is priced from sources still written in that currency, the
    Bulgarian cost base first among them, so it starts with that currency at
    its fixed rate instead of with a gap the BOQ reports as a missing rate.

    A project in another country, or in a currency that is not the euro, gets
    nothing: putting the lev into every euro project in the world would be
    noise, and a lev project keeps its own base.

    Args:
        base_currency: The project's currency.
        country_code: The project's ISO 3166-1 alpha-2 country.

    Returns:
        ``[{"code", "rate", "label"}]``, possibly empty.
    """
    if _code(base_currency) != EURO:
        return []
    country = _code(country_code)
    rows: list[dict[str, str]] = []
    for code, entry in IRREVOCABLE_EURO_RATES.items():
        if entry.country != country:
            continue
        rate = fixed_rate_between(code, EURO)
        if rate is None:  # pragma: no cover - every table row answers against the euro
            continue
        rows.append({"code": code, "rate": format(rate, "f"), "label": entry.label})
    return rows
