"""Restricted matches must not crowd readable records out of search.

Use more restricted matches than the old fourfold over-fetch, then exercise
global search, both file-search modes, and both unified-search tracks. The
retrievers are controlled where necessary to make candidate order explicit;
the folder permission decisions use the real PostgreSQL-backed service.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cost_scope
from app.core.global_search import global_search
from app.core.vector_index import COLLECTION_DOCUMENTS, VectorHit
from app.modules.contacts.models import Contact
from app.modules.costs.models import CostCatalog, CostItem
from app.modules.documents.folder_permissions_service import grant_permission
from app.modules.documents.models import Document
from app.modules.file_search import service as file_search
from app.modules.file_search.models import FileSearchIndex
from app.modules.file_search.schemas import SearchHit
from app.modules.projects.models import Project
from app.modules.search import service as unified_search
from app.modules.teams.models import Team, TeamMembership
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession) -> User:
    user = User(email=f"paging-{uuid.uuid4().hex}@example.com", hashed_password="x", role="editor")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def world(session: AsyncSession) -> SimpleNamespace:
    owner, reader, grantee = [await _user(session) for _ in range(3)]
    project = Project(name="Search pages", owner_id=owner.id)
    session.add(project)
    await session.flush()
    team = Team(project_id=project.id, name="Default", is_default=True)
    session.add(team)
    await session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=reader.id))
    await session.flush()
    await grant_permission(
        session,
        project_id=project.id,
        user_id=grantee.id,
        scope_kind="document",
        scope_path="contract",
        role="viewer",
        granted_by=owner.id,
    )
    query = f"page{uuid.uuid4().hex}"
    # Stable UUID order puts every hidden row before the readable ones in
    # global search; recency does the same for the unified SQL retriever.
    base = (uuid.uuid4().int >> 16) << 16
    now = datetime.now(UTC)
    hidden = [
        Document(
            id=uuid.UUID(int=base + i),
            project_id=project.id,
            name=f"{query} hidden {i}",
            category="contract",
            file_size=1,
            file_path="",
            uploaded_by=str(owner.id),
            created_at=now + timedelta(seconds=i),
        )
        for i in range(65)
    ]
    readable = [
        Document(
            id=uuid.UUID(int=base + 100 + i),
            project_id=project.id,
            name=f"{query} readable {i}",
            category="drawing",
            file_size=1,
            file_path="",
            uploaded_by=str(owner.id),
            created_at=now - timedelta(days=1, seconds=i),
        )
        for i in range(2)
    ]
    session.add_all([*hidden, *readable])
    await session.flush()
    return SimpleNamespace(project=project, reader=reader, hidden=hidden, readable=readable, query=query)


@pytest.mark.asyncio
async def test_user_without_projects_can_find_own_contacts_and_costs(session: AsyncSession) -> None:
    user, other = [await _user(session) for _ in range(2)]
    query = f"noproject{uuid.uuid4().hex}"
    own = Contact(contact_type="client", company_name=query, created_by=str(user.id))
    foreign = Contact(contact_type="client", company_name=query, created_by=str(other.id))
    catalog = CostCatalog(name=query, currency="EUR", created_by=user.id)
    session.add_all([own, foreign, catalog])
    await session.flush()
    item = CostItem(code=query, description=query, unit="m2", rate="1", currency="EUR", catalog_id=catalog.id)
    session.add(item)
    await session.flush()

    with cost_scope.caller_scope(user.id):
        results = await global_search(
            session,
            query,
            user_id=str(user.id),
            project_ids=set(),
            may_read=lambda p: p in {"contacts.read", "costs.read"},
            contact_owner=str(user.id),
        )

    assert {(r["module"], r["id"]) for r in results} == {("contacts", str(own.id)), ("costs", str(item.id))}


@pytest.mark.asyncio
async def test_global_search_reads_past_restricted_pages(session: AsyncSession, world: SimpleNamespace) -> None:
    results = await global_search(
        session,
        world.query,
        user_id=str(world.reader.id),
        project_ids={world.project.id},
        may_read=lambda p: p == "documents.read",
        contact_owner=str(world.reader.id),
        limit=2,
    )
    assert {r["id"] for r in results} == {str(doc.id) for doc in world.readable}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["content", "filename"])
async def test_file_search_expands_until_readable_hits_survive(
    session: AsyncSession, world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    docs = [*world.hidden, *world.readable]
    requested: list[int] = []

    async def content_candidates(_session, _project_id, _q, _kind, limit):  # type: ignore[no-untyped-def]
        requested.append(limit)
        return [
            FileSearchIndex(
                project_id=world.project.id, file_kind="document", file_id=str(doc.id), content_text=world.query
            )
            for doc in docs[:limit]
        ]

    async def filename_candidates(_session, _project_id, _q, _kind, limit):  # type: ignore[no-untyped-def]
        requested.append(limit)
        return [
            SearchHit(file_id=str(doc.id), kind="document", canonical_name=doc.name, snippet=doc.name, score=1.0)
            for doc in docs[:limit]
        ]

    monkeypatch.setattr(file_search, "_content_search_postgres", content_candidates)
    monkeypatch.setattr(file_search, "_content_search_sqlite", content_candidates)
    monkeypatch.setattr(file_search, "_search_by_filename", filename_candidates)
    hits = await file_search.search_content(
        session, world.project.id, world.query, mode=mode, limit=2, user_id=world.reader.id
    )
    assert {hit.file_id for hit in hits} == {str(doc.id) for doc in world.readable}
    assert max(requested) > 8


@pytest.mark.asyncio
@pytest.mark.parametrize("track", ["sql", "vector"])
async def test_unified_search_fills_after_folder_filtering(
    session: AsyncSession, world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, track: str
) -> None:
    requested: list[int] = []

    @asynccontextmanager
    async def same_session():  # type: ignore[no-untyped-def]
        yield session

    async def vectors(_collection, _query, *, limit, **_kwargs):  # type: ignore[no-untyped-def]
        requested.append(limit)
        if track == "sql":
            return []
        return [
            VectorHit(
                id=str(doc.id),
                score=1.0,
                text=doc.name,
                module="documents",
                project_id=str(world.project.id),
                tenant_id="",
                collection=COLLECTION_DOCUMENTS,
            )
            for doc in [*world.hidden, *world.readable][:limit]
        ]

    async def no_sql(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return []

    monkeypatch.setattr(unified_search, "async_session_factory", same_session)
    monkeypatch.setattr(unified_search, "search_collection", vectors)
    if track == "vector":
        monkeypatch.setattr(unified_search, "_sql_search_collection", no_sql)

    result = await unified_search.unified_search_service(
        world.query, user_id=str(world.reader.id), types=["documents"], limit_per_collection=2
    )
    assert {hit.id for hit in result.hits} == {str(doc.id) for doc in world.readable}
    if track == "vector":
        assert max(requested) > 8


@pytest.mark.asyncio
async def test_no_readable_candidates_exhausts_without_looping(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = [SimpleNamespace(id=str(i)) for i in range(9)]
    requested: list[int] = []

    async def fetch(limit: int) -> list:
        requested.append(limit)
        return candidates[:limit]

    async def deny_all(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return [[]]

    monkeypatch.setattr(unified_search, "_drop_unreadable_document_hits", deny_all)
    assert (
        await unified_search._fill_readable_document_ranking(None, "reader", fetch, limit=2, allowed_project_ids=None)
        == []
    )
    assert requested == [2, 4, 8, 16]
