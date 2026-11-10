# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Marketplace registry - static catalog of installable PM Project Management modules.

Provides a browsable catalog of add-ons: cost databases, vector indices,
language packs, CAD converters, analytics, and integrations. Each entry
carries metadata for the frontend marketplace UI.

The ``installed`` field is computed at runtime by checking which modules
the :class:`~app.core.module_loader.ModuleLoader` has already loaded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.converter_source import PACKAGES
from app.core.demo_seed import seed_demo_enabled
from app.core.market_profile import MARKET_COST_REGION
from app.core.module_loader import module_loader

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketplaceModule:
    """Metadata for a single marketplace entry."""

    id: str  # e.g. "cwicr-bg-sofia"
    name: str  # "Bulgarian Reference Costs (Sofia)"
    description: str  # Detailed blurb
    category: str  # cost_database | vector_index | language | converter | analytics | integration
    icon: str  # lucide-react icon name
    version: str  # SemVer
    size_mb: float  # Estimated download size
    author: str  # Publisher
    tags: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)  # Module dependencies
    price: str = "Free"  # "Free" | "Pro" | "$9.99/mo"

    def to_dict(self, *, installed: bool, coming_soon: bool = False) -> dict:
        """Serialize to a JSON-friendly dict with runtime ``installed`` flag."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "version": self.version,
            "size_mb": self.size_mb,
            "author": self.author,
            "tags": list(self.tags),
            "requires": list(self.requires),
            "installed": installed,
            "price": self.price,
            "coming_soon": coming_soon,
        }


# ---------------------------------------------------------------------------
# Registry - all available marketplace modules
# ---------------------------------------------------------------------------

_DDC = "Data Driven Construction"
_OE = "OpenConstructionERP Core Team"

# Only product-market stock data is offered here. The shared registries and
# import engines still resolve historical records and customer-supplied data.
MARKETPLACE_MODULES: list[MarketplaceModule] = [
    MarketplaceModule(
        id="cwicr-bg-sofia",
        name="Bulgarian Reference Costs (Sofia)",
        description="Bulgarian-language construction reference costs for Sofia. Source rates are in BGN; EUR projects use the existing fixed-rate conversion. Review and update rates for each project.",
        category="cost_database",
        icon="Database",
        version="2.0.0",
        size_mb=60.0,
        author=_DDC,
        tags=["Bulgaria", "Sofia", "BGN", "EUR"],
        requires=["oe_costs"],
    ),
    MarketplaceModule(
        id="catalog-bg-sofia",
        name="Bulgarian Resource Catalogue (Sofia)",
        description="Materials, equipment and labour from the Sofia reference catalogue. Keeps source-currency rates for conversion in project calculations.",
        category="resource_catalog",
        icon="Boxes",
        version="2.0.0",
        size_mb=2.0,
        author=_DDC,
        tags=["Bulgaria", "Sofia", "BGN"],
        requires=["oe_catalog"],
    ),
    MarketplaceModule(
        id="lang-bg",
        name="Български (Bulgarian)",
        description="Bundled Bulgarian interface and construction vocabulary. Enabled by default.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.0,
        author=_OE,
        tags=["Bulgarian", "Default"],
    ),
    MarketplaceModule(
        id="lang-en",
        name="English",
        description="English language pack - UI labels, validation messages, cost database descriptions, and report templates.",
        category="language",
        icon="Globe",
        version="1.0.0",
        size_mb=0.12,
        author=_OE,
        tags=["English", "Fallback"],
        price="Free",
    ),
    MarketplaceModule(
        id="converter-dwg",
        name="DWG/DXF Converter",
        description="Import DWG and DXF files. Extracts geometry, layers, blocks, and properties into structured element tables for cost estimation.",
        category="converter",
        icon="FileInput",
        version=PACKAGES["dwg"].version,
        size_mb=round(PACKAGES["dwg"].size_bytes / 1024 / 1024, 1),
        author=_DDC,
        tags=["CAD", "DWG", "DXF"],
        requires=["oe_projects"],
        price="Free",
    ),
    MarketplaceModule(
        id="converter-rvt",
        name="RVT Parser",
        description="Native RVT file parser. No proprietary CAD vendor license required. Extracts families, parameters, quantities, and spatial structure.",
        category="converter",
        icon="FileInput",
        version=PACKAGES["rvt"].version,
        size_mb=round(PACKAGES["rvt"].size_bytes / 1024 / 1024, 1),
        author=_DDC,
        tags=["BIM", "RVT"],
        requires=["oe_projects"],
        price="Free",
    ),
    MarketplaceModule(
        id="converter-ifc",
        name="IFC Import",
        description="Import IFC 2x3 and IFC4 files. Maps IFC entities to structured element tables with full property set extraction and spatial decomposition.",
        category="converter",
        icon="FileInput",
        version=PACKAGES["ifc"].version,
        size_mb=round(PACKAGES["ifc"].size_bytes / 1024 / 1024, 1),
        author=_DDC,
        tags=["BIM", "IFC", "buildingSMART"],
        requires=["oe_projects"],
        price="Free",
    ),
    MarketplaceModule(
        id="converter-pdf-ocr",
        name="PDF Takeoff Engine",
        description="AI-powered PDF takeoff with symbol detection, dimension extraction, and area measurement. Recognizes construction drawings and extracts quantities automatically.",
        category="converter",
        icon="FileInput",
        version="0.8.0",
        size_mb=512.0,
        author=_DDC,
        tags=["AI", "PDF", "OCR", "Takeoff"],
        requires=["oe_projects"],
        price="Free",
    ),
    MarketplaceModule(
        id="analytics-co2",
        name="Carbon Calculator (CO2)",
        description="Calculate embodied carbon (CO2e) for BOQ positions using EPD databases. Supports EN 15978 lifecycle stages A1-A5, B, C, D. Generate sustainability reports.",
        category="analytics",
        icon="BarChart3",
        version="1.0.0",
        size_mb=15.8,
        author=_OE,
        tags=["Sustainability", "CO2", "EPD", "EN 15978"],
        requires=["oe_boq", "oe_costs"],
        price="Free",
    ),
    MarketplaceModule(
        id="analytics-benchmarks",
        name="Cost Benchmarks",
        description="Compare estimates with project benchmarks and customer-supplied cost data, with building-type normalization.",
        category="analytics",
        icon="BarChart3",
        version="1.0.0",
        size_mb=42.5,
        author=_DDC,
        tags=["Benchmarks", "Cost Index"],
        requires=["oe_boq", "oe_costs"],
        price="Free",
    ),
    MarketplaceModule(
        id="demo-residential-sofia",
        name="Demo: Residential Building Sofia",
        description="Bulgarian residential sample project with a КСС and ЗУТ category. Available only when sample projects are enabled.",
        category="demo_project",
        icon="Building2",
        version="1.0.0",
        size_mb=0.1,
        author=_DDC,
        tags=["Bulgaria", "Sofia", "EUR", "Residential"],
        requires=[],
    ),
]

# Index by id for fast lookup
_MODULES_BY_ID: dict[str, MarketplaceModule] = {m.id: m for m in MARKETPLACE_MODULES}


def get_marketplace_catalog(
    loaded_catalog_regions: set[str] | None = None,
) -> list[dict]:
    """Return Bulgarian stock add-ons and shared tools with installation status.

    Installed status is determined by:
    - Languages: Bulgarian and English are bundled, always installed
    - Converters: built-in, always installed
    - Analytics: built-in, always installed
    - Integrations: not yet implemented, marked ``coming_soon=True``
    - Cost databases: checked on frontend via /costs/regions
    - Resource catalogs: checked against loaded catalog regions
    - Vector indices: checked on frontend
    - Demo projects: offered only when sample projects are enabled

    Args:
        loaded_catalog_regions: Set of catalog region keys that have been imported
            (e.g. {"BG_SOFIA"}). When provided, the corresponding
            ``resource_catalog`` marketplace entries are marked as installed.
    """
    loaded_names = {name for name in module_loader.loaded_modules}

    # Map catalog module IDs to their corresponding region keys
    _CATALOG_ID_TO_REGION: dict[str, str] = {
        "catalog-bg-sofia": MARKET_COST_REGION,
    }

    _loaded_regions = loaded_catalog_regions or set()

    result: list[dict] = []
    for mod in MARKETPLACE_MODULES:
        if mod.category == "demo_project" and not seed_demo_enabled():
            continue
        installed = False
        coming_soon = False

        if mod.category == "language":
            # Both product-interface languages are bundled with the app
            installed = True
        elif mod.category == "converter":
            # All converters are built-in
            installed = True
        elif mod.category == "analytics":
            # All analytics modules are built-in
            installed = True
        elif mod.category == "integration":
            # Integrations are not yet implemented
            installed = False
            coming_soon = True
        elif mod.category == "demo_project":
            installed = False  # Always installable
        elif mod.category == "cost_database":
            # Will be checked on frontend via /costs/regions
            installed = False
        elif mod.category == "resource_catalog":
            region_key = _CATALOG_ID_TO_REGION.get(mod.id, "")
            installed = region_key in _loaded_regions
        elif mod.category == "vector_index":
            installed = False  # Checked on frontend
        else:
            installed = mod.id in loaded_names

        result.append(mod.to_dict(installed=installed, coming_soon=coming_soon))

    return result


def get_marketplace_module(module_id: str) -> MarketplaceModule | None:
    """Look up an available product add-on; foreign stock ids are absent."""
    mod = _MODULES_BY_ID.get(module_id)
    if mod is not None and mod.category == "demo_project" and not seed_demo_enabled():
        return None
    return mod
