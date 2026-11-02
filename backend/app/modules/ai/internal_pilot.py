# PM Project Management internal company AI pilot.
"""Fail-closed, opt-in shared DeepSeek credential for a SINGLE-company install.

There is no Organization/Tenant membership entity in this release. Therefore
this is not a customer-facing SaaS credential feature. Grants are per account,
never inferred from an email domain or admin status. Only the backend sees the
shared key. Standalone personal AI keys remain separate.
"""

from __future__ import annotations

import os
from typing import Any

ACCESS_FLAG = "pmpm_internal_ai_access"


def internal_pilot_enabled() -> bool:
    """Require deliberate opt-in AND safe deployment login defaults."""
    return (
        os.environ.get("PMPM_INTERNAL_AI_PILOT", "").strip().lower() == "true"
        and os.environ.get("REGISTRATION_MODE", "").strip().lower() == "closed"
        and os.environ.get("SEED_DEMO", "").strip().lower() == "false"
    )


def internal_pilot_key_set() -> bool:
    """Configuration status only. The key itself must never reach a response."""
    return internal_pilot_enabled() and bool(
        os.environ.get("PMPM_INTERNAL_DEEPSEEK_API_KEY", "").strip()
    )


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
