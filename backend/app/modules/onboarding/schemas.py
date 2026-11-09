# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request/response schemas for the onboarding provisioning API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.market_profile import MARKET_COST_REGION, MARKET_DEMO_IDS


class ProvisionRequest(BaseModel):
    """What the wizard wants provisioned in the background.

    The list is intentionally open to growth (vectorization, converter install)
    without a breaking change; today the two heavy first-run blockers are the
    regional cost base import and the sample project install.
    """

    region: str | None = Field(
        default=None,
        description="Bulgarian cost base id (BG_SOFIA). None to skip the optional download.",
    )
    demo_ids: list[str] = Field(
        default_factory=list,
        description="Sample project ids to install.",
    )

    @field_validator("region")
    @classmethod
    def _bulgarian_cost_base(cls, value: str | None) -> str | None:
        region = (value or "").strip().upper()
        if region and region != MARKET_COST_REGION:
            raise ValueError("Only the Bulgarian cost base (BG_SOFIA) is available in this product.")
        return region or None

    @field_validator("demo_ids")
    @classmethod
    def _bulgarian_samples(cls, value: list[str]) -> list[str]:
        ids = [item.strip() for item in value if item.strip()]
        if any(item not in MARKET_DEMO_IDS for item in ids):
            raise ValueError("Only Bulgarian sample projects are available in this product.")
        return ids


class JobState(BaseModel):
    """One background provisioning job's live state, safe to expose to its owner."""

    id: str
    kind: str
    arg: str | None = None
    state: str = Field(description="pending | started | success | failed | cancelled")
    outcome: Literal["completed", "partial", "failed"] | None = Field(
        default=None,
        description=(
            "The truthful result once the job has finished, None while it runs. "
            "'partial' means the job finished but left something out: rows the "
            "database refused (see failed_items) or a cost base without its "
            "resource price sheet."
        ),
    )
    pct: int = 0
    message: str | None = None
    error: str | None = None
    imported: int | None = Field(default=None, description="Items the job added, when it reports them.")
    total: int | None = Field(default=None, description="Items now present for the job's subject.")
    failed_items: int = Field(default=0, description="Items the job had to leave out.")
    text_language: str | None = Field(
        default=None, description="Language a loaded cost base's work items are in, when the job reports it."
    )
    text_language_requested: str | None = Field(
        default=None, description="Language the cost base should have opened in (its own)."
    )
    text_language_error: str | None = Field(
        default=None, description="Why the base did not open in text_language_requested, when it did not."
    )
    created_at: datetime | None = None
    completed_at: datetime | None = None


class ProvisionResponse(BaseModel):
    """The jobs kicked off (or reused) by a provision call."""

    jobs: list[JobState] = Field(default_factory=list)
    skipped_demo_ids: list[str] = Field(default_factory=list)
    demo_skip_reason: str | None = None


class StatusRequest(BaseModel):
    """Poll the state of previously provisioned jobs by their ids."""

    ids: list[str] = Field(
        default_factory=list,
        description="Job ids returned by /provision.",
    )


class StatusResponse(BaseModel):
    """Live state for the caller's provisioning jobs."""

    jobs: list[JobState] = Field(default_factory=list)
