"""Legacy Bulgarian projects are repaired only by an explicit, reversible choice."""

from __future__ import annotations

import copy
import uuid
from types import SimpleNamespace

import pytest
from scripts.repair_bulgaria_validation import SNAPSHOT_KEY, _run, apply_plan, main, repair_plan


def _project(**values):
    return SimpleNamespace(
        **{
            "id": uuid.uuid4(),
            "name": "Жилищна сграда",
            "owner_id": uuid.uuid4(),
            "country_code": "BG",
            "region": "",
            "classification_standard": "",
            "validation_rule_sets": ["boq_quality", "din276", "custom_safety"],
            "metadata_": {"custom": {"keep": True}, "pack_rule_sets": ["din276"]},
            **values,
        }
    )


def test_preview_preserves_project_and_useful_validation():
    project = _project()
    before = copy.deepcopy(vars(project))
    plan = repair_plan(project)
    assert vars(project) == before
    assert plan["status"] == "change"
    assert plan["after"]["validation_rule_sets"] == ["boq_quality", "custom_safety", "bulgaria"]


@pytest.mark.parametrize("values", [{"country_code": "DE"}, {"country_code": "BG", "region": "DE"}])
def test_a_foreign_project_cannot_be_repaired(values):
    assert repair_plan(_project(**values))["status"] == "blocked"


def test_region_can_identify_a_bulgarian_project():
    assert repair_plan(_project(country_code="DE", region="BG"))["status"] == "change"


def test_an_explicit_din_standard_requires_the_additional_choice():
    project = _project(classification_standard="DIN276")
    assert repair_plan(project)["status"] == "blocked"
    plan = repair_plan(project, clear_din_standard=True)
    assert plan["status"] == "change"
    assert plan["after"]["classification_standard"] == ""


def test_other_explicit_standards_are_kept():
    plan = repair_plan(_project(classification_standard="custom_standard"))
    assert plan["after"]["classification_standard"] == "custom_standard"


def test_repair_is_idempotent_and_restores_the_original_settings():
    project = _project(classification_standard="din276")
    before = copy.deepcopy(vars(project))
    plan = repair_plan(project, clear_din_standard=True)
    apply_plan(project, plan)
    assert project.metadata_["custom"] == before["metadata_"]["custom"]
    assert project.metadata_["pack_rule_sets"] == ["din276"]
    assert project.metadata_[SNAPSHOT_KEY]["before"] == plan["before"]
    assert repair_plan(project)["status"] == "unchanged"
    restore = repair_plan(project, restore=True)
    assert restore["status"] == "change"
    apply_plan(project, restore, restore=True)
    assert vars(project) == before


def test_restore_refuses_to_overwrite_a_later_rule_change():
    project = _project()
    apply_plan(project, repair_plan(project))
    project.validation_rule_sets.append("new_custom_rule")
    assert repair_plan(project, restore=True)["status"] == "blocked"
    assert repair_plan(project)["status"] == "unchanged"


def test_a_repair_snapshot_is_never_silently_replaced():
    project = _project()
    apply_plan(project, repair_plan(project))
    original_snapshot = copy.deepcopy(project.metadata_[SNAPSHOT_KEY])
    project.validation_rule_sets.append("din276")
    assert repair_plan(project)["status"] == "blocked"
    assert project.metadata_[SNAPSHOT_KEY] == original_snapshot


def test_adding_country_rules_keeps_baseline_for_empty_legacy_settings():
    plan = repair_plan(_project(validation_rule_sets=[]))
    assert plan["after"]["validation_rule_sets"] == ["boq_quality", "bulgaria"]


@pytest.mark.parametrize("flag", ["--apply", "--clear-din-standard", "--restore"])
def test_mutation_flags_require_an_explicit_project_id(flag):
    with pytest.raises(SystemExit, match="2"):
        main([flag])


def test_restore_and_clear_standard_cannot_be_combined():
    with pytest.raises(SystemExit, match="2"):
        main(["--project-id", str(uuid.uuid4()), "--restore", "--clear-din-standard"])


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.committed = False
        self.locked = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def execute(self, query):
        self.locked = query._for_update_arg is not None
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.rows))

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_command_preview_writes_nothing(monkeypatch):
    import app.database

    project = _project()
    before = copy.deepcopy(vars(project))
    session = _Session([project])
    monkeypatch.setattr(app.database, "async_session_factory", lambda: session)
    assert await _run([], apply=False, clear_din_standard=False, restore=False) == 0
    assert vars(project) == before
    assert not session.committed
    assert not session.locked


@pytest.mark.asyncio
async def test_command_applies_selected_locked_row_and_commits(monkeypatch):
    import app.database

    project = _project()
    session = _Session([project])
    monkeypatch.setattr(app.database, "async_session_factory", lambda: session)
    assert await _run([project.id], apply=True, clear_din_standard=False, restore=False) == 0
    assert project.validation_rule_sets == ["boq_quality", "custom_safety", "bulgaria"]
    assert session.committed
    assert session.locked


@pytest.mark.asyncio
async def test_one_blocked_selected_project_prevents_partial_application(monkeypatch):
    import app.database

    eligible, blocked = _project(), _project(classification_standard="din276")
    before = copy.deepcopy(vars(eligible))
    session = _Session([eligible, blocked])
    monkeypatch.setattr(app.database, "async_session_factory", lambda: session)
    assert await _run([eligible.id, blocked.id], apply=True, clear_din_standard=False, restore=False) == 2
    assert vars(eligible) == before
    assert not session.committed


@pytest.mark.asyncio
async def test_missing_project_id_prevents_application(monkeypatch):
    import app.database

    project = _project()
    before = copy.deepcopy(vars(project))
    session = _Session([project])
    monkeypatch.setattr(app.database, "async_session_factory", lambda: session)
    assert await _run([project.id, uuid.uuid4()], apply=True, clear_din_standard=False, restore=False) == 2
    assert vars(project) == before
    assert not session.committed
