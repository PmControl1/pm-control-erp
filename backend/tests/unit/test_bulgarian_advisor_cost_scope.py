"""Cost advice keeps its requested market when vector search is unavailable."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import vector
from app.modules.ai import router
from app.modules.costs.models import CostItem
from tests._pg import isolated_engine


@pytest.mark.asyncio
@pytest.mark.parametrize("region", [None, "BG_SOFIA", "CUSTOM"])
async def test_text_fallback_uses_bulgaria_by_default_and_preserves_explicit_custom_data(
    monkeypatch: pytest.MonkeyPatch, region: str | None
) -> None:
    def unavailable(_texts: list[str]) -> None:
        raise RuntimeError("No local vector model")

    monkeypatch.setattr(vector, "encode_texts", unavailable)
    monkeypatch.setattr(
        router,
        "_get_service",
        lambda _session: SimpleNamespace(settings_repo=SimpleNamespace(get_by_user_id=AsyncMock(return_value=None))),
    )
    monkeypatch.setattr(router, "resolve_provider_key_model", lambda _settings: ("test", "test-key", "test-model"))
    ai = AsyncMock(return_value=("BG-RATE CUSTOM-RATE", 10))
    monkeypatch.setattr(router, "call_ai", ai)
    async with isolated_engine() as engine, AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(
            [
                CostItem(
                    code="BG-RATE", description="Бетон София", unit="м3", rate="100", currency="BGN", region="BG_SOFIA"
                ),
                CostItem(
                    code="FOREIGN-RATE",
                    description="Бетон Берлин",
                    unit="м3",
                    rate="900",
                    currency="EUR",
                    region="DE_BERLIN",
                ),
                CostItem(
                    code="CUSTOM-RATE",
                    description="Бетон по оферта",
                    unit="м3",
                    rate="70",
                    currency="EUR",
                    region="CUSTOM",
                    source="custom",
                ),
            ]
        )
        await session.flush()
        body = {"message": "Бетон"}
        if region is not None:
            body["region"] = region
        result = await router.advisor_chat(body, session, str(uuid.uuid4()), Response(), _remaining=99)

    expected = "CUSTOM-RATE" if region == "CUSTOM" else "BG-RATE"
    excluded = "BG-RATE" if region == "CUSTOM" else "CUSTOM-RATE"
    assert [source["code"] for source in result["sources"]] == [expected]
    prompt = ai.await_args.kwargs["prompt"]
    assert expected in prompt
    assert excluded not in prompt
    assert "FOREIGN-RATE" not in prompt
    assert "Respond in Bulgarian" in prompt
