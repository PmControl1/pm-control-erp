"""OpenConstructionERP - Bulgaria Construction partner pack (КСС + ДДС + ЗУТ + ЕИК).

This package exports a module-level ``MANIFEST`` instance of
:class:`PartnerPackManifest` referenced from ``pyproject.toml``::

    [project.entry-points."openconstructionerp.partner_packs"]
    bulgaria-bg = "openconstructionerp_bulgaria_bg:MANIFEST"

The OCERP core discovers this entry point at boot, validates the
manifest, and applies the partner overrides (branding, locale,
validation rule sets, onboarding script).
"""

from __future__ import annotations

from .manifest import MANIFEST

__all__ = ["MANIFEST"]
__version__ = "0.1.0"
