# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Global search API router.

Endpoint:
    GET /api/v1/global-search?q=...&project_id=...&limit=20

The prefix used to be /api/v1/search, but the module-loader auto-mounts
``app.modules.search`` at the same /api/v1/search prefix. Both routers
work today because their child paths don't overlap, but adding a route
in one that collides with the other would silently shadow. The prefixes
are now distinct so that class of bug can't slip past code review.
"""

import logging
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from app.core.global_search import global_search
from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    SessionDep,
    accessible_project_ids,
    verify_project_access,
)

router = APIRouter(prefix="/api/v1/global-search", tags=["Search"])
logger = logging.getLogger(__name__)


def _may_read(payload: dict[str, Any]) -> Callable[[str], bool]:
    """Whether the caller's role holds a permission, decided as ``RequirePermission`` decides it."""
    role = str(payload.get("role", "") or "")
    granted = set(payload.get("permissions", []) or [])

    def may(permission: str) -> bool:
        if role == "admin" or permission in granted:
            return True
        from app.core.permissions import permission_registry

        return permission_registry.role_has_permission(role, permission)

    return may


@router.get("", response_model=list[dict[str, Any]])
async def search(
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    q: str = Query(default="", description="Search query string"),
    project_id: str | None = Query(default=None, description="Limit search to a specific project"),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum results to return"),
) -> list[dict[str, Any]]:
    """Search across all modules - BOQ positions, contacts, documents, RFIs,
    tasks, cost items, meetings, inspections, and NCRs.

    Only what the caller could open elsewhere is returned: records of
    projects they may access, of modules their role may read, their own
    contacts, and documents in folders they may open. A ``project_id`` they
    may not access is a 404, like every other project-scoped endpoint.

    Results are ranked by relevance score. Each result includes:
    module, type, id, title, subtitle, url, score.
    """
    if not q.strip():
        return []

    project_ids: set[uuid.UUID] | None
    if project_id:
        try:
            requested = uuid.UUID(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found") from exc
        await verify_project_access(requested, str(user_id), session)
        project_ids = {requested}
    else:
        project_ids = await accessible_project_ids(session, str(user_id))

    may_read = _may_read(payload)
    is_admin = str(payload.get("role", "") or "") == "admin"
    return await global_search(
        session,
        query=q,
        user_id=str(user_id),
        project_ids=project_ids,
        may_read=may_read,
        contact_owner=None if is_admin else str(user_id),
        limit=limit,
    )
