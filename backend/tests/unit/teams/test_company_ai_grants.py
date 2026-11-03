"""A project team may use the owner's AI key only for its approved, current members."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import delete

from app.dependencies import get_current_user_payload, get_session
from app.modules.ai.team_grants import (
    GrantRequest,
    has_approved_team_membership,
    list_team_grants,
    router,
    set_team_grant,
)
from app.modules.teams.models import TeamMembership
from tests.unit.teams.conftest import make_membership, make_project, make_team, make_user

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def enable_pilot(monkeypatch):
    monkeypatch.setenv("PMPM_INTERNAL_AI_PILOT", "true")
    monkeypatch.setenv("REGISTRATION_MODE", "closed")
    monkeypatch.setenv("SEED_DEMO", "false")


async def test_grant_uses_live_eligible_memberships_and_requires_owner_approval_for_new_ones(session, monkeypatch):
    first = await make_user(session)
    other = await make_user(session)
    viewer = await make_user(session, role="viewer")
    inactive = await make_user(session, is_active=False)
    project = await make_project(session, first.id)
    team = await make_team(session, project.id, name="Design")
    second_team = await make_team(session, project.id, name="Survey")
    member = await make_membership(session, team.id, first.id)
    await make_membership(session, team.id, viewer.id)
    await make_membership(session, team.id, inactive.id)
    await make_membership(session, second_team.id, other.id)

    on, off = GrantRequest(enabled=True), GrantRequest(enabled=False)
    assert not await has_approved_team_membership(session, first.id)
    enabled = await set_team_grant(team.id, on, session)
    assert (enabled["eligible_members"], enabled["approved_members"], enabled["pending_members"]) == (1, 1, 0)
    assert await has_approved_team_membership(session, first.id)
    assert not await has_approved_team_membership(session, other.id)
    assert not await has_approved_team_membership(session, viewer.id)
    assert not await has_approved_team_membership(session, inactive.id)

    # A project owner may add members to a project, but cannot silently grant them paid AI.
    await make_membership(session, team.id, other.id)
    assert not await has_approved_team_membership(session, other.id)
    found = next(row for row in (await list_team_grants(session))["teams"] if row["id"] == team.id)
    assert (found["approved_members"], found["pending_members"]) == (1, 1)
    assert (await set_team_grant(team.id, on, session))["approved_members"] == 2
    assert await has_approved_team_membership(session, other.id)

    await session.execute(delete(TeamMembership).where(TeamMembership.id == member.id))
    assert not await has_approved_team_membership(session, first.id)
    await make_membership(session, team.id, first.id)
    assert not await has_approved_team_membership(session, first.id)

    other.role = "viewer"
    await session.flush()
    assert not await has_approved_team_membership(session, other.id)
    other.role = "editor"
    team.is_active = False
    await session.flush()
    assert not await has_approved_team_membership(session, other.id)
    suspended = next(row for row in (await list_team_grants(session))["teams"] if row["id"] == team.id)
    assert suspended["active"] is False
    with pytest.raises(HTTPException, match="inactive"):
        await set_team_grant(team.id, on, session)
    assert not (await set_team_grant(team.id, off, session))["enabled"]
    team.is_active = True
    await session.flush()
    await set_team_grant(team.id, on, session)

    with monkeypatch.context() as unsafe:
        unsafe.setenv("REGISTRATION_MODE", "open")
        assert not await has_approved_team_membership(session, other.id)
    for _ in range(2):
        assert not (await set_team_grant(team.id, off, session))["enabled"]
        assert not await has_approved_team_membership(session, other.id)


async def test_only_installation_owner_can_list_or_approve_teams(monkeypatch):
    owner_id = str(uuid.uuid4())
    monkeypatch.setenv("PMPM_AI_OWNER_USER_ID", owner_id)
    actor = {"sub": str(uuid.uuid4()), "role": "admin"}
    session = AsyncMock()
    session.execute.return_value = MagicMock()
    session.execute.return_value.mappings.return_value = []
    session.scalar.return_value = None
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_payload] = lambda: actor
    app.dependency_overrides[get_session] = lambda: session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        path = "/internal-pilot/teams/"
        unknown_team = f"{path}{uuid.uuid4()}"
        assert (await client.get(path)).status_code == 403
        assert (await client.put(unknown_team, json={"enabled": True})).status_code == 403
        session.execute.assert_not_awaited()
        session.scalar.assert_not_awaited()
        actor["sub"] = owner_id
        assert (await client.get(path)).json() == {"teams": []}
        assert (await client.put(unknown_team, json={"enabled": True})).status_code == 404
