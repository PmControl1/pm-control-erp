# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Company profile API - the letterhead printed on generated documents.

    GET    /api/v1/company-profile/         - any signed-in user. The settings
                                              preview reads it, and so does an
                                              export started by a non-admin.
    GET    /api/v1/company-profile/options/ - any signed-in user. The caps the
                                              sanitiser enforces, for the form.
    PUT    /api/v1/company-profile/         - admin only. Merge and persist.
    DELETE /api/v1/company-profile/         - admin only. Clear the profile.

Deliberately NOT mounted alongside the public ``GET /api/v1/branding/`` in
:mod:`app.core.branding_router`. That endpoint answers anonymous callers,
because the login page needs the app brand before sign-in; a registered
address and a tax identifier must never be one field away from it. A router of
its own, reading a file of its own, keeps the two apart structurally rather
than by somebody remembering which keys to leave out of a response.

Persistence is a small JSON file in the data dir (see
:mod:`app.core.company_profile`) - no database table, so this needs no
migration.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.core.app_branding import MAX_LOGO_DATA_URL_CHARS
from app.core.company_profile import (
    LOGO_IMAGE_TYPES,
    MAX_ADDRESS_CHARS,
    MAX_ADDRESS_LINES,
    MAX_COMPANY_ID,
    MAX_COMPANY_ID_LABEL,
    MAX_EMAIL,
    MAX_LEGAL_NAME,
    MAX_PHONE,
    MAX_REGISTRATION_LINE,
    MAX_WEBSITE,
    read_company_profile,
    reset_company_profile,
    sanitise,
    write_company_profile,
)
from app.dependencies import RequireRole, get_current_user_payload

router = APIRouter(tags=["company-profile"])

#: The accepted logo types as MIME names, for the options and the refusal.
_LOGO_MIME_TYPES = [f"image/{kind}" for kind in LOGO_IMAGE_TYPES]


class CompanyProfileResponse(BaseModel):
    """The letterhead. Always complete and already sanitised; unset is ``""``."""

    document_logo_data_url: str = ""
    #: PNG rasterised in the browser from an SVG logo; PDFs print this one.
    document_logo_png_data_url: str = ""
    legal_name: str = ""
    address: str = ""
    registration_line: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    #: The statutory company number the active country pack asks for, as
    #: checked and normalised, and the name it is printed under ("ЕИК").
    company_id: str = ""
    company_id_label: str = ""


class CompanyProfileOptions(BaseModel):
    """The caps the UI form should enforce.

    Served from the same constants the sanitiser uses, so a form built from
    this response cannot accept text the server will quietly trim or a file
    type it will quietly drop.
    """

    max_lengths: dict[str, int]
    max_address_lines: int
    max_logo_data_url_chars: int
    logo_mime_types: list[str]
    #: The company number the active country pack asks for (its scheme, label,
    #: placeholder and help, plus ``country``), or ``None`` when no active
    #: pack names one. The form shows the field only when this is set.
    company_identifier: dict[str, Any] | None = None


class CompanyProfileUpdate(BaseModel):
    """Admin payload. All fields optional so a client can send just what changed.

    Deliberately untyped beyond the basics: caps and formats are enforced by
    :func:`app.core.company_profile.sanitise`, which also guards the read path,
    so there is exactly one definition of what a legal profile is. A cap
    repeated here would answer an over-long name with a 422 where the
    sanitiser trims it. The one refusal, an unusable logo, is decided by that
    same sanitiser in :func:`_refuse_an_unusable_logo`.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    document_logo_data_url: str | None = None
    document_logo_png_data_url: str | None = None
    legal_name: str | None = None
    address: str | None = None
    registration_line: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    company_id: str | None = None


@router.get(
    "/company-profile/",
    response_model=CompanyProfileResponse,
    dependencies=[Depends(get_current_user_payload)],
)
@router.get(
    "/company-profile",
    response_model=CompanyProfileResponse,
    include_in_schema=False,
    dependencies=[Depends(get_current_user_payload)],
)
async def get_company_profile() -> CompanyProfileResponse:
    """The letterhead every generated document is printed with."""
    return CompanyProfileResponse(**read_company_profile())


@router.get(
    "/company-profile/options/",
    response_model=CompanyProfileOptions,
    dependencies=[Depends(get_current_user_payload)],
)
@router.get(
    "/company-profile/options",
    response_model=CompanyProfileOptions,
    include_in_schema=False,
    dependencies=[Depends(get_current_user_payload)],
)
async def get_company_profile_options() -> CompanyProfileOptions:
    """The caps and accepted logo types, so the form never offers a rejected value."""
    return CompanyProfileOptions(
        max_lengths={
            "legal_name": MAX_LEGAL_NAME,
            "address": MAX_ADDRESS_CHARS,
            "registration_line": MAX_REGISTRATION_LINE,
            "phone": MAX_PHONE,
            "email": MAX_EMAIL,
            "website": MAX_WEBSITE,
            "company_id": MAX_COMPANY_ID,
            "company_id_label": MAX_COMPANY_ID_LABEL,
        },
        max_address_lines=MAX_ADDRESS_LINES,
        max_logo_data_url_chars=MAX_LOGO_DATA_URL_CHARS,
        logo_mime_types=list(_LOGO_MIME_TYPES),
        company_identifier=_active_company_identifier(),
    )


def _active_company_identifier() -> dict[str, Any] | None:
    """The active pack's company number spec with its country, or ``None``.

    Read at request time, so activating or switching a pack changes the form
    without a restart. An unreadable pack state asks for nothing, the way an
    installation without a pack does.
    """
    try:
        from app.core.partner_pack.discovery import get_active_pack

        pack = get_active_pack()
    except Exception:  # noqa: BLE001 - a broken pack state must not break the settings page
        return None
    if pack is None or pack.company_identifier is None or pack.market_country_code is None:
        return None
    return {**pack.company_identifier.model_dump(), "country": pack.market_country_code}


def _checked_company_id(submitted: str) -> tuple[str, str]:
    """The number to store and the label to store it under, or a 422.

    ``""`` clears the number on purpose. Anything else is checked by the
    active pack's scheme when the registry has one: a shape or check-digit
    failure is refused, so a mistyped ЕИК never reaches a letterhead or a
    tender declaration. A scheme the registry does not carry stores the
    number as typed, which is what the free-text registration line did.
    Without an active pack that names a number there is nothing to file it
    under, and the field is refused rather than stored with no name.
    """
    spec = _active_company_identifier()
    if not submitted:
        return "", ""
    if spec is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "no_company_identifier",
                "field": "company_id",
                "message": "No active country pack names a company number, so there is nothing to file it under.",
            },
        )
    from app.core.party_identifiers import check

    result = check(spec["country"], spec["scheme"], submitted)
    if result is None:
        return submitted, spec["label"]
    if not result.valid:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_company_id",
                "field": "company_id",
                "reason": result.reason,
                "scheme": spec["scheme"],
                "label": spec["label"],
                "message": result.details.get("message") or f"This is not a valid {spec['label']}.",
            },
        )
    return result.normalised, spec["label"]


def _refuse_an_unusable_logo(submitted: str | None) -> None:
    """Answer 422 when a submitted logo would not survive the sanitiser.

    Text fields are trimmed on the way in and the admin sees the trimmed value
    in the response. A logo cannot be trimmed: the sanitiser reduces it to
    ``""``, and merged over the stored profile that ``""`` would silently
    delete the logo the firm already had, behind a 200. Refusing the whole
    request leaves the stored profile exactly as it was.

    ``None`` (leave alone) and ``""`` (clear on purpose) are not submissions of
    a logo and pass through. Whether a logo is usable is still the sanitiser's
    call; the length is consulted only to say why it was not.
    """
    if not submitted or sanitise({"document_logo_data_url": submitted})["document_logo_data_url"]:
        return
    if len(submitted) > MAX_LOGO_DATA_URL_CHARS:
        reason = "too_large"
        message = (
            f"The document logo is too large: {len(submitted)} characters as a data URL, "
            f"the limit is {MAX_LOGO_DATA_URL_CHARS}."
        )
    else:
        reason = "unsupported_format"
        message = "The document logo must be a base64 data URL of one of: " + ", ".join(_LOGO_MIME_TYPES) + "."
    raise HTTPException(
        status_code=422,
        detail={
            "error": "invalid_document_logo",
            "field": "document_logo_data_url",
            "reason": reason,
            "message": message,
            "accepted_types": list(_LOGO_MIME_TYPES),
            "max_chars": MAX_LOGO_DATA_URL_CHARS,
        },
    )


@router.put(
    "/company-profile/",
    response_model=CompanyProfileResponse,
    dependencies=[Depends(RequireRole("admin"))],
)
@router.put(
    "/company-profile",
    response_model=CompanyProfileResponse,
    include_in_schema=False,
    dependencies=[Depends(RequireRole("admin"))],
)
async def put_company_profile(body: CompanyProfileUpdate) -> CompanyProfileResponse:
    """Admin: set the letterhead. Merged over what is stored, then sanitised.

    ``None`` leaves the stored value alone, so the form can save one field at a
    time and a client that only changes the logo does not have to resend the
    address. An empty string clears that one field; DELETE clears them all. A
    logo the sanitiser would drop is refused with 422 before anything is
    merged, so it cannot cost the firm the logo already stored.
    """
    _refuse_an_unusable_logo(body.document_logo_data_url)
    current = read_company_profile()
    patch = {key: value for key, value in body.model_dump().items() if value is not None}
    if "company_id" in patch:
        patch["company_id"], patch["company_id_label"] = _checked_company_id(patch["company_id"])
    if "document_logo_data_url" in patch:
        # A new logo replaces its PNG too, unless the same request carries one.
        patch.setdefault("document_logo_png_data_url", "")
    current.update(patch)
    return CompanyProfileResponse(**write_company_profile(current))


@router.delete(
    "/company-profile/",
    response_model=CompanyProfileResponse,
    dependencies=[Depends(RequireRole("admin"))],
)
@router.delete(
    "/company-profile",
    response_model=CompanyProfileResponse,
    include_in_schema=False,
    dependencies=[Depends(RequireRole("admin"))],
)
async def delete_company_profile() -> CompanyProfileResponse:
    """Admin: clear the letterhead, so documents print without one again."""
    return CompanyProfileResponse(**reset_company_profile())
