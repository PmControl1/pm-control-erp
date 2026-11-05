"""Validate the source amounts removed from Bulgarian Excel work-item rows.

Section and workbook summaries are not native markup lines. Validate the
immutable source snapshot separately, never against converted or edited live
rates. Multiple tax blocks on one sheet or a separate recap sheet need human
review because the importer does not retain their accounting scope.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, ValidationRule
from app.core.validation.messages import translate
from app.core.validation.rules import _get_locale, _ok
from app.modules.boq.importers.bulgaria_totals import SOURCE_TOTALS_KEY

_VAT = re.compile(r"(?<!\w)(?:ддс|vat|dds)(?!\w)", re.IGNORECASE)
_RATE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_CENT = Decimal("0.01")


def _decimal(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


class BulgarianImportedVatTotals(ValidationRule):
    rule_id = "bulgaria.imported_vat_totals"
    name = "Imported КСС ДДС Totals"
    standard = "bulgaria"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "The source spreadsheet's ДДС and total agree with its taxable work and contingency"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        source = context.data.get(SOURCE_TOTALS_KEY) if isinstance(context.data, dict) else None
        if not isinstance(source, dict):
            return []
        rows = source.get("summary_rows")
        amounts = source.get("sheet_amounts")
        if not isinstance(rows, list) or not isinstance(amounts, dict):
            return []
        locale = _get_locale(context)
        results: list[RuleResult] = []
        sheets: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            if isinstance(row, dict):
                sheets.setdefault(str(row.get("sheet") or ""), []).append(row)
        for sheet, summaries in sheets.items():
            taxes = [r for r in summaries if r.get("kind") == "tax" and _VAT.search(str(r.get("description") or ""))]
            if not taxes:
                if any(
                    r.get("kind") == "grand_total" and _VAT.search(str(r.get("description") or "")) for r in summaries
                ):
                    results.append(self._result(locale, "review", sheet=sheet, severity=Severity.WARNING))
                continue
            net = _decimal(amounts.get(sheet))
            if source.get("partial") or net is None or len(taxes) != 1:
                results.append(self._result(locale, "review", sheet=sheet, severity=Severity.WARNING))
                continue
            tax = taxes[0]
            label = str(tax.get("description") or "")
            rate = _RATE.search(label)
            if rate and _decimal(rate[1].replace(",", ".")) != Decimal("20"):
                results.append(self._result(locale, "rate", sheet=sheet, row=tax.get("row"), rate=rate[1]))
            actual = _decimal(tax.get("amount"))
            expected = (net * Decimal("0.20")).quantize(_CENT, rounding=ROUND_HALF_UP)
            if actual is None or abs(actual - expected) > _CENT:
                results.append(
                    self._result(
                        locale, "amount", sheet=sheet, row=tax.get("row"), expected=str(expected), actual=str(actual)
                    )
                )
            for total in summaries:
                if total.get("kind") != "grand_total":
                    continue
                # Per-sheet total only; a recap sheet without its own work is
                # deliberately reported for review above instead of guessed.
                actual_total = _decimal(total.get("amount"))
                expected_total = net + (actual if actual is not None else expected)
                if actual_total is None or abs(actual_total - expected_total) > _CENT:
                    results.append(
                        self._result(
                            locale,
                            "amount",
                            sheet=sheet,
                            row=total.get("row"),
                            expected=str(expected_total),
                            actual=str(actual_total),
                        )
                    )
        if results:
            return results
        if not any(
            row.get("kind") == "tax" and _VAT.search(str(row.get("description") or ""))
            for row in rows
            if isinstance(row, dict)
        ):
            return []
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=True,
                message=_ok(locale),
            )
        ]

    def _result(self, locale: str, kind: str, *, severity: Severity | None = None, **details: Any) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=False,
            message=translate(f"{self.rule_id}.{kind}", locale=locale, **details),
            suggestion=translate(f"{self.rule_id}.suggestion", locale=locale),
            details={"source_spreadsheet": True, **details},
        )
