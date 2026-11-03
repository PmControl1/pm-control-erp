"""Keep Bulgarian Excel totals in their source currency for validation.

This snapshot is captured before any lev-to-euro conversion. It describes the
uploaded spreadsheet, not subsequently edited rates in the live bill.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

SOURCE_TOTALS_KEY = "bulgaria_source_totals"


def source_totals_snapshot(imported: Any) -> dict[str, Any]:
    """Taxable amounts per item sheet, including imported contingency lines."""
    amounts: dict[str, Decimal] = {}
    default_sheet = str(imported.metadata.get("item_sheet") or "")
    for position in imported.positions:
        if position.is_section:
            continue
        sheet = str((position.metadata or {}).get("import_sheet") or default_sheet)
        amount = (Decimal(str(position.quantity)) * Decimal(str(position.unit_rate))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        amounts[sheet] = amounts.get(sheet, Decimal(0)) + amount
    return {
        "currency": imported.currency,
        "partial": bool(imported.errors),
        "sheet_amounts": {sheet: str(amount) for sheet, amount in amounts.items()},
        "summary_rows": [
            {**row, "sheet": str(row.get("sheet") or default_sheet)}
            for row in imported.metadata.get("summary_rows") or []
        ],
    }
