"""A restricted folder stays restricted on every path to its documents.

Reading a document's metadata honoured folder permissions, but download,
metadata updates, share links, the activity log, content search, Document
Analyst's retrieval, unified search and global search did not, and global
search was not even scoped to the caller's projects. These tests build one
real project on PostgreSQL and walk each path as four people:

* Olivia owns the project.
* Ivo is a member with a viewer grant on the restricted ``contract`` folder.
* Mia is a member with no grant on it, so she may not see it at all; the
  ``drawing`` folder has no grants and stays open to every member.
* Otto belongs to a different project entirely.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import global_search_router
from app.core.vector_index import COLLECTION_DOCUMENTS, VectorHit
from app.modules.contacts.models import Contact
from app.modules.documents import router as documents_router
from app.modules.documents.access import readable_document_ids, require_document_access
from app.modules.documents.folder_permissions_service import grant_permission
from app.modules.documents.models import Document
from app.modules.documents.service import DocumentService
from app.modules.file_search.models import FileSearchIndex
from app.modules.file_search.service import search_content
from app.modules.projects.models import Project
from app.modules.search.service import _drop_unreadable_document_hits
from app.modules.tasks.models import Task
from app.modules.teams.models import Team, TeamMembership
from app.modules.users.models import User
from tests._pg import transactional_session

WORD = f"zq{uuid.uuid4().hex[:8]}"  # unique per run, so no other row matches


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


@dataclass
class World:
    olivia: User
    ivo: User
    mia: User
    otto: User
    project: Project
    other_project: Project
    contract: Document
    drawing: Document


async def _user(session: AsyncSession, name: str) -> User:
    user = User(email=f"{name}-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", full_name=name, role="editor")
    session.add(user)
    await session.flush()
    return user


async def _document(session: AsyncSession, project: Project, category: str, owner: User, folder: Path) -> Document:
    path = folder / f"{category}-{WORD}.pdf"
    path.write_bytes(b"%PDF-1.4 synthetic")
    doc = Document(
        project_id=project.id,
        name=f"{category} {WORD}.pdf",
        category=category,
        file_size=18,
        mime_type="application/pdf",
        file_path=str(path),
        uploaded_by=str(owner.id),
    )
    session.add(doc)
    await session.flush()
    return doc


@pytest_asyncio.fixture
async def world(session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    monkeypatch.setattr(documents_router, "UPLOAD_BASE", tmp_path)
    olivia, ivo, mia, otto = [await _user(session, n) for n in ("olivia", "ivo", "mia", "otto")]
    project = Project(name=f"Site {WORD}", owner_id=olivia.id)
    other_project = Project(name=f"Other {WORD}", owner_id=otto.id)
    session.add_all([project, other_project])
    await session.flush()
    team = Team(project_id=project.id, name="Default", is_default=True)
    session.add(team)
    await session.flush()
    session.add_all([TeamMembership(team_id=team.id, user_id=ivo.id), TeamMembership(team_id=team.id, user_id=mia.id)])
    await session.flush()
    # Granting Ivo the contract folder makes it restricted; Mia has no grant.
    await grant_permission(
        session,
        project_id=project.id,
        user_id=ivo.id,
        scope_kind="document",
        scope_path="contract",
        role="viewer",
        granted_by=olivia.id,
    )
    contract = await _document(session, project, "contract", olivia, tmp_path)
    drawing = await _document(session, project, "drawing", olivia, tmp_path)
    return World(olivia, ivo, mia, otto, project, other_project, contract, drawing)


async def _download(session: AsyncSession, doc: Document, user: User):  # type: ignore[no-untyped-def]
    return await documents_router.download_document(
        document_id=doc.id, user_id=str(user.id), session=session, service=DocumentService(session)
    )


# -- download -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_member_without_a_grant_cannot_download_from_a_restricted_folder(
    session: AsyncSession, world: World
) -> None:
    with pytest.raises(HTTPException) as denied:
        await _download(session, world.contract, world.mia)
    assert denied.value.status_code == 404


@pytest.mark.asyncio
async def test_downloads_still_work_for_everyone_who_may_read(session: AsyncSession, world: World) -> None:
    assert (await _download(session, world.drawing, world.mia)).path.endswith(".pdf")  # open folder
    assert (await _download(session, world.contract, world.ivo)).path.endswith(".pdf")  # viewer grant
    assert (await _download(session, world.contract, world.olivia)).path.endswith(".pdf")  # owner


@pytest.mark.asyncio
async def test_a_user_from_another_project_cannot_download(session: AsyncSession, world: World) -> None:
    with pytest.raises(HTTPException) as denied:
        await _download(session, world.drawing, world.otto)
    assert denied.value.status_code == 404


# -- read vs write ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_viewer_may_read_but_not_change_or_share(session: AsyncSession, world: World) -> None:
    assert await require_document_access(session, world.contract, world.ivo.id, "read") == "viewer"
    with pytest.raises(HTTPException) as denied:
        await require_document_access(session, world.contract, world.ivo.id, "write")
    assert denied.value.status_code == 404


@pytest.mark.asyncio
async def test_an_open_folder_member_and_the_owner_may_write(session: AsyncSession, world: World) -> None:
    assert await require_document_access(session, world.drawing, world.mia.id, "write") == "editor"
    assert await require_document_access(session, world.contract, world.olivia.id, "write") == "owner"


@pytest.mark.asyncio
async def test_share_links_cannot_be_minted_without_write_access(session: AsyncSession, world: World) -> None:
    with pytest.raises(HTTPException) as denied:
        await documents_router.create_document_share_link(
            document_id=world.contract.id,
            body=SimpleNamespace(password=None, expires_in_days=7),
            user_id=str(world.mia.id),
            session=session,
            _perm=None,
            service=DocumentService(session),
        )
    assert denied.value.status_code == 404


@pytest.mark.asyncio
async def test_readable_ids_follow_the_folders(session: AsyncSession, world: World) -> None:
    both = [world.contract.id, world.drawing.id, uuid.uuid4(), "not-a-uuid"]
    assert await readable_document_ids(session, world.mia.id, both) == {str(world.drawing.id)}
    assert await readable_document_ids(session, world.ivo.id, both) == {str(world.contract.id), str(world.drawing.id)}
    assert await readable_document_ids(session, world.otto.id, both) == set()


# -- content search, which Document Analyst also reads --------------------------


@pytest.mark.asyncio
async def test_content_search_leaves_out_restricted_documents(session: AsyncSession, world: World) -> None:
    for doc in (world.contract, world.drawing):
        session.add(
            FileSearchIndex(
                project_id=world.project.id,
                file_kind="document",
                file_id=str(doc.id),
                content_text=f"penalty clause {WORD} applies",
                indexed_at=datetime.now(UTC),
            )
        )
    await session.flush()

    def ids(hits: list) -> set[str]:
        return {h.file_id for h in hits}

    assert ids(await search_content(session, world.project.id, WORD, user_id=world.mia.id)) == {str(world.drawing.id)}
    assert ids(await search_content(session, world.project.id, WORD, user_id=world.ivo.id)) == {
        str(world.contract.id),
        str(world.drawing.id),
    }
    # Filename search goes through the same filter.
    by_name = await search_content(session, world.project.id, WORD, mode="filename", user_id=world.mia.id)
    assert str(world.contract.id) not in ids(by_name)


# -- unified search ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_unified_search_drops_restricted_document_hits(session: AsyncSession, world: World) -> None:
    def hit(doc: Document) -> VectorHit:
        return VectorHit(
            id=str(doc.id), score=1.0, text=doc.name, module="documents", project_id=str(doc.project_id), tenant_id=""
        )

    rankings = [[hit(world.contract), hit(world.drawing)]]
    (kept,) = await _drop_unreadable_document_hits(session, str(world.mia.id), [COLLECTION_DOCUMENTS], rankings)
    assert [h.id for h in kept] == [str(world.drawing.id)]


# -- global search ----------------------------------------------------------------


#: What an editor's token carries for the nine searched modules.
READS = [
    f"{m}.read" for m in ("boq", "contacts", "documents", "rfi", "tasks", "costs", "meetings", "inspections", "ncr")
]


async def _global(
    session: AsyncSession,
    user: User,
    *,
    role: str = "editor",
    permissions: list[str] = READS,
    project_id: str | None = None,
) -> list:
    return await global_search_router.search(
        session=session,
        user_id=str(user.id),
        payload={"sub": str(user.id), "role": role, "permissions": permissions},
        q=WORD,
        project_id=project_id,
        limit=50,
    )


@pytest.mark.asyncio
async def test_global_search_stays_inside_the_callers_projects(session: AsyncSession, world: World) -> None:
    session.add(Task(project_id=world.other_project.id, task_type="task", title=f"Other site {WORD}"))
    await session.flush()

    titles = [r["title"] for r in await _global(session, world.mia)]
    assert not any("Other site" in t for t in titles), "a task from a project Mia is not on came back"
    others = [r["title"] for r in await _global(session, world.otto)]
    assert any("Other site" in t for t in others)
    assert not any(r["module"] == "documents" for r in await _global(session, world.otto))


@pytest.mark.asyncio
async def test_global_search_leaves_out_restricted_documents(session: AsyncSession, world: World) -> None:
    docs = {r["id"] for r in await _global(session, world.mia) if r["module"] == "documents"}
    assert docs == {str(world.drawing.id)}
    docs = {r["id"] for r in await _global(session, world.ivo) if r["module"] == "documents"}
    assert docs == {str(world.contract.id), str(world.drawing.id)}


@pytest.mark.asyncio
async def test_global_search_refuses_a_project_the_caller_cannot_access(session: AsyncSession, world: World) -> None:
    with pytest.raises(HTTPException) as denied:
        await _global(session, world.otto, project_id=str(world.project.id))
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as malformed:
        await _global(session, world.otto, project_id="not-a-project")
    assert malformed.value.status_code == 404


@pytest.mark.asyncio
async def test_global_search_only_returns_the_callers_own_contacts(session: AsyncSession, world: World) -> None:
    session.add(Contact(contact_type="client", company_name=f"Acme {WORD}", created_by=str(world.otto.id)))
    await session.flush()

    assert not [r for r in await _global(session, world.mia) if r["module"] == "contacts"]
    assert [r for r in await _global(session, world.otto) if r["module"] == "contacts"]


@pytest.mark.asyncio
async def test_global_search_skips_modules_the_role_may_not_read(session: AsyncSession, world: World) -> None:
    # A role with no read permissions at all sees nothing, even in its own project.
    assert await _global(session, world.olivia, role="no-such-role", permissions=[]) == []
    only_tasks = await _global(session, world.olivia, permissions=["tasks.read"])
    assert {r["module"] for r in only_tasks} <= {"tasks"}
    assert {r["module"] for r in await _global(session, world.olivia)} >= {"documents"}
