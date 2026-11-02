"""Single-company shared AI key must remain opt-in and per-user."""

import uuid
from types import SimpleNamespace

import pytest

from app.modules.ai.ai_client import default_model_for, resolve_provider_key_model
from app.modules.ai.internal_pilot import (
    ACCESS_FLAG,
    internal_pilot_credential,
    internal_pilot_enabled,
)


@pytest.fixture(autouse=True)
def isolated_pilot_environment(monkeypatch):
    for name in (
        "PMPM_INTERNAL_AI_PILOT",
        "PMPM_INTERNAL_DEEPSEEK_API_KEY",
        "REGISTRATION_MODE",
        "SEED_DEMO",
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def _row(granted=True):
    return SimpleNamespace(
        user_id=uuid.uuid4(),
        preferred_model="deepseek-flash",
        metadata_={ACCESS_FLAG: granted},
    )


def _enable(monkeypatch):
    monkeypatch.setenv("PMPM_INTERNAL_AI_PILOT", "true")
    monkeypatch.setenv("REGISTRATION_MODE", "closed")
    monkeypatch.setenv("SEED_DEMO", "false")
    monkeypatch.setenv("PMPM_INTERNAL_DEEPSEEK_API_KEY", "company-test-secret")


def test_company_credential_is_deny_by_default(monkeypatch):
    row = _row()
    monkeypatch.setenv("PMPM_INTERNAL_DEEPSEEK_API_KEY", "test-secret")
    assert internal_pilot_credential(row) is None
    assert not internal_pilot_enabled()


def test_company_credential_requires_explicit_user_grant(monkeypatch):
    _enable(monkeypatch)
    assert internal_pilot_credential(None) is None
    assert internal_pilot_credential(_row(False)) is None
    assert internal_pilot_credential(SimpleNamespace(metadata_={ACCESS_FLAG: True})) is None
    assert internal_pilot_credential(_row()) == "company-test-secret"


@pytest.mark.parametrize(
    ("registration", "demo"),
    [("open", "false"), ("admin-approve", "false"), ("closed", "true")],
)
def test_registration_or_demo_must_be_locked(monkeypatch, registration, demo):
    _enable(monkeypatch)
    monkeypatch.setenv("REGISTRATION_MODE", registration)
    monkeypatch.setenv("SEED_DEMO", demo)
    assert internal_pilot_credential(_row()) is None


def test_grant_routes_to_shared_deepseek_without_exposing_key_to_other_users(monkeypatch):
    _enable(monkeypatch)
    provider, key, model = resolve_provider_key_model(_row())
    assert (provider, key, model) == ("deepseek", "company-test-secret", None)
    assert default_model_for(provider) == "deepseek-flash"
    with pytest.raises(ValueError, match="approved internal company AI"):
        resolve_provider_key_model(_row(False))


def test_global_env_fallback_cannot_bypass_internal_grant(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unrestricted-legacy-secret")
    with pytest.raises(ValueError, match="approved internal company AI"):
        resolve_provider_key_model(_row(False))


def test_disabled_pilot_preserves_regular_provider_settings(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "existing-personal-environment-key")
    provider, key, model = resolve_provider_key_model(_row(False))
    assert (provider, key, model) == ("deepseek", "existing-personal-environment-key", None)
