# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bulgarian company identifier: the ЕИК (единен идентификационен код).

Every company in the Commercial Register and every entity in the БУЛСТАТ
register carries one, issued by the Агенция по вписванията. It is what a
Bulgarian letterhead, invoice and tender declaration names the firm by, and a
VAT-registered company's ДДС number is the same digits behind "BG".

Two lengths are issued (Закон за регистър БУЛСТАТ, чл. 6):

* nine digits for a legal entity, a sole trader and the other entities of
  чл. 3. The ninth is a check digit over the first eight: weights 1 to 8,
  modulo 11; a remainder of 10 is recomputed with weights 3 to 10, and a
  second 10 gives 0. Self-insured persons once used their ten-digit ЕГН here;
  since 2021 the Agency has converted those codes to nine digits, so ten digits
  are no longer a valid ЕИК.
* thirteen digits for a branch (клон) of a foreign or Bulgarian entity: the
  parent's nine digits, three digits of branch number and a check digit over
  digits 9 to 12 with weights 2, 7, 3, 5, recomputed with 4, 9, 5, 7 on a
  remainder of 10, a second 10 giving 0.

The nine-digit rule is the one every open implementation agrees on (it is
python-stdnum's ``bg.vat`` legal-entity check). The thirteen-digit rule is
documented by secondary sources only, so a branch code that passes it is
valid but says so in ``details["needs_expert_review"]``, the way the French
module treats La Poste's exception.

The shape failure and the check-digit failure are kept apart, so a caller can
tell "this is not an ЕИК at all" from "this is an ЕИК with a typo in it".
"""

from __future__ import annotations

import re

from app.core.party_identifiers import IdentifierCheck, register

REASON_SHAPE = "shape"
REASON_CHECKSUM = "checksum"

_SOURCE = "https://portal.registryagency.bg/"
_READ_DATE = "2026-10-31"
_SEPARATORS = re.compile(r"[\s\-./]")

_NINE_FIRST = (1, 2, 3, 4, 5, 6, 7, 8)
_NINE_SECOND = (3, 4, 5, 6, 7, 8, 9, 10)
_BRANCH_FIRST = (2, 7, 3, 5)
_BRANCH_SECOND = (4, 9, 5, 7)


def normalise(value: str | None) -> str:
    """Drop the separators people type, and a leading ``BG`` from a VAT number.

    A Bulgarian company's ДДС number is ``BG`` and its ЕИК, so a firm pasting
    the number from an invoice gets its ЕИК checked rather than a shape error.
    """
    cleaned = _SEPARATORS.sub("", value or "").upper()
    return cleaned[2:] if cleaned.startswith("BG") else cleaned


def _weighted_check(digits: str, first: tuple[int, ...], second: tuple[int, ...]) -> int:
    """The two-pass modulo-11 check digit the ЕИК uses at both lengths."""
    remainder = sum(w * int(d) for w, d in zip(first, digits, strict=True)) % 11
    if remainder == 10:
        remainder = sum(w * int(d) for w, d in zip(second, digits, strict=True)) % 11
    return 0 if remainder == 10 else remainder


def eik_check_digit(first_eight: str) -> int:
    """The ninth digit of a nine-digit ЕИК."""
    return _weighted_check(first_eight, _NINE_FIRST, _NINE_SECOND)


def branch_check_digit(digits_nine_to_twelve: str) -> int:
    """The thirteenth digit of a branch ЕИК, over its digits 9 to 12."""
    return _weighted_check(digits_nine_to_twelve, _BRANCH_FIRST, _BRANCH_SECOND)


def _result(normalised: str, *, valid: bool, reason: str | None = None, **extra: str) -> IdentifierCheck:
    details = {"label": "ЕИК", "read_date": _READ_DATE, **extra}
    return IdentifierCheck(
        valid=valid,
        normalised=normalised,
        scheme="eik",
        country="BG",
        reason=reason,
        source=_SOURCE,
        details=details,
    )


@register("BG", "eik")
def check_eik(value: str) -> IdentifierCheck:
    """ЕИК: nine digits, or thirteen for a branch, each with its check digit."""
    number = normalise(value)
    if not re.fullmatch(r"\d{9}|\d{13}", number):
        return _result(
            number,
            valid=False,
            reason=REASON_SHAPE,
            message="An ЕИК has 9 digits, or 13 for a branch.",
        )
    if int(number[8]) != eik_check_digit(number[:8]):
        return _result(
            number,
            valid=False,
            reason=REASON_CHECKSUM,
            message="The ЕИК fails its check digit; it is probably mistyped.",
        )
    if len(number) == 9:
        return _result(number, valid=True)
    if int(number[12]) != branch_check_digit(number[8:12]):
        return _result(
            number,
            valid=False,
            reason=REASON_CHECKSUM,
            message="The branch part of the ЕИК fails its check digit; it is probably mistyped.",
        )
    return _result(
        number,
        valid=True,
        needs_expert_review="true",
        message="Branch check digit verified against a rule documented by secondary sources only.",
    )


__all__ = [
    "REASON_CHECKSUM",
    "REASON_SHAPE",
    "branch_check_digit",
    "check_eik",
    "eik_check_digit",
    "normalise",
]
