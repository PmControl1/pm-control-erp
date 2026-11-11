"""Seeded examples must be readable by the actual module views and exports."""

from __future__ import annotations

import io
from decimal import Decimal

import pypdf
import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.core.bulgarian_demo import install_bulgarian_demo
from app.modules.boq.models import BOQ
from app.modules.boq.pdf_export import generate_boq_pdf
from app.modules.boq.router import _render_boq_xlsx
from app.modules.boq.service import BOQService
from app.modules.fieldreports.models import FieldReport
from app.modules.fieldreports.router import _report_to_response
from app.modules.meetings.models import Meeting
from app.modules.meetings.router import _meeting_to_response
from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem
from app.modules.punchlist.router import _item_to_response
from app.modules.rfi.models import RFI
from app.modules.rfi.router import _to_response as rfi_response
from app.modules.risk.models import RiskItem
from app.modules.risk.router import _risk_to_response
from app.modules.tasks.models import Task
from app.modules.tasks.router import _to_response as task_response

from .test_bulgarian_demo import _owner

pytestmark = pytest.mark.asyncio


async def test_demo_exports_bulgarian_kss_with_tax_and_section_totals(pg_session, tmp_path):
    owner = await _owner(pg_session)
    installed = await install_bulgarian_demo(pg_session, owner.id, upload_base=tmp_path)
    project = await pg_session.get(Project, installed.project_id)
    boq = await pg_session.scalar(select(BOQ).where(BOQ.project_id == project.id))
    service = BOQService(pg_session)
    structured = await service.get_boq_structured_for_export(boq.id)
    assert len(structured.sections) == 7
    assert sum(Decimal(str(section.subtotal)) for section in structured.sections) == Decimal("1801140")
    taxes = [markup for markup in structured.markups if markup.category == "tax"]
    assert len(taxes) == 1 and Decimal(taxes[0].percentage) == Decimal("20")

    pdf = generate_boq_pdf(
        structured, project.name, currency="EUR", country_code="BG", locale="bg", base_currency="EUR"
    )
    text = "\n".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert "КОЛИЧЕСТВЕНО-СТОЙНОСТНА СМЕТКА" in text
    assert "Машинен изкоп и извозване" in text
    assert "Всичко с ДДС" in text
    assert "2 161 368,00" in text.replace("\xa0", " ")

    xlsx = _render_boq_xlsx(
        await service.get_boq_with_positions(boq.id),
        structured,
        custom_columns=[],
        project_line=project.name,
        base_ccy="EUR",
        fx_map={},
        locale="bg",
    )
    workbook = load_workbook(io.BytesIO(xlsx), data_only=True)
    assert workbook.active.title == "КСС"
    rows = list(workbook.active.iter_rows(values_only=True))
    by_description = {row[1]: row for row in rows if len(row) > 1 and row[1]}
    assert by_description["Общо за СМР"][5] == 1801140
    assert by_description["Всичко с ДДС"][5] == 2161368


async def test_site_records_serialize_for_their_module_views(pg_session, tmp_path):
    owner = await _owner(pg_session)
    installed = await install_bulgarian_demo(pg_session, owner.id, upload_base=tmp_path)
    for model, serializer, expected_count in [
        (Task, task_response, 5),
        (RiskItem, _risk_to_response, 2),
        (RFI, rfi_response, 1),
        (PunchItem, _item_to_response, 1),
        (Meeting, _meeting_to_response, 1),
        (FieldReport, _report_to_response, 1),
    ]:
        records = (await pg_session.scalars(select(model).where(model.project_id == installed.project_id))).all()
        assert len(records) == expected_count
        for record in records:
            response = serializer(record)
            assert response.project_id == installed.project_id
            assert response.model_dump(mode="json")["id"] == str(record.id)


async def test_viewer_can_explore_own_demo_bill_but_not_another_users(pg_session, tmp_path):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.dependencies import get_current_user_payload, get_session
    from app.modules.boq.permissions import register_boq_permissions
    from app.modules.boq.router import router

    owner = await _owner(pg_session, role="viewer")
    outsider = await _owner(pg_session, role="viewer")
    installed = await install_bulgarian_demo(pg_session, owner.id, upload_base=tmp_path)
    boq = await pg_session.scalar(select(BOQ).where(BOQ.project_id == installed.project_id))
    register_boq_permissions()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/boq")
    current_id = owner.id

    async def session_override():
        yield pg_session

    async def payload_override():
        return {"sub": str(current_id), "role": "viewer"}

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user_payload] = payload_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        url = f"/api/v1/boq/boqs/{boq.id}/structured/"
        response = await client.get(url)
        assert response.status_code == 200, response.text
        assert Decimal(str(response.json()["grand_total"])) == Decimal("2161368")
        current_id = outsider.id
        assert (await client.get(url)).status_code == 404
