"""The explicit Bulgarian walkthrough works without enabling legacy demo seeding."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.bulgarian_demo import DEMO_ID, install_bulgarian_demo
from app.core.demo_marker import live_demo_projects
from app.modules.boq.models import BOQ, Position
from app.modules.boq.service import BOQService
from app.modules.documents.models import Document
from app.modules.finance.models import Invoice, Payment, ProjectBudget
from app.modules.finance.schemas import InvoiceResponse
from app.modules.finance.service import FinanceService
from app.modules.projects.models import Project
from app.modules.schedule.models import Activity, Schedule
from app.modules.teams.models import Team, TeamMembership
from app.modules.tendering.models import TenderBid, TenderPackage
from app.modules.tendering.service import TenderingService
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _owner(session, *, role="admin"):
    user = User(
        id=uuid.uuid4(),
        email=f"demo-owner-{uuid.uuid4().hex}@example.invalid",
        hashed_password="test-only",
        full_name="Demo Owner",
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def test_installs_linked_bulgarian_data_and_read_services(pg_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SEED_DEMO", "false")
    owner = await _owner(pg_session)
    result = await install_bulgarian_demo(pg_session, owner.id, today=date(2026, 11, 12), upload_base=tmp_path)
    project = await pg_session.get(Project, result.project_id)
    assert (project.country_code, project.region, project.locale, project.currency) == ("BG", "BG", "bg", "EUR")
    assert project.owner_id == owner.id
    assert project.validation_rule_sets == ["boq_quality", "bulgaria"]
    assert project.metadata_["demo_id"] == DEMO_ID
    assert await live_demo_projects(pg_session, [project.id]) == []
    assert not result.already_installed
    assert result.template_id == "residential"
    assert await pg_session.scalar(select(func.count()).select_from(User)) == 1

    boq = await pg_session.scalar(select(BOQ).where(BOQ.project_id == project.id))
    positions = (await pg_session.scalars(select(Position).where(Position.boq_id == boq.id))).all()
    lines = [p for p in positions if p.unit]
    assert len(lines) == 22
    assert sum(Decimal(p.total) for p in lines) == Decimal("1801140")
    assert all(Decimal(p.quantity) * Decimal(p.unit_rate) == Decimal(p.total) for p in lines)
    totals = (await BOQService(pg_session).compute_boq_totals([boq.id]))[boq.id]
    assert Decimal(str(totals["direct_cost"])) == Decimal("1801140")
    assert Decimal(str(totals["grand_total"])) == Decimal("2161368")
    budgets = (await pg_session.scalars(select(ProjectBudget).where(ProjectBudget.project_id == project.id))).all()
    assert sum(b.original_budget for b in budgets) == Decimal("1801140")
    assert sum(b.actual for b in budgets) == Decimal("182000")
    assert sum(b.committed for b in budgets) == Decimal("98600")
    await FinanceService(pg_session).sync_project_budget(project.id)
    assert sum(b.actual for b in budgets) == Decimal("182000")
    assert sum(b.committed for b in budgets) == Decimal("98600")

    package = await pg_session.scalar(select(TenderPackage).where(TenderPackage.project_id == project.id))
    comparison = await TenderingService(pg_session).compare_bids(package.id)
    assert comparison.bid_count == 3
    assert comparison.budget_total == Decimal("303400")
    assert len(comparison.rows) == 3
    bids = (await pg_session.scalars(select(TenderBid).where(TenderBid.package_id == package.id))).all()
    assert {Decimal(b.total_amount) for b in bids} == {Decimal("297332"), Decimal("315536"), Decimal("291264")}
    for bid in bids:
        assert sum(Decimal(line["total"]) for line in bid.line_items) == Decimal(bid.total_amount)

    invoice = await pg_session.scalar(
        select(Invoice).where(Invoice.project_id == project.id, Invoice.invoice_number == "DEMO-0001")
    )
    loaded = await FinanceService(pg_session).get_invoice(invoice.id)
    response = InvoiceResponse.model_validate(loaded)
    assert Decimal(response.amount_total) == Decimal("238320")
    assert sum(Decimal(line.amount) for line in response.line_items) == Decimal("198600")
    paid = await pg_session.scalar(select(func.sum(Payment.amount)).where(Payment.invoice_id == invoice.id))
    assert invoice.amount_total - paid == Decimal("118320")
    assert invoice.status == "approved"

    schedule = await pg_session.scalar(select(Schedule).where(Schedule.project_id == project.id))
    activities = (await pg_session.scalars(select(Activity).where(Activity.schedule_id == schedule.id))).all()
    assert len(activities) == 7
    assert {a.status for a in activities} == {"completed", "in_progress", "not_started"}
    assert all(a.start_date <= a.end_date for a in activities)
    docs = (await pg_session.scalars(select(Document).where(Document.project_id == project.id))).all()
    assert len(docs) == 3
    for doc in docs:
        path = tmp_path / doc.file_path
        assert path.is_file()
        assert path.stat().st_size == doc.file_size
        assert "ДЕМО" in path.read_text(encoding="utf-8-sig") or doc.name == "DEMO-KSS.csv"
    team = await pg_session.scalar(select(Team).where(Team.project_id == project.id))
    membership = await pg_session.scalar(select(TeamMembership).where(TeamMembership.team_id == team.id))
    assert membership.user_id == owner.id


async def test_repeated_install_preserves_edits_and_isolates_owners(pg_session, tmp_path):
    owner, other = await _owner(pg_session), await _owner(pg_session)
    first = await install_bulgarian_demo(pg_session, owner.id, upload_base=tmp_path)
    project = await pg_session.get(Project, first.project_id)
    project.name = "Edited example"
    # Existing copies predate the template selector and only carry demo_id.
    project.metadata_ = {"demo_id": DEMO_ID, "custom": "keep this edit"}
    boq = await pg_session.scalar(select(BOQ).where(BOQ.project_id == project.id))
    position = await pg_session.scalar(select(Position).where(Position.boq_id == boq.id, Position.unit != "").limit(1))
    position.unit_rate = "123.45"
    await pg_session.flush()
    again = await install_bulgarian_demo(pg_session, owner.id, upload_base=tmp_path)
    assert again.already_installed and again.project_id == first.project_id
    assert again.project_name == "Edited example" and position.unit_rate == "123.45"
    assert project.metadata_ == {"demo_id": DEMO_ID, "custom": "keep this edit"}
    other_demo = await install_bulgarian_demo(pg_session, other.id, upload_base=tmp_path)
    assert other_demo.project_id != first.project_id
    assert (await pg_session.get(Project, other_demo.project_id)).owner_id == other.id
    assert await pg_session.scalar(select(func.count()).select_from(Project)) == 2


async def test_failure_rolls_back_every_project_record(pg_session, tmp_path, monkeypatch):
    import app.core.bulgarian_demo as demo

    owner = await _owner(pg_session)

    def fail(*args, **kwargs):
        raise RuntimeError("simulated document storage failure")

    monkeypatch.setattr(demo, "_add_documents", fail)
    with pytest.raises(RuntimeError, match="storage failure"):
        async with pg_session.begin_nested():
            await install_bulgarian_demo(pg_session, owner.id, upload_base=tmp_path)
    assert await pg_session.scalar(select(func.count()).select_from(Project)) == 0
    assert await pg_session.scalar(select(func.count()).select_from(BOQ)) == 0
    assert await pg_session.scalar(select(func.count()).select_from(Invoice)) == 0
    assert await pg_session.scalar(select(func.count()).select_from(TenderPackage)) == 0


@pytest.mark.parametrize("role", ["viewer", "editor", "admin"])
async def test_route_allows_every_role_and_uses_current_owner(pg_session, tmp_path, monkeypatch, role):
    from app.dependencies import get_current_user_payload, get_session
    from app.modules.documents import service as documents
    from app.modules.projects.router import router

    owner = await _owner(pg_session, role=role)
    monkeypatch.setattr(documents, "UPLOAD_BASE", tmp_path)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/projects")

    async def session_override():
        yield pg_session

    async def payload_override():
        return {"sub": str(owner.id), "role": role}

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user_payload] = payload_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/projects/demo/bulgaria")
    assert response.status_code == 200, response.text
    project = await pg_session.get(Project, uuid.UUID(response.json()["project_id"]))
    assert project.owner_id == owner.id


async def test_anonymous_request_cannot_install():
    from app.modules.projects.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/projects")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/projects/demo/bulgaria")
    assert response.status_code in (401, 403)


async def test_rollback_removes_downloads_together_with_rows(pg_session, tmp_path):
    owner = await _owner(pg_session)
    with pytest.raises(RuntimeError, match="after install"):  # noqa: PT012 - exercise a transaction rollback
        async with pg_session.begin_nested():
            await install_bulgarian_demo(pg_session, owner.id, upload_base=tmp_path)
            assert list(tmp_path.rglob("*.csv"))
            raise RuntimeError("after install")
    assert not list(tmp_path.rglob("*.csv"))
    assert not list(tmp_path.rglob("*.txt"))
    assert await pg_session.scalar(select(func.count()).select_from(Project)) == 0


async def test_only_shared_team_members_can_read_example(pg_session, tmp_path):
    from app.dependencies import get_current_user_payload, get_session
    from app.modules.projects.router import router

    owner = await _owner(pg_session)
    viewer = await _owner(pg_session, role="viewer")
    result = await install_bulgarian_demo(pg_session, owner.id, upload_base=tmp_path)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/projects")

    async def session_override():
        yield pg_session

    async def payload_override():
        return {"sub": str(viewer.id), "role": "viewer"}

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user_payload] = payload_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        url = f"/api/v1/projects/{result.project_id}"
        assert (await client.get(url)).status_code == 404
        team = await pg_session.scalar(select(Team).where(Team.project_id == result.project_id))
        pg_session.add(TeamMembership(team_id=team.id, user_id=viewer.id, role="viewer"))
        await pg_session.flush()
        response = await client.get(url)
        assert response.status_code == 200, response.text
        assert response.json()["id"] == str(result.project_id)


async def test_archived_example_stays_archived_on_explicit_new_install(pg_session, tmp_path):
    owner = await _owner(pg_session)
    result = await install_bulgarian_demo(pg_session, owner.id, upload_base=tmp_path)
    original = await pg_session.get(Project, result.project_id)
    original.status = "archived"
    await pg_session.flush()
    new = await install_bulgarian_demo(pg_session, owner.id, upload_base=tmp_path)
    assert new.project_id != original.id
    assert original.status == "archived"


async def test_concurrent_requests_install_exactly_one_copy(pg_engine, tmp_path):
    import asyncio

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.modules.projects.service import purge_project_children_without_cascade

    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with factory() as session:
        owner = await _owner(session)
        owner_id = owner.id
        await session.commit()

    async def install():
        async with factory() as session:
            result = await install_bulgarian_demo(session, owner_id, upload_base=tmp_path)
            await session.commit()
            return result

    try:
        first, second = await asyncio.gather(install(), install())
        assert first.project_id == second.project_id
        assert sorted([first.already_installed, second.already_installed]) == [False, True]
        assert len(list(tmp_path.rglob("*.csv"))) == 1
    finally:
        async with factory() as session:
            ids = list((await session.scalars(select(Project.id).where(Project.owner_id == owner_id))).all())
            await purge_project_children_without_cascade(session, ids)
            await session.execute(delete(Project).where(Project.owner_id == owner_id))
            await session.execute(delete(User).where(User.id == owner_id))
            await session.commit()


@pytest.mark.parametrize("account_state", ["inactive", "deleted"])
async def test_inactive_or_deleted_account_cannot_install(pg_session, tmp_path, monkeypatch, account_state):
    from app.dependencies import get_current_user_payload, get_session
    from app.modules.documents import service as documents
    from app.modules.projects.router import router

    owner = await _owner(pg_session, role="viewer")
    if account_state == "inactive":
        owner.is_active = False
    else:
        owner.deleted_at = datetime.now(UTC)
    await pg_session.flush()
    monkeypatch.setattr(documents, "UPLOAD_BASE", tmp_path)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/projects")

    async def session_override():
        yield pg_session

    async def payload_override():
        # Even if a request passed authentication earlier, the installer
        # rechecks the account before looking up or writing demo data.
        return {"sub": str(owner.id), "role": "viewer"}

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user_payload] = payload_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/projects/demo/bulgaria")
    assert response.status_code == 404, response.text
    assert await pg_session.scalar(select(func.count()).select_from(Project)) == 0
    assert not list(tmp_path.rglob("*.csv"))


async def test_two_regular_users_can_open_only_their_own_demo(pg_session, tmp_path, monkeypatch):
    from app.dependencies import get_current_user_payload, get_session
    from app.modules.documents import service as documents
    from app.modules.projects.router import router

    first = await _owner(pg_session, role="viewer")
    second = await _owner(pg_session, role="editor")
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/projects/demo/bulgaria")
        assert response.status_code == 200, response.text
        first_project = response.json()["project_id"]
        current_user = second
        response = await client.post("/api/v1/projects/demo/bulgaria")
        assert response.status_code == 200, response.text
        second_project = response.json()["project_id"]
        assert first_project != second_project
        assert (await client.get(f"/api/v1/projects/{second_project}")).status_code == 200
        assert (await client.get(f"/api/v1/projects/{first_project}")).status_code == 404
        current_user = first
        assert (await client.get(f"/api/v1/projects/{first_project}")).status_code == 200
        assert (await client.get(f"/api/v1/projects/{second_project}")).status_code == 404
        reopened = await client.post("/api/v1/projects/demo/bulgaria")
        assert reopened.json()["project_id"] == first_project
        assert reopened.json()["already_installed"] is True
