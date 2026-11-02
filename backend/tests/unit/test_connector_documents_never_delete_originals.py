"""Deleting a watched-folder document never deletes the user's original.

A sync used to create a Document whose ``file_path`` was the file in the
watched folder itself, so deleting that document in the app unlinked the
original there (a Dropbox folder, a shared drive). Now a sync copies each file
into managed storage and the document owns only the copy; and the delete path
refuses to unlink anything under the watched folders, which also protects
documents imported before the change.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.connectors import service as connectors_service
from app.modules.connectors.service import CONNECTOR_META_KEY, ConnectorService
from app.modules.documents import service as documents_service
from app.modules.documents.models import Document
from app.modules.documents.service import DocumentService, _remove_file
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest.fixture
def watched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A watched-folder base dir and a separate managed upload dir, both temporary."""
    base = tmp_path / "watched"
    base.mkdir()
    monkeypatch.setenv("OE_CONNECTORS_BASE_DIR", str(base))
    monkeypatch.setattr(documents_service, "UPLOAD_BASE", tmp_path / "uploads")
    return base


async def _project(session: AsyncSession) -> tuple[User, Project]:
    user = User(email=f"orig-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="O", role="admin")
    session.add(user)
    await session.flush()
    project = Project(name=f"Orig {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(project)
    await session.flush()
    return user, project


async def _sync(session: AsyncSession, project: Project, user: User, root: Path) -> dict:
    service = ConnectorService(session)
    source = await service.create_source(project_id=project.id, name="Dropbox", root_path=str(root))
    return await service.sync_source(source, user_id=str(user.id))


async def _only_document(session: AsyncSession, project: Project) -> Document:
    (doc,) = (await session.execute(select(Document).where(Document.project_id == project.id))).scalars().all()
    return doc


@pytest.mark.asyncio
async def test_a_synced_document_holds_its_own_copy(session: AsyncSession, watched: Path, tmp_path: Path) -> None:
    user, project = await _project(session)
    original = watched / "КСС обект 7.xlsx"
    original.write_bytes(b"synthetic bill")

    result = await _sync(session, project, user, watched)

    assert result["created"] == 1 and result["failed"] == []
    doc = await _only_document(session, project)
    stored = Path(doc.file_path)
    assert stored != original
    assert stored.is_relative_to(tmp_path / "uploads" / str(project.id))
    assert stored.read_bytes() == b"synthetic bill"
    assert doc.file_size == len(b"synthetic bill")
    # Dedup still keys on the original's path.
    assert doc.metadata_[CONNECTOR_META_KEY]["external_id"] == str(original)


@pytest.mark.asyncio
async def test_resync_after_copying_still_creates_nothing(session: AsyncSession, watched: Path) -> None:
    user, project = await _project(session)
    (watched / "a.txt").write_text("one")
    service = ConnectorService(session)
    source = await service.create_source(project_id=project.id, name="Dropbox", root_path=str(watched))
    await service.sync_source(source, user_id=str(user.id))

    again = await service.sync_source(source, user_id=str(user.id))

    assert again["created"] == 0
    assert again["already_known"] == 1


@pytest.mark.asyncio
async def test_deleting_a_synced_document_keeps_the_original(session: AsyncSession, watched: Path) -> None:
    user, project = await _project(session)
    original = watched / "drawing.pdf"
    original.write_bytes(b"%PDF-1.4 synthetic")
    await _sync(session, project, user, watched)
    doc = await _only_document(session, project)
    copy = Path(doc.file_path)

    await DocumentService(session).delete_document(doc.id, str(user.id))

    assert original.read_bytes() == b"%PDF-1.4 synthetic"
    assert not copy.exists()


@pytest.mark.asyncio
async def test_a_document_imported_before_the_change_keeps_its_original(session: AsyncSession, watched: Path) -> None:
    # Rows created by earlier versions point straight at the original.
    user, project = await _project(session)
    original = watched / "old-import.docx"
    original.write_bytes(b"synthetic")
    doc = Document(
        project_id=project.id,
        name=original.name,
        category="other",
        file_size=9,
        file_path=str(original),
        uploaded_by=str(user.id),
        metadata_={CONNECTOR_META_KEY: {"source": "Dropbox", "external_id": str(original)}},
    )
    session.add(doc)
    await session.flush()

    await DocumentService(session).delete_document(doc.id, str(user.id))

    assert original.exists()
    assert (await session.execute(select(Document).where(Document.id == doc.id))).scalar_one_or_none() is None


def test_file_removal_refuses_anything_in_the_watched_folders(watched: Path, tmp_path: Path) -> None:
    inside = watched / "sub" / "original.txt"
    inside.parent.mkdir()
    inside.write_text("keep me")
    managed = tmp_path / "uploads" / "p" / "abc_upload.txt"
    managed.parent.mkdir(parents=True)
    managed.write_text("ours")

    _remove_file(str(inside))
    _remove_file(str(managed))

    assert inside.exists(), "an original in a watched folder was deleted"
    assert not managed.exists(), "a managed upload must still be removable"


def test_file_removal_ignores_a_document_without_a_file() -> None:
    _remove_file(None)
    _remove_file("")


@pytest.mark.asyncio
async def test_a_file_that_cannot_be_copied_is_reported_and_retried(
    session: AsyncSession, watched: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, project = await _project(session)
    original = watched / "locked.xlsx"
    original.write_bytes(b"synthetic original")
    service = ConnectorService(session)
    source = await service.create_source(project_id=project.id, name="Dropbox", root_path=str(watched))

    real_copy = connectors_service.shutil.copyfile

    def _fail(src: Path, dst: Path) -> None:
        # Disk and read errors can happen after a destination was created.
        Path(dst).write_bytes(b"partial")
        raise OSError("copy interrupted")

    monkeypatch.setattr(connectors_service.shutil, "copyfile", _fail)
    for _ in range(2):
        failed = await service.sync_source(source, user_id=str(user.id))
        assert failed["created"] == 0
        assert failed["failed"] == [{"name": "locked.xlsx", "error": "could_not_copy"}]
        assert source.last_result["failed"] == 1
        assert list((documents_service.UPLOAD_BASE / str(project.id)).iterdir()) == []
        assert original.read_bytes() == b"synthetic original"

    monkeypatch.setattr(connectors_service.shutil, "copyfile", real_copy)
    second = await service.sync_source(source, user_id=str(user.id))
    assert second["created"] == 1


def test_a_copy_whose_size_cannot_be_read_is_removed(watched: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = watched / "size-error.txt"
    original.write_bytes(b"synthetic original")
    project_id = uuid.uuid4()
    upload_dir = documents_service.UPLOAD_BASE / str(project_id)
    real_stat = Path.stat

    def _fail_stored_stat(path: Path, *args: object, **kwargs: object):
        if path.parent == upload_dir:
            raise OSError("cannot read copied file size")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _fail_stored_stat)
    with pytest.raises(OSError, match="cannot read copied file size"):
        connectors_service._copy_into_managed_storage(original, project_id)

    assert list(upload_dir.iterdir()) == []
    assert original.read_bytes() == b"synthetic original"
