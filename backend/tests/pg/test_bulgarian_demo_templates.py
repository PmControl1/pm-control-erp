"""Each Bulgarian scenario is a separate, coherent example with real exports."""

from __future__ import annotations

import asyncio
import io
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pypdf
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from openpyxl import load_workbook
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.bulgarian_demo import install_bulgarian_demo
from app.core.demo_marker import live_demo_projects
from app.modules.boq.models import BOQ, Position
from app.modules.boq.pdf_export import generate_boq_pdf
from app.modules.boq.router import _render_boq_xlsx
from app.modules.boq.service import BOQService
from app.modules.documents.models import Document
from app.modules.finance.models import Invoice, Payment, ProjectBudget
from app.modules.finance.schemas import InvoiceResponse
from app.modules.finance.service import FinanceService
from app.modules.projects.models import Project
from app.modules.projects.service import purge_project_children_without_cascade
from app.modules.schedule.models import Activity, Schedule
from app.modules.tendering.models import TenderBid, TenderPackage
from app.modules.tendering.service import TenderingService
from app.modules.users.models import User

from .test_bulgarian_demo import _owner

pytestmark = pytest.mark.asyncio


@dataclass(frozen=True)
class Expected:
    demo_id: str
    name_fragment: str
    city: str
    rows: int
    net: str
    tender: str
    invoice_net: str
    payment: str
    actual: str
    committed: str


# Independent financial checkpoints, not values copied from the implementation
# at test time. A misplaced section or a residential constant must fail here.
EXPECTED = {
    "residential": Expected(
        "pm-bg-plovdiv-v1", "Марица", "Пловдив", 22, "1801140", "303400", "198600", "120000", "182000", "98600"
    ),
    "office-renovation": Expected(
        "pm-bg-office-v1", "Сердика", "София", 21, "251215", "31230", "19312", "11587.20", "23306", "9656"
    ),
    "logistics-warehouse": Expected(
        "pm-bg-warehouse-v1", "Тракия", "Пловдив", 21, "1180730", "244700", "51484", "30890.40", "119642", "25742"
    ),
}


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", "", text).replace(",", ".")


@pytest.mark.parametrize("template_id", list(EXPECTED))
async def test_each_template_has_coherent_exports_tender_payment_and_documents(pg_session, tmp_path, template_id):
    expected = EXPECTED[template_id]
    owner = await _owner(pg_session, role="viewer")
    installed = await install_bulgarian_demo(pg_session, owner.id, template_id=template_id, upload_base=tmp_path)
    project = await pg_session.get(Project, installed.project_id)
    assert expected.name_fragment in project.name
    assert project.address["city"] == expected.city
    assert project.owner_id == owner.id
    assert project.metadata_["demo_id"] == expected.demo_id
    assert project.metadata_["demo_enrichment"] is False
    assert await live_demo_projects(pg_session, [project.id]) == []
    assert Decimal(project.budget_estimate) == Decimal(expected.net)
    assert (project.country_code, project.currency, project.locale) == ("BG", "EUR", "bg")

    boq = await pg_session.scalar(select(BOQ).where(BOQ.project_id == project.id))
    positions = (await pg_session.scalars(select(Position).where(Position.boq_id == boq.id))).all()
    leaves = [position for position in positions if position.unit]
    assert len(leaves) == expected.rows
    assert all(Decimal(row.quantity) * Decimal(row.unit_rate) == Decimal(row.total) for row in leaves)
    assert sum(Decimal(row.total) for row in leaves) == Decimal(expected.net)
    assert all(row.metadata_["demo_id"] == expected.demo_id for row in positions)
    service = BOQService(pg_session)
    structured = await service.get_boq_structured_for_export(boq.id)
    assert len(structured.sections) == 7
    assert sum(Decimal(str(section.subtotal)) for section in structured.sections) == Decimal(expected.net)
    gross = Decimal(expected.net) * Decimal("1.20")
    assert Decimal(str(structured.grand_total)) == gross
    taxes = [markup for markup in structured.markups if markup.category == "tax"]
    assert len(taxes) == 1 and Decimal(taxes[0].percentage) == Decimal("20")

    pdf = generate_boq_pdf(
        structured, project.name, currency="EUR", country_code="BG", locale="bg", base_currency="EUR"
    )
    text = "\n".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)
    assert "КОЛИЧЕСТВЕНО-СТОЙНОСТНА СМЕТКА" in text
    assert expected.name_fragment in text
    assert "Всичко с ДДС" in text
    assert f"{gross:.2f}" in _normalized_text(text)
    xlsx = _render_boq_xlsx(
        await service.get_boq_with_positions(boq.id),
        structured,
        custom_columns=[],
        project_line=project.name,
        base_ccy="EUR",
        fx_map={},
        locale="bg",
    )
    sheet = load_workbook(io.BytesIO(xlsx), data_only=True).active
    assert sheet.title == "КСС"
    rows = list(sheet.iter_rows(values_only=True))
    by_description = {row[1]: row for row in rows if len(row) > 1 and row[1]}
    assert Decimal(str(by_description["Общо за СМР"][5])) == Decimal(expected.net)
    assert Decimal(str(by_description["Всичко с ДДС"][5])) == gross

    package = await pg_session.scalar(select(TenderPackage).where(TenderPackage.project_id == project.id))
    scope = set(package.metadata_["scope_position_ids"])
    scoped_lines = [row for row in leaves if str(row.id) in scope]
    assert len(scope) == len(scoped_lines) == 3
    assert sum(Decimal(row.total) for row in scoped_lines) == Decimal(expected.tender)
    comparison = await TenderingService(pg_session).compare_bids(package.id)
    assert comparison.budget_total == Decimal(expected.tender)
    assert comparison.bid_count == 3 and len(comparison.rows) == 3
    bids = (await pg_session.scalars(select(TenderBid).where(TenderBid.package_id == package.id))).all()
    assert {Decimal(bid.total_amount) for bid in bids} == {
        Decimal(expected.tender) * factor for factor in (Decimal("0.98"), Decimal("1.04"), Decimal("0.96"))
    }
    for bid in bids:
        assert bid.metadata_["demo_id"] == expected.demo_id
        assert {row["position_id"] for row in bid.line_items} == scope
        assert sum(Decimal(row["total"]) for row in bid.line_items) == Decimal(bid.total_amount)
        assert all(
            Decimal(row["quantity"]) * Decimal(row["unit_rate"]) == Decimal(row["total"]) for row in bid.line_items
        )

    invoice = await pg_session.scalar(
        select(Invoice).where(Invoice.project_id == project.id, Invoice.invoice_number == "DEMO-0001")
    )
    response = InvoiceResponse.model_validate(await FinanceService(pg_session).get_invoice(invoice.id))
    assert invoice.metadata_["demo_id"] == expected.demo_id
    assert invoice.status == "approved"
    assert Decimal(response.amount_subtotal) == Decimal(expected.invoice_net)
    assert Decimal(response.tax_amount) == Decimal(expected.invoice_net) * Decimal("0.20")
    assert Decimal(response.amount_total) == Decimal(expected.invoice_net) * Decimal("1.20")
    assert sum(Decimal(line.amount) for line in response.line_items) == Decimal(expected.invoice_net)
    payments = (await pg_session.scalars(select(Payment).where(Payment.invoice_id == invoice.id))).all()
    assert sum(row.amount for row in payments) == Decimal(expected.payment)
    assert all(row.metadata_["demo_id"] == expected.demo_id for row in payments)
    assert invoice.amount_total > sum(row.amount for row in payments)
    budgets = (await pg_session.scalars(select(ProjectBudget).where(ProjectBudget.project_id == project.id))).all()
    assert sum(row.original_budget for row in budgets) == Decimal(expected.net)
    for _ in range(2):
        await FinanceService(pg_session).sync_project_budget(project.id)
        assert sum(row.actual for row in budgets) == Decimal(expected.actual)
        assert sum(row.committed for row in budgets) == Decimal(expected.committed)

    schedule = await pg_session.scalar(select(Schedule).where(Schedule.project_id == project.id))
    activities = (await pg_session.scalars(select(Activity).where(Activity.schedule_id == schedule.id))).all()
    assert len(activities) == 7
    assert all(row.metadata_["demo_id"] == expected.demo_id for row in activities)
    assert set().union(*(set(row.boq_position_ids) for row in activities)) == {str(row.id) for row in leaves}
    docs = (await pg_session.scalars(select(Document).where(Document.project_id == project.id))).all()
    assert len(docs) == 3
    assert all(doc.metadata_["demo_id"] == expected.demo_id for doc in docs)
    documents = {doc.name: Path(doc.file_path).read_text(encoding="utf-8-sig") for doc in docs}
    guide = documents["DEMO-project-guide.txt"]
    assert project.name in guide
    assert expected.net in _normalized_text(guide)
    if template_id != "residential":
        for name, content in documents.items():
            if name.endswith(".txt"):
                assert "Марица" not in content
                normalized = _normalized_text(content)
                assert "1801140" not in normalized
                assert "198600" not in normalized
                assert "238320" not in normalized
                assert "118320" not in normalized


async def test_two_users_have_three_independent_idempotent_examples(pg_session, tmp_path, monkeypatch):
    from app.dependencies import get_current_user_payload, get_session
    from app.modules.documents import service as documents
    from app.modules.projects.router import router

    first, second = await _owner(pg_session, role="viewer"), await _owner(pg_session, role="editor")
    monkeypatch.setattr(documents, "UPLOAD_BASE", tmp_path)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/projects")
    current_user = first

    async def session_override():
        yield pg_session

    async def payload_override():
        return {"sub": str(current_user.id), "role": current_user.role}

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user_payload] = payload_override
    projects = {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for owner in (first, second):
            current_user = owner
            for template_id in EXPECTED:
                response = await client.post("/api/v1/projects/demo/bulgaria", json={"template_id": template_id})
                assert response.status_code == 200, response.text
                assert response.json()["template_id"] == template_id
                projects[owner.id, template_id] = uuid.UUID(response.json()["project_id"])
        assert len(set(projects.values())) == 6
        for (owner_id, template_id), project_id in projects.items():
            current_user = first if owner_id == first.id else second
            project = await pg_session.get(Project, project_id)
            project.name += " — edited"
            await pg_session.flush()
            again = await client.post("/api/v1/projects/demo/bulgaria", json={"template_id": template_id})
            assert again.status_code == 200, again.text
            assert again.json()["already_installed"] and again.json()["project_id"] == str(project_id)
            assert again.json()["project_name"].endswith(" — edited")
            assert project.owner_id == owner_id
            assert project.metadata_["demo_id"] == EXPECTED[template_id].demo_id
            other_id = second.id if owner_id == first.id else first.id
            other_project = projects[other_id, template_id]
            assert (await client.get(f"/api/v1/projects/{other_project}")).status_code == 404
        current_user = first
        default = await client.post("/api/v1/projects/demo/bulgaria")
        assert default.status_code == 200, default.text
        assert default.json()["project_id"] == str(projects[first.id, "residential"])
        assert default.json()["template_id"] == "residential"
    assert await pg_session.scalar(select(func.count()).select_from(Project)) == 6
    assert len(list(tmp_path.rglob("*.csv"))) == 6


@pytest.mark.parametrize("template_id", ["", "unknown", "residential-sofia"])
async def test_invalid_template_request_writes_nothing(pg_session, tmp_path, monkeypatch, template_id):
    from app.dependencies import get_current_user_payload, get_session
    from app.modules.documents import service as documents
    from app.modules.projects.router import router

    owner = await _owner(pg_session, role="viewer")
    monkeypatch.setattr(documents, "UPLOAD_BASE", tmp_path)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/projects")

    async def session_override():
        yield pg_session

    async def payload_override():
        return {"sub": str(owner.id), "role": "viewer"}

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user_payload] = payload_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/projects/demo/bulgaria", json={"template_id": template_id})
    assert response.status_code == 422, response.text
    assert await pg_session.scalar(select(func.count()).select_from(Project)) == 0
    assert not list(tmp_path.rglob("*.csv"))


async def test_new_template_rollback_preserves_previously_created_example(pg_session, tmp_path):
    owner = await _owner(pg_session, role="viewer")
    first = await install_bulgarian_demo(pg_session, owner.id, template_id="office-renovation", upload_base=tmp_path)
    original_documents = set(tmp_path.rglob("*.csv")) | set(tmp_path.rglob("*.txt"))
    assert len(original_documents) == 3
    with pytest.raises(RuntimeError, match="cancel second example"):  # noqa: PT012 - exercise transaction rollback
        async with pg_session.begin_nested():
            await install_bulgarian_demo(pg_session, owner.id, template_id="logistics-warehouse", upload_base=tmp_path)
            raise RuntimeError("cancel second example")
    assert set(tmp_path.rglob("*.csv")) | set(tmp_path.rglob("*.txt")) == original_documents
    assert await pg_session.scalar(select(func.count()).select_from(Project)) == 1
    assert await pg_session.get(Project, first.project_id) is not None


async def test_concurrent_templates_do_not_share_data_or_mutate_default(pg_engine, tmp_path):
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        owners = [await _owner(session, role="viewer"), await _owner(session, role="editor")]
        owner_ids = [owner.id for owner in owners]
        await session.commit()

    async def install(owner_id: uuid.UUID, template_id: str):
        async with factory() as session:
            result = await install_bulgarian_demo(session, owner_id, template_id=template_id, upload_base=tmp_path)
            await session.commit()
            project = await session.get(Project, result.project_id)
            assert project.owner_id == owner_id
            assert project.metadata_["demo_id"] == EXPECTED[template_id].demo_id
            assert Decimal(project.budget_estimate) == Decimal(EXPECTED[template_id].net)
            return result.project_id

    try:
        ids = await asyncio.gather(*(install(owner_id, template) for owner_id in owner_ids for template in EXPECTED))
        assert len(set(ids)) == 6
        assert len(list(tmp_path.rglob("*.csv"))) == 6
    finally:
        async with factory() as session:
            ids = list((await session.scalars(select(Project.id).where(Project.owner_id.in_(owner_ids)))).all())
            await purge_project_children_without_cascade(session, ids)
            await session.execute(delete(Project).where(Project.owner_id.in_(owner_ids)))
            await session.execute(delete(User).where(User.id.in_(owner_ids)))
            await session.commit()
