"""Real spreadsheet totals remain checkable after import and euro conversion."""

from __future__ import annotations

import asyncio
import copy
import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openpyxl import load_workbook

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.core.validation.rules.bulgaria_import_totals import BulgarianImportedVatTotals
from app.modules.boq import router as boq_router
from app.modules.boq.importers.bulgaria_kss import convert_to_euro
from app.modules.boq.importers.bulgaria_totals import SOURCE_TOTALS_KEY
from app.modules.boq.importers.excel import ExcelImporter
from app.modules.boq.kss_tender import with_kss_tender_bill
from tests.unit.test_bulgaria_kss_import import _kss


def _parse(*, vat: float | None = None, rate: str | None = None, total: float | None = None):
    wb = load_workbook(io.BytesIO(_kss()))
    sheet = wb.active
    if vat is not None:
        sheet.cell(20, 7, vat)
    if rate is not None:
        sheet.cell(20, 3, f"ДДС {rate}%")
    if total is not None:
        sheet.cell(21, 7, total)
    content = io.BytesIO()
    wb.save(content)
    return asyncio.run(ExcelImporter.parse(content.getvalue(), locale="bg"))


def _run(data):
    return asyncio.run(BulgarianImportedVatTotals().validate(ValidationContext(data=data, metadata={"locale": "bg"})))


def test_registered_for_bulgarian_projects():
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()
    assert BulgarianImportedVatTotals.rule_id in {r["rule_id"] for r in rule_registry.list_rules(rule_set="bulgaria")}


def test_real_workbook_vat_including_contingency_passes():
    imported = _parse()
    source = imported.metadata[SOURCE_TOTALS_KEY]
    assert source["sheet_amounts"] == {"КСС": "208049.93"}
    assert all(result.passed for result in _run(imported.metadata))


def test_source_vat_on_direct_cost_omits_the_contingency_and_fails():
    imported = _parse(vat=37827.26)
    failures = [r for r in _run(imported.metadata) if not r.passed]
    assert failures
    assert failures[0].severity == Severity.ERROR
    assert failures[0].details["expected"] == "41609.99"
    assert failures[0].details["source_spreadsheet"] is True


def test_wrong_source_rate_fails_even_with_correct_amount():
    results = _run(_parse(rate="9").metadata)
    assert any(not r.passed and r.details.get("rate") == "9" for r in results)


def test_wrong_source_grand_total_fails():
    results = _run(_parse(total=249000).metadata)
    assert any(not r.passed and r.details.get("row") == 21 for r in results)


def test_source_comparison_keeps_lev_amounts_after_rates_convert_to_euro():
    imported = _parse()
    snapshot = copy.deepcopy(imported.metadata[SOURCE_TOTALS_KEY])
    convert_to_euro(imported, "BGN")
    assert imported.currency == "EUR"
    assert imported.metadata[SOURCE_TOTALS_KEY] == snapshot
    assert all(result.passed for result in _run(imported.metadata))


@pytest.mark.parametrize("case", ["duplicate_tax", "recap", "partial"])
def test_ambiguous_scope_or_partial_parse_needs_review(case):
    imported = _parse()
    source = imported.metadata[SOURCE_TOTALS_KEY]
    if case == "duplicate_tax":
        tax = next(row for row in source["summary_rows"] if row["kind"] == "tax")
        source["summary_rows"].append(dict(tax))
    elif case == "recap":
        source["sheet_amounts"] = {"Работи": "208049.93"}
    else:
        source["partial"] = True
    results = _run(imported.metadata)
    assert len(results) == 1
    assert not results[0].passed and results[0].severity == Severity.WARNING


def test_bill_without_source_snapshot_is_not_claimed_as_checked():
    assert _run({"positions": []}) == []


def test_grand_total_with_dds_but_no_separate_source_tax_row_needs_review():
    imported = _parse()
    source = imported.metadata[SOURCE_TOTALS_KEY]
    source["summary_rows"] = [row for row in source["summary_rows"] if row["kind"] != "tax"]
    results = _run(imported.metadata)
    assert len(results) == 1
    assert not results[0].passed and results[0].severity == Severity.WARNING


def test_both_validation_paths_helper_adds_source_audit_even_without_tender_link():
    boq_id = uuid.uuid4()
    source = _parse().metadata[SOURCE_TOTALS_KEY]
    bill = SimpleNamespace(metadata_={"last_import": {SOURCE_TOTALS_KEY: source}})

    class Session:
        async def get(self, _model, value):
            assert value == boq_id
            return bill

    original = {"positions": []}
    payload = asyncio.run(with_kss_tender_bill(Session(), boq_id, original))
    assert payload[SOURCE_TOTALS_KEY] is source
    assert original == {"positions": []}


def test_totals_only_reimport_refreshes_source_audit_and_validates(monkeypatch):
    imported = _parse(vat=37827.26)
    boq_id = uuid.uuid4()
    bill = SimpleNamespace(metadata_={"keep": "custom", "last_import": {SOURCE_TOTALS_KEY: {"old": True}}})
    session = SimpleNamespace(flush=AsyncMock(), commit=AsyncMock())
    service = SimpleNamespace(session=session, get_boq=AsyncMock(return_value=bill))
    chosen = SimpleNamespace(format_id="excel")
    monkeypatch.setattr(boq_router, "_parse_with_mapping", AsyncMock(return_value=imported))
    monkeypatch.setattr(boq_router, "_convert_replaced_currency_to_euro", AsyncMock())
    monkeypatch.setattr(
        boq_router,
        "_persist_imported_boq",
        AsyncMock(
            return_value={
                "created": 0,
                "updated": 0,
                "deleted": 0,
                "unchanged": 9,
                "apply_errors": [],
                "would_delete": 0,
                "round_trip": True,
                "problems": [],
            }
        ),
    )
    validate = AsyncMock(return_value={"errors": 1})
    monkeypatch.setattr(boq_router, "_run_import_validation", validate)
    result = asyncio.run(
        boq_router._run_native_import(
            boq_id,
            chosen,
            b"excel",
            file_name="corrected.xlsx",
            overrides=None,
            delete_missing=False,
            actor_id=None,
            service=service,
        )
    )
    assert bill.metadata_["keep"] == "custom"
    assert bill.metadata_["last_import"][SOURCE_TOTALS_KEY] == imported.metadata[SOURCE_TOTALS_KEY]
    assert bill.metadata_["last_import"]["source_filename"] == "corrected.xlsx"
    validate.assert_awaited_once_with(boq_id, service, session)
    assert result["validation_report"] == {"errors": 1}
