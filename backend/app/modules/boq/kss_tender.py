# PM Project Management - the количествена сметка a КСС is priced against.
# Licensed under the GNU AGPL v3.0 or later, like the rest of this program.
"""Load the tender bill a priced КСС names, for ``bulgaria.kss_matches_tender_bill``.

A bill names its количествена сметка in ``metadata["kss_tender_bill_id"]``,
which the bill editor sets. Both validation paths (the editor's Validate button
in ``boq.router`` and :class:`app.modules.validation.service.ValidationService`)
pass their payload through :func:`with_kss_tender_bill`, so the rule reads the
same tender lines whichever path runs it.

The payload gains ``kss_tender``:

* nothing, when the bill names no tender bill;
* ``{"boq_id", "name", "positions"}`` when it names one of the same project,
  each position in the shape the validation rules read;
* ``{"boq_id", "missing": True}`` when the bill it names is gone, belongs to
  another project or is the bill itself, so the rule can say the link is
  broken instead of passing as if nothing had been compared.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.core.validation.rules.bulgaria_kss import TENDER_BILL_METADATA_KEY, TENDER_PAYLOAD_KEY

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _row_type(position: Any, metadata: dict[str, Any]) -> str:
    """Section or position, the way the editor's validate path tells them apart."""
    if str(metadata.get("type") or "") == "section":
        return "section"
    unit = (getattr(position, "unit", "") or "").strip().lower()
    try:
        quantity = float(getattr(position, "quantity", 0) or 0)
        rate = float(getattr(position, "unit_rate", 0) or 0)
    except (TypeError, ValueError):
        quantity = rate = 0.0
    if unit in ("", "section") and quantity == 0.0 and rate == 0.0:
        return "section"
    return "position"


def tender_bill_id(metadata: Any) -> str | None:
    """The tender bill a bill's metadata names, or ``None``."""
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(TENDER_BILL_METADATA_KEY)
    text = str(value).strip() if value else ""
    return text or None


async def load_kss_tender(session: AsyncSession, boq_id: uuid.UUID | str) -> dict[str, Any] | None:
    """The ``kss_tender`` payload entry for ``boq_id``, or ``None`` when it names no tender bill."""
    from app.modules.boq.models import BOQ, Position

    own_id = boq_id if isinstance(boq_id, uuid.UUID) else uuid.UUID(str(boq_id))
    bill = await session.get(BOQ, own_id)
    if bill is None:
        return None
    named = tender_bill_id(bill.metadata_)
    if named is None:
        return None
    try:
        tender_id = uuid.UUID(named)
    except ValueError:
        return {"boq_id": named, "missing": True}
    tender = None if tender_id == own_id else await session.get(BOQ, tender_id)
    if tender is None or tender.project_id != bill.project_id:
        return {"boq_id": named, "missing": True}
    rows = (await session.execute(select(Position).where(Position.boq_id == tender_id))).scalars().all()
    positions: list[dict[str, Any]] = []
    for row in rows:
        metadata = row.metadata_ or {}
        positions.append(
            {
                "id": str(row.id),
                "parent_id": str(row.parent_id) if row.parent_id else None,
                "ordinal": row.ordinal,
                "description": row.description,
                "unit": row.unit,
                "quantity": float(row.quantity or 0),
                "type": _row_type(row, metadata),
                "metadata": metadata,
            }
        )
    return {"boq_id": str(tender_id), "name": tender.name, "positions": positions}


async def with_kss_tender_bill(
    session: AsyncSession | None, boq_id: uuid.UUID | str, data: dict[str, Any]
) -> dict[str, Any]:
    """Return ``data`` plus ``kss_tender`` when the bill names a tender bill; ``data`` is not changed."""
    if session is None:
        return data
    # The spreadsheet's totals are an immutable source audit, kept separately
    # from live markups and before any currency conversion or later edit.
    from app.modules.boq.importers.bulgaria_totals import SOURCE_TOTALS_KEY
    from app.modules.boq.models import BOQ

    own_id = boq_id if isinstance(boq_id, uuid.UUID) else uuid.UUID(str(boq_id))
    bill = await session.get(BOQ, own_id)
    metadata = bill.metadata_ if bill is not None and isinstance(bill.metadata_, dict) else {}
    last_import = metadata.get("last_import")
    source = last_import.get(SOURCE_TOTALS_KEY) if isinstance(last_import, dict) else None
    if isinstance(source, dict):
        data = {**data, SOURCE_TOTALS_KEY: source}
    tender = await load_kss_tender(session, boq_id)
    if tender is None:
        return data
    return {**data, TENDER_PAYLOAD_KEY: tender}
