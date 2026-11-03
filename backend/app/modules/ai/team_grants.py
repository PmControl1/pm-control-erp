"""Owner-approved access to the company provider for members of native project teams."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StrictBool
from sqlalchemy import and_, delete, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import ROLE_ALIASES, ROLE_HIERARCHY, Role
from app.dependencies import SessionDep
from app.modules.ai.company_config import require_company_owner
from app.modules.ai.internal_pilot import internal_pilot_enabled
from app.modules.ai.models import company_team_approvals as approvals
from app.modules.ai.models import company_team_grants as grants
from app.modules.projects.models import Project
from app.modules.teams.models import Team, TeamMembership
from app.modules.users.models import User

router = APIRouter(prefix="/internal-pilot/teams", dependencies=[Depends(require_company_owner)])

_ELIGIBLE_ROLES = tuple(
    role.value for role, level in ROLE_HIERARCHY.items() if level >= ROLE_HIERARCHY[Role.EDITOR]
) + tuple(alias for alias, role in ROLE_ALIASES.items() if ROLE_HIERARCHY[role] >= ROLE_HIERARCHY[Role.EDITOR])


def _eligible_user():
    return and_(
        User.is_active.is_(True), User.deleted_at.is_(None), func.lower(func.trim(User.role)).in_(_ELIGIBLE_ROLES)
    )


async def has_approved_team_membership(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Recheck current membership and account eligibility each time a shared credential is needed."""
    if not internal_pilot_enabled():
        return False
    eligible = (
        select(1)
        .select_from(TeamMembership)
        .join(Team, Team.id == TeamMembership.team_id)
        .join(Project, Project.id == Team.project_id)
        .join(User, User.id == TeamMembership.user_id)
        .join(grants, grants.c.team_id == Team.id)
        .join(approvals, and_(approvals.c.team_id == Team.id, approvals.c.membership_id == TeamMembership.id))
        .where(TeamMembership.user_id == user_id, Team.is_active.is_(True), _eligible_user())
    )
    return bool(await session.scalar(select(eligible.exists())))


class GrantRequest(BaseModel):
    enabled: StrictBool


def _team_list(*, include_inactive: bool = False):
    eligible = func.count(User.id)
    approved = func.count(approvals.c.membership_id).filter(User.id.is_not(None))
    stmt = (
        select(
            Team.id,
            Team.name,
            Team.project_id,
            Team.is_active.label("active"),
            Project.name.label("project_name"),
            grants.c.team_id.is_not(None).label("enabled"),
            eligible.label("eligible_members"),
            approved.label("approved_members"),
            (eligible - approved).label("pending_members"),
        )
        .select_from(Team)
        .join(Project, Project.id == Team.project_id)
        .outerjoin(grants, grants.c.team_id == Team.id)
        .outerjoin(TeamMembership, TeamMembership.team_id == Team.id)
        .outerjoin(User, and_(User.id == TeamMembership.user_id, _eligible_user()))
        .outerjoin(
            approvals, and_(approvals.c.team_id == grants.c.team_id, approvals.c.membership_id == TeamMembership.id)
        )
        .group_by(Team.id, Team.name, Team.project_id, Team.is_active, Project.name, grants.c.team_id)
        .order_by(Project.name, Team.name, Team.id)
    )

    if not include_inactive:
        stmt = stmt.where(or_(Team.is_active.is_(True), grants.c.team_id.is_not(None)))
    return stmt


@router.get("/")
async def list_team_grants(session: SessionDep) -> dict:
    rows = await session.execute(_team_list())
    return {"teams": [dict(row) for row in rows.mappings()]}


@router.put("/{team_id}")
async def set_team_grant(team_id: uuid.UUID, body: GrantRequest, session: SessionDep) -> dict:
    """Grant or refresh eligible current members; revoke removes the entire approval."""
    if not internal_pilot_enabled():
        raise HTTPException(409, "Company AI is disabled.")
    # Serialize owner edits on a row already present even before the first grant.
    active = await session.scalar(
        select(Team.is_active)
        .join(Project, Project.id == Team.project_id)
        .where(Team.id == team_id)
        .with_for_update(of=Team)
    )
    if active is None:
        raise HTTPException(404, "Team not found.")
    if body.enabled and not active:
        raise HTTPException(409, "An inactive team cannot receive AI access.")
    await session.execute(delete(approvals).where(approvals.c.team_id == team_id))
    if body.enabled:
        if await session.scalar(select(grants.c.team_id).where(grants.c.team_id == team_id)) is None:
            await session.execute(insert(grants).values(team_id=team_id))
        eligible = (
            select(TeamMembership.id, TeamMembership.team_id)
            .join(User, User.id == TeamMembership.user_id)
            .where(TeamMembership.team_id == team_id, _eligible_user())
        )
        await session.execute(insert(approvals).from_select(["membership_id", "team_id"], eligible))
    else:
        await session.execute(delete(grants).where(grants.c.team_id == team_id))
    return dict((await session.execute(_team_list(include_inactive=True).where(Team.id == team_id))).mappings().one())
