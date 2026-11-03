# PM Project Management - the Bulgarian КСС rule set.
# Licensed under the GNU AGPL v3.0 or later, like the rest of this program.
"""The ``bulgaria`` rule set: a КСС read the way a Bulgarian tender reads it.

Two questions a bidder is excluded over, and the platform can answer from the
bill alone:

* **Does the priced КСС keep the количествена сметка?** Under the ЗОП the
  contracting authority issues the количествена сметка and the bidder prices
  it without changing a description, a unit or a quantity. A bill that names
  the количествена сметка it was priced against
  (``metadata["kss_tender_bill_id"]``, set in the bill editor) is compared line
  by line with it: ``bulgaria.kss_matches_tender_bill``. The payload builders
  load that bill as ``kss_tender`` (:mod:`app.modules.boq.kss_tender`); a bill
  that names none is not checked.
* **Does it close with ДДС the way a КСС does?** "Общо без ДДС", "ДДС 20 %",
  "Всичко с ДДС": one ДДС line (``bulgaria.vat_charged_once``), at the
  standard rate of ЗДДС чл. 66, ал. 1 (``bulgaria.vat_rate``), charged on
  everything above it and with nothing after it
  (``bulgaria.vat_on_whole_total``). A bill with no ДДС line at all is a
  warning only (``bulgaria.vat_line_present``): a contractor that is not
  registered under the ЗДДС charges none.

A ДДС line is a markup line of the ``tax`` category, or one named ДДС or VAT
whatever its category, since a line typed by hand often keeps the default
category. Count and order are checked on the effective stack for each part
of the work, including section additions and overrides, just as the bill's
calculator applies them. Every active VAT line is checked for its rate.

The rules live in their own module, like ``italy_prezzario``; the registration
in ``register_builtin_rules`` is the only line the two files share.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
)
from app.core.validation.messages import translate
from app.core.validation.rules import _get_leaf_positions, _get_locale, _ok, _position_metadata

BULGARIA_RULE_SET = "bulgaria"

#: Key of the bill metadata that names the количествена сметка a КСС is priced against.
TENDER_BILL_METADATA_KEY = "kss_tender_bill_id"

#: Key of the validation payload that carries that bill, see :mod:`app.modules.boq.kss_tender`.
TENDER_PAYLOAD_KEY = "kss_tender"

#: ЗДДС чл. 66, ал. 1: the standard rate, the one construction works are charged at.
STANDARD_VAT_PERCENT = Decimal("20")

#: Quantities are compared to the thousandth, the finest a КСС prints.
QUANTITY_STEP = Decimal("0.001")

_VAT_NAME_RE = re.compile(r"(?<!\w)(?:ддс|vat|dds)(?!\w)", re.IGNORECASE)

_WHOLE_BASES = frozenset({"cumulative", "subtotal"})

_QUOTES = str.maketrans({"„": '"', "“": '"', "”": '"', "«": '"', "»": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})


# ── Shared reading ────────────────────────────────────────────────────────────


def _as_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _number(value: Decimal) -> str:
    """A figure as a person writes it: no exponent, no trailing zeros."""
    text = format(value.normalize(), "f")
    return text if text not in ("-0", "") else "0"


def _excerpt(text: Any, limit: int = 60) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def is_vat_line(markup: dict[str, Any]) -> bool:
    """Whether a markup line is the bill's ДДС: the tax category, or named ДДС or VAT."""
    if str(markup.get("category") or "").strip().lower() == "tax":
        return True
    return bool(_VAT_NAME_RE.search(str(markup.get("name") or "")))


def _markups(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data
    raw = data.get("markups") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    return [m for m in raw if isinstance(m, dict)]


def _active(markup: dict[str, Any]) -> bool:
    return bool(markup.get("is_active", True))


def _bill_wide_stack(context: ValidationContext) -> list[dict[str, Any]]:
    """The active bill-wide markup lines in the order the bill compounds them.

    The sort is stable, so lines that share a ``sort_order`` keep the order the
    caller loaded them in, which is the bill's own (``sort_order``, then
    creation) on the editor's path.
    """
    lines = [m for m in _markups(context) if _active(m) and not m.get("scope_position_id")]

    def order(markup: dict[str, Any]) -> Decimal:
        return _as_decimal(markup.get("sort_order")) or Decimal(0)

    return sorted(lines, key=order)


def _has_priced_work(context: ValidationContext) -> bool:
    return any((_as_decimal(pos.get("total")) or Decimal(0)) != 0 for pos in _get_leaf_positions(context))


def _effective_markup_stacks(context: ValidationContext, *, priced_only: bool = False) -> list[list[dict[str, Any]]]:
    """The actual markup stacks that apply to the bill's work.

    A scoped line can replace a bill-wide line or add to it. Inspecting only
    bill-wide rows would miss double VAT on a section and contingency outside
    the VAT base. Reuse the calculator's inheritance and ordering helpers so
    validation follows the same stacks as the price calculation.
    """
    raw = _markups(context)
    if not any(_active(m) and m.get("scope_position_id") for m in raw):
        return [_bill_wide_stack(context)]

    from app.modules.boq.service import _effective_stack, _scope_chain

    lines = [
        SimpleNamespace(
            id=str(m.get("id") or f"@markup-{index}"),
            scope_position_id=str(m["scope_position_id"]) if m.get("scope_position_id") else None,
            overrides_id=str(m["overrides_id"]) if m.get("overrides_id") else None,
            sort_order=_as_decimal(m.get("sort_order")) or Decimal(0),
            payload=m,
        )
        for index, m in enumerate(raw)
    ]
    bill_wide = sorted([m for m in lines if m.scope_position_id is None], key=lambda m: m.sort_order)
    scoped: dict[str, list[Any]] = {}
    for line in lines:
        if line.scope_position_id is not None and _active(line.payload):
            scoped.setdefault(line.scope_position_id, []).append(line)

    positions = context.data.get("positions") or []
    parent_of = {
        str(p["id"]): str(p["parent_id"]) if p.get("parent_id") else None
        for p in positions
        if isinstance(p, dict) and p.get("id") is not None
    }
    leaves = _get_leaf_positions(context)
    if priced_only:
        leaves = [p for p in leaves if (_as_decimal(p.get("total")) or Decimal(0)) != 0]
    stacks: list[list[dict[str, Any]]] = []
    seen: set[tuple[str, ...]] = set()
    scope_ids = set(scoped)
    seen_chains: set[tuple[str, ...]] = set()
    for position in leaves:
        chain = _scope_chain(str(position.get("id")), parent_of, scope_ids)
        if chain in seen_chains:
            continue
        seen_chains.add(chain)
        effective = [m for m in _effective_stack(bill_wide, scoped, chain) if _active(m.payload)]
        key = tuple(m.id for m in effective)
        if key not in seen:
            seen.add(key)
            stacks.append([m.payload for m in effective])
    return stacks or [_bill_wide_stack(context)]


def _distinct_results(results: list[RuleResult]) -> list[RuleResult]:
    """A bill-wide problem shared by several sections needs one finding."""
    seen: set[tuple[str | None, bool, str]] = set()
    distinct: list[RuleResult] = []
    for result in results:
        key = (result.element_ref, result.passed, result.message)
        if key not in seen:
            seen.add(key)
            distinct.append(result)
    return distinct


def _result(
    rule: ValidationRule,
    *,
    passed: bool,
    message: str,
    element_ref: str | None = None,
    details: dict[str, Any] | None = None,
    suggestion: str | None = None,
    severity: Severity | None = None,
) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=severity or rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=element_ref,
        details=details or {},
        suggestion=suggestion,
    )


# ── ДДС ─────────────────────────────────────────────────────────────────────


class BulgarianVatLinePresent(ValidationRule):
    rule_id = "bulgaria.vat_line_present"
    name = "КСС Closes With ДДС"
    standard = BULGARIA_RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = 'A КСС closes with "Общо без ДДС", "ДДС 20 %" and "Всичко с ДДС"'

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _has_priced_work(context):
            return []
        locale = _get_locale(context)
        passed = all(
            any(is_vat_line(m) for m in stack) for stack in _effective_markup_stacks(context, priced_only=True)
        )
        return [
            _result(
                self,
                passed=passed,
                message=_ok(locale) if passed else translate(f"{self.rule_id}.fail", locale=locale),
                suggestion=None if passed else translate(f"{self.rule_id}.suggestion", locale=locale),
            )
        ]


class BulgarianVatChargedOnce(ValidationRule):
    rule_id = "bulgaria.vat_charged_once"
    name = "ДДС Charged Once"
    standard = BULGARIA_RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A КСС carries one ДДС line; a second one charges the tax twice"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for stack in _effective_markup_stacks(context):
            lines = [m for m in stack if is_vat_line(m)]
            if not lines:
                continue
            passed = len(lines) == 1
            names = ", ".join(f'"{m.get("name") or ""}"' for m in lines)
            results.append(
                _result(
                    self,
                    passed=passed,
                    message=_ok(locale)
                    if passed
                    else translate(f"{self.rule_id}.fail", locale=locale, count=len(lines), names=names),
                    details={"vat_lines": [str(m.get("name") or "") for m in lines]},
                    suggestion=None if passed else translate(f"{self.rule_id}.suggestion", locale=locale),
                )
            )
        return _distinct_results(results)


class BulgarianVatRate(ValidationRule):
    rule_id = "bulgaria.vat_rate"
    name = "ДДС At 20 %"
    standard = BULGARIA_RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Construction works are charged ДДС at 20 % of the total before tax (ЗДДС чл. 66, ал. 1)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for markup in _markups(context):
            if not _active(markup) or not is_vat_line(markup):
                continue
            name = str(markup.get("name") or "")
            kind = str(markup.get("markup_type") or "percentage").strip().lower()
            rate = _as_decimal(markup.get("percentage"))
            if kind != "percentage":
                passed, key = False, f"{self.rule_id}.not_percentage"
            else:
                passed, key = rate == STANDARD_VAT_PERCENT, f"{self.rule_id}.fail"
            results.append(
                _result(
                    self,
                    passed=passed,
                    message=_ok(locale)
                    if passed
                    else translate(key, locale=locale, name=name, rate=_number(rate or Decimal(0))),
                    element_ref=str(markup.get("id")) if markup.get("id") else None,
                    details={"name": name, "markup_type": kind, "percentage": _number(rate) if rate else None},
                    suggestion=None if passed else translate(f"{self.rule_id}.suggestion", locale=locale),
                )
            )
        return results


class BulgarianVatOnWholeTotal(ValidationRule):
    rule_id = "bulgaria.vat_on_whole_total"
    name = "ДДС On The Whole Total"
    standard = BULGARIA_RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = 'ДДС is charged on all of "Общо без ДДС" and nothing is added after it'

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = _get_locale(context)
        results: list[RuleResult] = []
        for stack in _effective_markup_stacks(context):
            for index, vat in enumerate(stack):
                if not is_vat_line(vat):
                    continue
                before = [m for m in stack[:index] if not is_vat_line(m)]
                after = [m for m in stack[index + 1 :] if not is_vat_line(m)]
                on_whole = str(vat.get("apply_to") or "direct_cost").strip().lower() in _WHOLE_BASES
                left_out = [] if on_whole else before
                name = str(vat.get("name") or "")
                failures: list[tuple[str, list[dict[str, Any]]]] = []
                if left_out:
                    failures.append((f"{self.rule_id}.base", left_out))
                if after:
                    failures.append((f"{self.rule_id}.after", after))
                ref = str(vat.get("id")) if vat.get("id") else None
                if not failures:
                    results.append(_result(self, passed=True, message=_ok(locale), element_ref=ref))
                    continue
                for key, lines in failures:
                    names = ", ".join(f'"{m.get("name") or ""}"' for m in lines)
                    results.append(
                        _result(
                            self,
                            passed=False,
                            message=translate(key, locale=locale, name=name, names=names),
                            element_ref=ref,
                            details={"vat_line": name, "lines": [str(m.get("name") or "") for m in lines]},
                            suggestion=translate(f"{self.rule_id}.suggestion", locale=locale),
                        )
                    )
        return _distinct_results(results)


# ── КСС against its количествена сметка ─────────────────────────────────────


def _text_key(text: Any) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).translate(_QUOTES)
    return re.sub(r"\s+", " ", value).strip().rstrip(" .;:").casefold()


def _unit_key(unit: Any) -> str:
    from app.modules.boq.importers.bulgaria_kss import canonical_unit

    return canonical_unit(str(unit or "")).strip().casefold()


def _quantity_key(value: Any) -> Decimal | None:
    number = _as_decimal(value)
    return None if number is None else number.quantize(QUANTITY_STEP, rounding=ROUND_HALF_UP)


def _ordinal_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).rstrip(".").casefold()


def _work_lines(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The measured lines of a bill: no section rows, no contingency allowance."""
    leaves = _get_leaf_positions(ValidationContext(data={"positions": positions}))
    return [pos for pos in leaves if not _position_metadata(pos).get("contingency")]


def _keys(positions: list[dict[str, Any]], lines: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Each line's own number and its number under its sections, as matching keys."""
    by_id = {str(p.get("id")): p for p in positions if p.get("id") is not None}
    own: list[str] = []
    path: list[str] = []
    for line in lines:
        number = _ordinal_key(_position_metadata(line).get("kss_source_ordinal", line.get("ordinal")))
        chain = [number]
        seen: set[str] = set()
        parent = line.get("parent_id")
        while parent and str(parent) in by_id and str(parent) not in seen:
            seen.add(str(parent))
            node = by_id[str(parent)]
            chain.append(_ordinal_key(_position_metadata(node).get("kss_source_ordinal", node.get("ordinal"))))
            parent = node.get("parent_id")
        own.append(number)
        path.append("/".join(reversed(chain)))
    return {"own": own, "path": path}


def _usable(keys: list[str]) -> bool:
    return all(keys) and len(set(keys)) == len(keys)


def match_lines(
    tender_positions: list[dict[str, Any]], kss_positions: list[dict[str, Any]]
) -> tuple[list[tuple[dict[str, Any], dict[str, Any] | None]], list[dict[str, Any]]] | None:
    """Pair each line of the количествена сметка with the КСС line of the same number.

    Lines are matched by their own number when it is unique in both bills, else
    by the number under their sections (a КСС that restarts at 1 in every
    раздел), else not at all.

    Returns:
        ``(pairs, extra)``: every tender line with its КСС line or ``None``, and
        the КСС lines that match no tender line. ``None`` when neither numbering
        tells the lines apart.
    """
    tender_lines = _work_lines(tender_positions)
    kss_lines = _work_lines(kss_positions)
    tender_keys = _keys(tender_positions, tender_lines)
    kss_keys = _keys(kss_positions, kss_lines)
    for kind in ("own", "path"):
        if _usable(tender_keys[kind]) and _usable(kss_keys[kind]):
            by_key = dict(zip(kss_keys[kind], kss_lines, strict=True))
            pairs = [(line, by_key.get(key)) for key, line in zip(tender_keys[kind], tender_lines, strict=True)]
            matched = {id(kss) for _tender, kss in pairs if kss is not None}
            extra = [line for line in kss_lines if id(line) not in matched]
            return pairs, extra
    return None


class BulgarianKssMatchesTenderBill(ValidationRule):
    rule_id = "bulgaria.kss_matches_tender_bill"
    name = "КСС Keeps The Количествена Сметка"
    standard = BULGARIA_RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = (
        "A priced КСС keeps every description, unit and quantity of the количествена сметка it was "
        "issued with, and adds no line of its own (ЗОП)"
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data
        tender = data.get(TENDER_PAYLOAD_KEY) if isinstance(data, dict) else None
        if not isinstance(tender, dict):
            return []
        locale = _get_locale(context)
        if tender.get("missing"):
            return [
                _result(
                    self,
                    passed=False,
                    severity=Severity.WARNING,
                    message=translate(f"{self.rule_id}.tender_missing", locale=locale),
                    details={"tender_bill_id": tender.get("boq_id")},
                    suggestion=translate(f"{self.rule_id}.tender_missing_suggestion", locale=locale),
                )
            ]
        bill = str(tender.get("name") or "")
        tender_positions = [p for p in tender.get("positions") or [] if isinstance(p, dict)]
        kss_positions = [p for p in (data.get("positions") or []) if isinstance(p, dict)]
        matched = match_lines(tender_positions, kss_positions)
        if matched is None:
            return [
                _result(
                    self,
                    passed=False,
                    severity=Severity.WARNING,
                    message=translate(f"{self.rule_id}.unmatched", locale=locale, bill=bill),
                    details={"tender_bill_id": tender.get("boq_id")},
                    suggestion=translate(f"{self.rule_id}.unmatched_suggestion", locale=locale),
                )
            ]
        pairs, extra = matched
        results: list[RuleResult] = []
        for line, kss in pairs:
            ordinal = str(line.get("ordinal") or "")
            if kss is None:
                results.append(
                    self._fail(
                        locale,
                        "missing",
                        None,
                        ordinal=ordinal,
                        description=_excerpt(line.get("description")),
                        bill=bill,
                    )
                )
                continue
            ref = str(kss.get("id")) if kss.get("id") else None
            found: list[RuleResult] = []
            if _text_key(kss.get("description")) != _text_key(line.get("description")):
                found.append(
                    self._fail(
                        locale,
                        "description",
                        ref,
                        ordinal=ordinal,
                        description=_excerpt(kss.get("description")),
                        tender_description=_excerpt(line.get("description")),
                    )
                )
            if _unit_key(kss.get("unit")) != _unit_key(line.get("unit")):
                found.append(
                    self._fail(
                        locale,
                        "unit",
                        ref,
                        ordinal=ordinal,
                        unit=str(kss.get("unit") or "-"),
                        tender_unit=str(line.get("unit") or "-"),
                    )
                )
            quantity, tender_quantity = _quantity_key(kss.get("quantity")), _quantity_key(line.get("quantity"))
            if quantity != tender_quantity:
                found.append(
                    self._fail(
                        locale,
                        "quantity",
                        ref,
                        ordinal=ordinal,
                        quantity=_number(quantity) if quantity is not None else "-",
                        tender_quantity=_number(tender_quantity) if tender_quantity is not None else "-",
                    )
                )
            results.extend(found or [_result(self, passed=True, message=_ok(locale), element_ref=ref)])
        for kss in extra:
            results.append(
                self._fail(
                    locale,
                    "extra",
                    str(kss.get("id")) if kss.get("id") else None,
                    ordinal=str(kss.get("ordinal") or ""),
                    description=_excerpt(kss.get("description")),
                    bill=bill,
                )
            )
        return results

    def _fail(self, locale: str, what: str, ref: str | None, **params: str) -> RuleResult:
        return _result(
            self,
            passed=False,
            message=translate(f"{self.rule_id}.{what}", locale=locale, **params),
            element_ref=ref,
            details={"difference": what, **params},
            suggestion=translate(f"{self.rule_id}.suggestion", locale=locale),
        )


BULGARIA_RULES: tuple[type[ValidationRule], ...] = (
    BulgarianKssMatchesTenderBill,
    BulgarianVatLinePresent,
    BulgarianVatChargedOnce,
    BulgarianVatRate,
    BulgarianVatOnWholeTotal,
)

__all__ = [
    "BULGARIA_RULES",
    "BULGARIA_RULE_SET",
    "STANDARD_VAT_PERCENT",
    "TENDER_BILL_METADATA_KEY",
    "TENDER_PAYLOAD_KEY",
    "is_vat_line",
    "match_lines",
]
