# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The project classifications a country pack declares, checked and served.

A classification is a closed list a project is filed under because its
country's law says so: Bulgaria's six ЗУТ categories are the first. The list
lives in the pack's manifest (:class:`ProjectClassificationSpec`), the value on
the project under ``custom_fields[key]``. This module is the one reader of both:
the project service asks it whether a value is allowed, and the packs router
asks it what to offer on the project form.

Which pack speaks for a project is not decided here. It is the pack that fits
out the project's country (:func:`app.modules.projects.country_configuration.
configuration_pack`), the same one its rule sets and methodology come from, so
a Bulgarian project created while another country's pack is active still gets
the Bulgarian list, and a project in a country no pack is written for gets
none.

Pure functions over manifests: no database and no pack state.
"""

from __future__ import annotations

from typing import Any

from app.core.partner_pack.manifest import PartnerPackManifest

__all__ = ["classification_errors", "classifications_payload"]


def classification_errors(pack: PartnerPackManifest, custom_fields: dict[str, Any]) -> list[dict[str, str]]:
    """Every declared classification in ``custom_fields`` whose value is not an option.

    A key the pack does not declare is an ordinary custom field and is not
    looked at. A declared key holding ``None`` or ``""`` means "not recorded",
    which is always allowed: the category of a project is often not known on
    the day it is opened.

    Args:
        pack: The pack that fits out the project's country.
        custom_fields: The project's custom fields as submitted.

    Returns:
        ``[{key, value, message}]``, empty when everything is allowed.
    """
    errors: list[dict[str, str]] = []
    for spec in pack.project_classifications:
        if spec.key not in custom_fields:
            continue
        raw = custom_fields[spec.key]
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            continue
        allowed = [option.value for option in spec.options]
        if not isinstance(raw, str) or raw.strip() not in allowed:
            errors.append(
                {
                    "key": spec.key,
                    "value": str(raw),
                    "message": f"{spec.label_en or spec.label} must be one of {', '.join(allowed)}.",
                }
            )
    return errors


def classifications_payload(pack: PartnerPackManifest | None, *, country: str | None, source: str) -> dict[str, Any]:
    """What the project form needs to offer a country's classifications.

    Args:
        pack: The pack that fits out the country, or ``None``.
        country: The country the form asked about, as the caller resolved it.
        source: How ``pack`` was chosen (a ``SOURCE_*`` constant of
            ``country_configuration``), returned so the form can say why.

    Returns:
        ``{country, pack_slug, locale, source, classifications}``. The list is
        empty when no pack speaks for the country or the pack declares none.
    """
    return {
        "country": country,
        "pack_slug": pack.slug if pack is not None else None,
        "locale": pack.default_locale if pack is not None else None,
        "source": source,
        "classifications": [spec.model_dump() for spec in pack.project_classifications] if pack is not None else [],
    }
