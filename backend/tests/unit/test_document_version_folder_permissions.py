"""Document version metadata and writes obey the document folder permissions."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.folder_permissions_service import grant_permission
from app.modules.documents.models import Document
from app.modules.file_versions import router
from app.modules.file_versions.models import FileVersion
from app.modules.file_versions.schemas import FileVersionCreate
from app.modules.file_versions.service import FileVersionService
from app.modules.projects.models import Project
from app.modules.teams.models import Team, TeamMembership
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.tenant_isolation


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


@dataclass
class World:
    owner: User
    viewer: User
    member: User
    editor: User
    project: Project
    foreign_project: Project
    contract: Document
    drawing: Document
    foreign_document: Document
    contract_version: FileVersion
    drawing_version: FileVersion


async def _user(session: AsyncSession) -> User:
    user = User(
        email=f"version-{uuid.uuid4().hex}@example.com", hashed_password="x", full_name="Version user", role="editor"
    )
    session.add(user)
    await session.flush()
    return user


async def _document(
    session: AsyncSession, project: Project, owner: User, category: str, *, name: str | None = None
) -> Document:
    document = Document(
        project_id=project.id,
        name=name or f"version-{uuid.uuid4().hex}.pdf",
        category=category,
        file_size=0,
        file_path="",
        uploaded_by=str(owner.id),
    )
    session.add(document)
    await session.flush()
    return document


def _payload(document: Document, **overrides: object) -> FileVersionCreate:
    values = {
        "project_id": document.project_id,
        "file_kind": "document",
        "file_id": str(document.id),
        "canonical_name": document.name,
        "notes": "confidential revision terms",
    }
    values.update(overrides)
    return FileVersionCreate.model_validate(values)


@pytest_asyncio.fixture
async def world(session: AsyncSession) -> World:
    owner, viewer, member, editor = [await _user(session) for _ in range(4)]
    project = Project(name=f"Versions {uuid.uuid4().hex}", owner_id=owner.id)
    foreign_project = Project(name=f"Foreign {uuid.uuid4().hex}", owner_id=owner.id)
    session.add_all([project, foreign_project])
    await session.flush()
    team = Team(project_id=project.id, name="Default", is_default=True)
    session.add(team)
    await session.flush()
    session.add_all([TeamMembership(team_id=team.id, user_id=user.id) for user in (viewer, member, editor)])
    await session.flush()
    for user, role in ((viewer, "viewer"), (editor, "editor")):
        await grant_permission(
            session,
            project_id=project.id,
            user_id=user.id,
            scope_kind="document",
            scope_path="contract",
            role=role,
            granted_by=owner.id,
        )
    contract = await _document(session, project, owner, "contract")
    drawing = await _document(session, project, owner, "drawing")
    foreign_document = await _document(session, foreign_project, owner, "drawing")
    service = FileVersionService(session)
    contract_version = await service.register_new_version(_payload(contract), uploaded_by_id=owner.id)
    drawing_version = await service.register_new_version(_payload(drawing), uploaded_by_id=owner.id)
    return World(
        owner,
        viewer,
        member,
        editor,
        project,
        foreign_project,
        contract,
        drawing,
        foreign_document,
        contract_version,
        drawing_version,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list", "get"])
async def test_restricted_version_metadata_is_not_readable_by_an_ungranted_member(
    session: AsyncSession, world: World, operation: str
) -> None:
    service = FileVersionService(session)
    request = (
        router.list_versions(
            session=session,
            user_id=str(world.member.id),
            file_id=str(world.contract.id),
            kind="document",
            service=service,
        )
        if operation == "list"
        else router.get_version(
            world.contract_version.id, session=session, user_id=str(world.member.id), service=service
        )
    )
    with pytest.raises(HTTPException) as denied:
        await request
    assert denied.value.status_code == 404


@pytest.mark.asyncio
async def test_a_folder_viewer_can_read_version_notes(session: AsyncSession, world: World) -> None:
    service = FileVersionService(session)
    rows = await router.list_versions(
        session=session,
        user_id=str(world.viewer.id),
        file_id=str(world.contract.id),
        kind="document",
        service=service,
    )
    detail = await router.get_version(
        world.contract_version.id, session=session, user_id=str(world.viewer.id), service=service
    )
    assert [row.id for row in rows] == [world.contract_version.id]
    assert detail.notes == "confidential revision terms"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "restore"])
async def test_a_folder_viewer_cannot_change_version_history(
    session: AsyncSession, world: World, operation: str
) -> None:
    service = FileVersionService(session)
    request = (
        router.create_version(_payload(world.contract), session, str(world.viewer.id), service)
        if operation == "create"
        else router.restore_version(world.contract_version.id, session, str(world.viewer.id), service)
    )
    with pytest.raises(HTTPException) as denied:
        await request
    assert denied.value.status_code == 404
    assert [row.id for row in await service.list_for_file(file_id=str(world.contract.id), file_kind="document")] == [
        world.contract_version.id
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("user_role", ["owner", "editor"])
async def test_document_writers_can_register_and_restore_versions(
    session: AsyncSession, world: World, user_role: str
) -> None:
    service = FileVersionService(session)
    user = getattr(world, user_role)
    new = await router.create_version(_payload(world.contract), session, str(user.id), service)
    assert new.version_number == 2 and new.is_current
    restored = await router.restore_version(world.contract_version.id, session, str(user.id), service)
    assert restored.id == world.contract_version.id and restored.is_current


@pytest.mark.asyncio
async def test_open_folder_version_writes_still_work_for_members(session: AsyncSession, world: World) -> None:
    new = await router.create_version(
        _payload(world.drawing), session, str(world.member.id), FileVersionService(session)
    )
    assert new.version_number == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_file_id", ["malformed", "missing", "foreign"])
async def test_registering_a_version_requires_a_real_document_in_the_claimed_project(
    session: AsyncSession, world: World, bad_file_id: str
) -> None:
    file_id = {
        "malformed": "not-a-document-uuid",
        "missing": str(uuid.uuid4()),
        "foreign": str(world.foreign_document.id),
    }[bad_file_id]
    with pytest.raises(HTTPException) as denied:
        await router.create_version(
            _payload(world.drawing, file_id=file_id), session, str(world.member.id), FileVersionService(session)
        )
    assert denied.value.status_code == 404


@pytest.mark.asyncio
async def test_an_open_document_cannot_be_used_to_read_or_change_a_restricted_historical_chain(
    session: AsyncSession, world: World
) -> None:
    service = FileVersionService(session)
    # Normal uploads key history by name, so two folders can share a chain.
    open_copy = await _document(session, world.project, world.owner, "drawing", name=world.contract.name)
    current = await service.register_new_version(_payload(open_copy), uploaded_by_id=world.owner.id)
    with pytest.raises(HTTPException) as denied_read:
        await router.list_versions(
            session=session,
            user_id=str(world.member.id),
            file_id=str(open_copy.id),
            kind="document",
            service=service,
        )
    assert denied_read.value.status_code == 404
    with pytest.raises(HTTPException) as denied_create:
        await router.create_version(_payload(open_copy), session, str(world.member.id), service)
    assert denied_create.value.status_code == 404
    with pytest.raises(HTTPException) as denied_restore:
        await router.restore_version(current.id, session, str(world.member.id), service)
    assert denied_restore.value.status_code == 404


@pytest.mark.asyncio
async def test_an_explicit_previous_version_must_belong_to_the_same_document_chain(
    session: AsyncSession, world: World
) -> None:
    with pytest.raises(HTTPException) as denied:
        await router.create_version(
            _payload(world.drawing, previous_version_id=world.contract_version.id),
            session,
            str(world.owner.id),
            FileVersionService(session),
        )
    assert denied.value.status_code == 404


@pytest.mark.asyncio
async def test_deleted_historical_uploads_do_not_block_the_live_document_chain(
    session: AsyncSession, world: World
) -> None:
    service = FileVersionService(session)
    current_document = await _document(session, world.project, world.owner, "drawing", name=world.drawing.name)
    current = await service.register_new_version(_payload(current_document), uploaded_by_id=world.owner.id)
    deleted_version_id = world.drawing_version.id
    await session.delete(world.drawing)
    await session.flush()

    rows = await router.list_versions(
        session=session,
        user_id=str(world.member.id),
        file_id=str(current_document.id),
        kind="document",
        service=service,
    )
    assert [row.id for row in rows] == [current.id]
    with pytest.raises(HTTPException) as denied_get:
        await router.get_version(deleted_version_id, session, str(world.member.id), service)
    assert denied_get.value.status_code == 404
    with pytest.raises(HTTPException) as denied_restore:
        await router.restore_version(deleted_version_id, session, str(world.member.id), service)
    assert denied_restore.value.status_code == 404

    created = await router.create_version(_payload(current_document), session, str(world.member.id), service)
    assert created.version_number == 3 and created.is_current
    restored = await router.restore_version(current.id, session, str(world.member.id), service)
    assert restored.id == current.id and restored.is_current


@pytest.mark.asyncio
async def test_non_document_versions_keep_project_level_access(session: AsyncSession, world: World) -> None:
    service = FileVersionService(session)
    payload = FileVersionCreate(
        project_id=world.project.id,
        file_kind="photo",
        file_id="photo-row-id",
        canonical_name=f"photo-{uuid.uuid4().hex}",
    )
    created = await router.create_version(payload, session, str(world.member.id), service)
    detail = await router.get_version(created.id, session, str(world.member.id), service)
    assert detail.file_kind == "photo"
