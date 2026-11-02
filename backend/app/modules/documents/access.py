"""One answer to "may this user read / change this document?".

Folder permissions used to be enforced only by some document endpoints:
reading metadata and deleting checked the document's folder, but download,
metadata updates, share links, the activity log, "similar documents", content
search and Document Analyst's retrieval checked project membership alone. A
member kept out of a restricted folder could still download one of its files
by id, mint a public link to it, or have its text quoted back by the AI.

Every path that hands out a document, or acts on one, goes through here:

* :func:`require_document_access` - one document, raising the same 404 the
  existing guarded endpoints use (a denied document looks missing).
* :func:`readable_document_ids` - the subset of a set of ids the caller may
  read, for search and retrieval, which drop what the caller cannot see.

Both rest on :func:`~app.modules.documents.folder_permissions_service.
folder_access_for`, so admins, project owners, members and folder grants are
decided exactly as they are for ``GET /documents/{id}``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.folder_permissions_service import (
    can_write,
    folder_access_for,
    kind_and_path_for_document,
)

Action = Literal["read", "write"]


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


async def document_role(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    category: str | None,
    user_id: str | uuid.UUID,
) -> str | None:
    """The caller's folder role for a document in ``category``, or ``None`` for no access."""
    try:
        caller = uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return None
    kind, path = kind_and_path_for_document(category)
    return await folder_access_for(
        session,
        project_id=project_id,
        user_id=caller,
        scope_kind=kind,
        scope_path=path,
    )


async def require_document_access(
    session: AsyncSession,
    document: Any,
    user_id: str | uuid.UUID,
    action: Action = "read",
) -> str:
    """Raise 404 unless the caller may ``action`` this document; return their role.

    ``read`` needs any role on the document's folder. ``write`` (change it,
    replace its file, share it outside the project) needs editor or above, the
    same bar uploading into the folder and deleting from it already set.
    """
    from app.dependencies import verify_project_access

    # Project first: keeps "no such project" and "not yours" one answer.
    await verify_project_access(document.project_id, str(user_id), session)
    role = await document_role(
        session,
        project_id=document.project_id,
        category=getattr(document, "category", None),
        user_id=user_id,
    )
    if role is None:
        raise _not_found()
    if action == "write" and role != "owner" and not can_write(role):
        raise _not_found()
    return role


async def readable_document_ids(
    session: AsyncSession,
    user_id: str | uuid.UUID,
    ids: Iterable[str | uuid.UUID],
) -> set[str]:
    """The ids in ``ids`` that are documents the caller may read, as strings.

    Unknown or malformed ids are left out. Folder access is resolved once per
    (project, category), not once per document.
    """
    from app.modules.documents.models import Document

    wanted: set[uuid.UUID] = set()
    for raw in ids:
        try:
            wanted.add(uuid.UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    if not wanted:
        return set()

    rows = (
        await session.execute(
            select(Document.id, Document.project_id, Document.category).where(Document.id.in_(wanted))
        )
    ).all()
    decided: dict[tuple[uuid.UUID, str | None], bool] = {}
    readable: set[str] = set()
    for doc_id, project_id, category in rows:
        _kind, path = kind_and_path_for_document(category)
        key = (project_id, path)
        if key not in decided:
            role = await document_role(session, project_id=project_id, category=category, user_id=user_id)
            decided[key] = role is not None
        if decided[key]:
            readable.add(str(doc_id))
    return readable
