"""A program renamed to look like a document is refused by what it is.

The extension gate only reads the name, and the content sniffer returned
"unknown" for programs, which the documents upload lets through as if it were
plain text. So a Windows program called "фактура.pdf" was stored and offered
for download as a PDF. The sniffer now names Windows, Linux and macOS
programs, and the documents and photo uploads refuse them by content.
"""

from __future__ import annotations

import io
import uuid
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from starlette.datastructures import Headers

from app.core.file_signature import BANNED_SIGNATURE_TOKENS, detect
from app.modules.documents import service as documents_service
from app.modules.documents.models import Document, ProjectPhoto
from app.modules.documents.service import DocumentService, PhotoService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

OWNER_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()

# The first bytes of real programs, padded the way a real file continues.
WINDOWS = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + bytes(240)
LINUX = b"\x7fELF\x02\x01\x01\x00" + bytes(248)
MACOS = b"\xcf\xfa\xed\xfe\x0c\x00\x00\x01" + bytes(248)
MACOS_UNIVERSAL = b"\xca\xfe\xba\xbe\x00\x00\x00\x02" + bytes(248)

PROGRAMS = [
    pytest.param(WINDOWS, "exe", id="windows"),
    pytest.param(LINUX, "elf", id="linux"),
    pytest.param(MACOS, "mach-o", id="macos"),
    pytest.param(MACOS_UNIVERSAL, "mach-o", id="macos-universal"),
]


@pytest.mark.parametrize(("content", "token"), PROGRAMS)
def test_a_program_is_named_and_banned(content: bytes, token: str) -> None:
    assert detect(content[:16]) == token
    assert token in BANNED_SIGNATURE_TOKENS


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"MZ;Mazut;Litres\n1;Heating;400\n", id="a csv that starts with MZ"),
        pytest.param(b"MZ is the start of these site notes.\n", id="text that starts with MZ"),
        pytest.param(b"\xca\xfe\xba\xbe\x00\x00\x00\x34" + bytes(8), id="a java class file"),
        pytest.param(b"ELF report: nothing found\n", id="text that says ELF"),
    ],
)
def test_text_that_only_looks_like_a_program_is_not_named_one(content: bytes) -> None:
    assert detect(content[:16]) is None


@pytest.mark.parametrize(
    ("content", "token"),
    [
        (b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", "pdf"),
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "png"),
        (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00", "jpeg"),
        (b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00", "zip"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1\x00\x00\x00\x00", "ole"),
        (b"ISO-10303-21;\nHEADER;", "ifc"),
        (b"AC1032\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00", "dwg"),
        (b"glTF\x02\x00\x00\x00\x00\x00\x00\x00", "glb"),
    ],
)
def test_the_formats_people_upload_are_still_recognised(content: bytes, token: str) -> None:
    assert detect(content[:16]) == token


@pytest.fixture(autouse=True)
def upload_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Write uploads under the test's own tmp dir, not the user's home."""
    monkeypatch.setattr(documents_service, "UPLOAD_BASE", tmp_path / "uploads")
    monkeypatch.setattr(documents_service, "PHOTO_BASE", tmp_path / "photos")
    monkeypatch.setattr(documents_service, "PHOTO_THUMB_BASE", tmp_path / "photos" / "thumbs")
    return tmp_path


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email="owner@disguised-programs.io", hashed_password="x", full_name="Owner"))
        await s.flush()
        s.add(Project(id=PROJECT_ID, name="Disguised programs", owner_id=OWNER_ID, currency="EUR"))
        await s.flush()
        yield s


def _upload(content: bytes, filename: str, content_type: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename, headers=Headers({"content-type": content_type}))


def _files_under(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()] if root.exists() else []


@pytest.mark.parametrize(("content", "token"), PROGRAMS)
async def test_a_program_named_pdf_is_refused_and_not_stored(
    session: AsyncSession, upload_dirs: Path, content: bytes, token: str
) -> None:
    with pytest.raises(HTTPException) as refused:
        await DocumentService(session).upload_document(
            PROJECT_ID, _upload(content, "фактура.pdf", "application/pdf"), "other", str(OWNER_ID)
        )
    assert refused.value.status_code == 400
    assert token in str(refused.value.detail)
    assert await session.scalar(select(func.count()).select_from(Document)) == 0
    assert _files_under(upload_dirs / "uploads") == []


async def test_a_program_named_jpg_is_refused_as_a_photo(session: AsyncSession, upload_dirs: Path) -> None:
    with pytest.raises(HTTPException) as refused:
        await PhotoService(session).upload_photo(
            project_id=PROJECT_ID,
            file=_upload(WINDOWS, "оглед.jpg", "image/jpeg"),
            caption=None,
            gps_lat=None,
            gps_lon=None,
            tags=[],
            category="site",
            taken_at=None,
            user_id=str(OWNER_ID),
        )
    assert refused.value.status_code == 400
    assert await session.scalar(select(func.count()).select_from(ProjectPhoto)) == 0
    assert _files_under(upload_dirs / "photos") == []


async def test_a_text_file_that_starts_with_mz_still_uploads(session: AsyncSession) -> None:
    doc = await DocumentService(session).upload_document(
        PROJECT_ID,
        _upload(b"MZ;Mazut;Litres\n1;Heating;400\n", "разход гориво.csv", "text/csv"),
        "other",
        str(OWNER_ID),
    )
    assert doc.name.endswith(".csv")
