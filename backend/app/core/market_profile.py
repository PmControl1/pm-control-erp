"""The market shipped by PM Project Management.

Shared country registries and importers remain available for existing records
and documents from international suppliers. New workspace choices use this
profile instead of offering the upstream product's country catalogue.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MARKET_COUNTRY = "BG"
MARKET_REGION = "BG"
MARKET_CURRENCY = "EUR"
MARKET_LOCALE = "bg"
MARKET_PACK = "bulgaria-bg"
MARKET_COST_REGION = "BG_SOFIA"
MARKET_DEMO_IDS = ("residential-sofia",)
MARKET_TIMEZONE = "Europe/Sofia"


def _is_bulgaria(value: str) -> bool:
    if value.strip().upper() in {"BG", "BGR", "BULGARIA", "БЪЛГАРИЯ"}:
        return True
    from app.core.country_resolver import resolve_country_code

    return resolve_country_code(value) == MARKET_COUNTRY


def bulgarian_project_defaults(payload: Any) -> Any:
    """Apply the Bulgarian new-project contract at the public API boundary.

    The generic project service and update schema intentionally retain their
    ability to handle historical records. A supplied foreign country is
    refused, rather than quietly relabelling its address as Bulgarian.
    """
    if not isinstance(payload, Mapping):
        return payload
    values = dict(payload)
    country = str(values.get("country_code") or "").strip().upper()
    if country and country != MARKET_COUNTRY:
        raise ValueError("New projects are available for Bulgaria (BG) only.")
    region = str(values.get("region") or "").strip()
    if region and not _is_bulgaria(region):
        raise ValueError("New projects must use the Bulgarian market (BG).")
    address = values.get("address")
    if isinstance(address, Mapping) and str(address.get("country") or "").strip():
        if not _is_bulgaria(str(address["country"])):
            raise ValueError("New project site addresses must be in Bulgaria.")
    currency = str(values.get("currency") or "").strip().upper()
    if currency and currency != MARKET_CURRENCY:
        raise ValueError("New Bulgarian projects use EUR; legacy BGN amounts can be imported.")
    locale = str(values.get("locale") or "").strip()
    values.update(country_code=MARKET_COUNTRY, region=MARKET_REGION, currency=MARKET_CURRENCY)
    values["locale"] = locale or MARKET_LOCALE
    return values
