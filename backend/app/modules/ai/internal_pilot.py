# PM Project Management internal company AI pilot.
"""Single-company AI modes on a closed, demo-free installation.

The legacy staff pilot grants its environment-held DeepSeek key per account.
In managed mode the owner selects the provider and approves project teams.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

ACCESS_FLAG = "pmpm_internal_ai_access"


@dataclass(frozen=True)
class CompanyAccess:
    """Transient authorization from an active database account, never user metadata."""

    is_owner: bool
    granted: bool


def company_store_path() -> Path:
    from app.core.demo_seed import resolve_data_dir

    return resolve_data_dir() / ".pmpm" / "company-ai.sqlite3"


def managed_ai_requested() -> bool:
    """Keep unsafe managed deployments locked; never fall through to personal keys."""
    if os.environ.get("PMPM_INTERNAL_AI_PILOT", "").strip().lower() != "true":
        return False
    if os.environ.get("PMPM_AI_OWNER_USER_ID", "").strip():
        return True
    try:
        company_store_path().stat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def managed_ai_enabled() -> bool:
    if not managed_ai_requested() or not internal_pilot_enabled():
        return False
    try:
        UUID(os.environ.get("PMPM_AI_OWNER_USER_ID", "").strip())
    except ValueError:
        return False
    return True


def internal_pilot_enabled() -> bool:
    """Require deliberate opt-in AND safe deployment login defaults."""
    return (
        os.environ.get("PMPM_INTERNAL_AI_PILOT", "").strip().lower() == "true"
        and os.environ.get("REGISTRATION_MODE", "").strip().lower() == "closed"
        and os.environ.get("SEED_DEMO", "").strip().lower() == "false"
    )


def internal_pilot_key_set() -> bool:
    """Configuration status only. The key itself must never reach a response."""
    return internal_pilot_enabled() and bool(os.environ.get("PMPM_INTERNAL_DEEPSEEK_API_KEY", "").strip())


def internal_pilot_credential(settings: Any) -> str | None:
    """Return server-held credential only for an explicitly granted account.

    No settings row, no user id, no grant, unsafe registration mode, or
    missing key means access is denied. This check runs on every resolution,
    not just when the user opens Settings.
    """
    if not internal_pilot_enabled() or settings is None:
        return None
    if not getattr(settings, "user_id", None):
        return None
    meta = getattr(settings, "metadata_", None)
    if not isinstance(meta, dict) or meta.get(ACCESS_FLAG) is not True:
        return None
    return os.environ.get("PMPM_INTERNAL_DEEPSEEK_API_KEY", "").strip() or None
