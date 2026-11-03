import concurrent.futures
import sqlite3
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import crypto
from app.dependencies import get_current_user_payload
from app.modules.ai import ai_client, company_config

OWNER = str(uuid4())
SECRET = "test-only-company-key"


@pytest.fixture
def client(monkeypatch, tmp_path):
    from types import SimpleNamespace

    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PMPM_INTERNAL_AI_PILOT", "true")
    monkeypatch.setenv("REGISTRATION_MODE", "closed")
    monkeypatch.setenv("SEED_DEMO", "false")
    monkeypatch.setenv("PMPM_AI_OWNER_USER_ID", OWNER)
    monkeypatch.setenv("PMPM_INTERNAL_DEEPSEEK_API_KEY", "test-only-old-environment-key")
    monkeypatch.setattr(crypto, "get_settings", lambda: SimpleNamespace(jwt_secret="unit-test-key"))
    app = FastAPI()
    app.include_router(company_config.router)
    app.dependency_overrides[get_current_user_payload] = lambda: {"sub": OWNER, "role": "admin"}
    return TestClient(app)


URL = "/company/settings/"


@pytest.mark.parametrize("ident,role", [(str(uuid4()), "admin"), (OWNER, "editor"), (OWNER, "viewer")])
def test_only_named_admin_can_read_or_manage(client, ident, role):
    client.app.dependency_overrides[get_current_user_payload] = lambda: {"sub": ident, "role": role}
    data = {"provider": "deepseek", "model": "deepseek-flash", "api_key": SECRET}
    assert client.get(URL).status_code == 403
    assert client.put(URL, json=data).status_code == 403
    assert client.post(URL + "test/").status_code == 403
    assert client.delete(URL).status_code == 403


def test_disabled_pilot_and_unbound_owner_denied(client, monkeypatch):
    monkeypatch.setenv("REGISTRATION_MODE", "open")
    assert client.get(URL).status_code == 403
    monkeypatch.setenv("REGISTRATION_MODE", "closed")
    monkeypatch.setenv("PMPM_AI_OWNER_USER_ID", "invalid")
    assert client.get(URL).status_code == 403


def test_rotation_and_clear_do_not_reveal_or_revive_keys(client, tmp_path):
    first = {"provider": "openai", "model": "model-1", "api_key": SECRET}
    assert client.put(URL, json=first).json() == {"provider": "openai", "model": "model-1", "key_set": True}
    assert SECRET not in client.get(URL).text
    storage = tmp_path / ".pmpm/company-ai.sqlite3"
    assert SECRET.encode() not in storage.read_bytes()
    assert storage.stat().st_mode & 0o077 == 0
    assert company_config.company_credential() == ("openai", SECRET, "model-1")
    assert client.put(URL, json={"provider": "openai", "model": "model-2"}).status_code == 200
    assert company_config.company_credential() == ("openai", SECRET, "model-2")
    assert client.put(URL, json={"provider": "deepseek", "model": "model-3"}).status_code == 422
    assert company_config.company_credential() == ("openai", SECRET, "model-2")
    assert (
        client.put(URL, json={"provider": "deepseek", "model": "model-3", "api_key": "rotated-key"}).status_code == 200
    )
    assert company_config.company_credential() == ("deepseek", "rotated-key", "model-3")
    assert client.delete(URL).json()["key_set"] is False
    assert company_config.company_credential() is None
    assert client.put(URL, json={"provider": "deepseek", "model": "model-4"}).status_code == 422


def test_rejected_first_save_leaves_legacy_key_working(client):
    assert client.get(URL).json()["key_set"] is True
    for data in ({}, {"api_key": " "}, {"api_key": SECRET, "base_url": "https://example.com"}):
        assert client.put(URL, json={"provider": "openai", "model": "demo", **data}).status_code == 422
    assert company_config.company_credential()[1] == "test-only-old-environment-key"


def test_legacy_key_can_be_kept_on_same_provider_upgrade(client, monkeypatch):
    assert client.put(URL, json={"provider": "deepseek", "model": "chosen-model"}).is_success
    monkeypatch.delenv("PMPM_INTERNAL_DEEPSEEK_API_KEY")
    assert company_config.company_credential() == ("deepseek", "test-only-old-environment-key", "chosen-model")


def test_ciphertext_only_and_missing_owner_fail_closed(client, tmp_path, monkeypatch):
    assert client.put(URL, json={"provider": "openai", "model": "demo", "api_key": SECRET}).is_success
    with sqlite3.connect(tmp_path / ".pmpm/company-ai.sqlite3") as db:
        db.execute("UPDATE company_ai SET ciphertext = 'untrusted-plaintext' WHERE id=1")
    assert not client.get(URL).json()["key_set"]
    assert company_config.company_credential() is None
    assert client.put(URL, json={"provider": "openai", "model": "demo", "api_key": SECRET}).is_success
    monkeypatch.delenv("PMPM_AI_OWNER_USER_ID")
    assert company_config.company_credential() is None


def test_concurrent_model_change_cannot_revert_rotation(client):
    payload = {"provider": "openai", "model": "model-1"}
    assert client.put(URL, json={**payload, "api_key": SECRET}).is_success
    with concurrent.futures.ThreadPoolExecutor() as pool:
        responses = list(
            pool.map(
                lambda body: client.put(URL, json=body),
                [
                    {**payload, "api_key": "rotated-key"},
                    {**payload, "model": "model-2"},
                ],
            )
        )
    assert all(response.is_success for response in responses)
    assert company_config.company_credential()[1] == "rotated-key"


@pytest.mark.parametrize("provider,adapter", [("openai", "call_openai"), ("deepseek", "call_openai_compatible")])
def test_connection_uses_saved_provider_and_model_and_redacts_errors(client, monkeypatch, provider, adapter):
    assert client.put(URL, json={"provider": provider, "model": "chosen-model", "api_key": SECRET}).is_success
    request = AsyncMock(return_value=("OK", 1))
    monkeypatch.setattr(ai_client, adapter, request)
    assert client.post(URL + "test/").json()["success"]
    assert request.await_args.kwargs["model"] == "chosen-model"
    assert request.await_args.kwargs["api_key"] == SECRET
    request.side_effect = ValueError(SECRET)
    response = client.post(URL + "test/")
    assert not response.json()["success"]
    assert SECRET not in response.text
