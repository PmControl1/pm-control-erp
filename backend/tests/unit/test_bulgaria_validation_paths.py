"""Imports must use the same linked tender and markup inputs as later validation."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.validation.rules import register_builtin_rules
from app.modules.boq.router import _run_import_validation
from app.modules.validation.service import ValidationModuleService


@pytest.mark.asyncio
async def test_inline_bulgarian_import_checks_the_linked_tender_and_vat(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("IMPORT_INLINE_VALIDATION", "true")
    get_settings.cache_clear()
    register_builtin_rules()
    bill_id, tender_id, project_id, position_id = (uuid.uuid4() for _ in range(4))
    project = SimpleNamespace(
        validation_rule_sets=["boq_quality"], classification_standard="", region="BG", country_code="BG"
    )
    position = SimpleNamespace(
        id=position_id,
        parent_id=None,
        ordinal="1",
        description="Изкоп",
        unit="м3",
        quantity=9,
        unit_rate=100,
        total=900,
        classification={},
        metadata_={},
    )
    tender_position = SimpleNamespace(**{**vars(position), "id": uuid.uuid4(), "quantity": 10, "unit_rate": 0})
    bills = {
        bill_id: SimpleNamespace(project_id=project_id, metadata_={"kss_tender_bill_id": str(tender_id)}),
        tender_id: SimpleNamespace(project_id=project_id, name="Оригинална КС"),
    }

    class Session:
        async def get(self, _model, key):
            return bills.get(key)

        async def execute(self, _query):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [tender_position]))

    class Service:
        async def get_boq_with_positions(self, _key):
            return SimpleNamespace(project_id=project_id, positions=[position])

        async def list_markups(self, _key):
            return [
                SimpleNamespace(
                    id=uuid.uuid4(),
                    name="ДДС",
                    markup_type="percentage",
                    category="tax",
                    percentage=9,
                    fixed_amount=0,
                    apply_to="direct_cost",
                    sort_order=0,
                    is_active=True,
                    scope_position_id=None,
                    overrides_id=None,
                )
            ]

    class ProjectRepository:
        def __init__(self, _session):
            pass

        async def get_by_id(self, _key):
            return project

    async def with_context(_session, _project_id, data):
        return data

    async def proposal_meta(*_args):
        return {}

    monkeypatch.setattr("app.modules.projects.repository.ProjectRepository", ProjectRepository)
    monkeypatch.setattr("app.core.validation.project_context.with_project_context", with_context)
    monkeypatch.setattr("app.modules.boq.router._unreviewed_proposal_meta", proposal_meta)
    try:
        report = await _run_import_validation(bill_id, Service(), Session())
    finally:
        get_settings.cache_clear()
    assert report is not None
    failures = {row["rule_id"] for row in report["results"] if not row["passed"]}
    assert "bulgaria.kss_matches_tender_bill" in failures
    assert "bulgaria.vat_rate" in failures
    assert not any(name.startswith("din276.") for name in failures)


@pytest.mark.asyncio
async def test_service_validation_preserves_scoped_markup_overrides():
    original_id, override_id, section_id = (uuid.uuid4() for _ in range(3))
    markup = SimpleNamespace(
        id=override_id,
        name="ДДС раздел",
        markup_type="percentage",
        category="tax",
        percentage=20,
        fixed_amount=0,
        apply_to="cumulative",
        sort_order=1,
        is_active=True,
        scope_position_id=section_id,
        overrides_id=original_id,
    )

    class Session:
        async def execute(self, _query):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [markup]))

    rows = await ValidationModuleService(Session())._load_boq_markups(uuid.uuid4())
    assert rows[0]["overrides_id"] == str(original_id)
    assert rows[0]["scope_position_id"] == str(section_id)
