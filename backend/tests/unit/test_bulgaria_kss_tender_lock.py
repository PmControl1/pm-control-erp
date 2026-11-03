"""A locked КСС retains the tender bill it was approved against."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.modules.boq.schemas import BOQUpdate
from app.modules.boq.service import BOQService


def _service(monkeypatch: pytest.MonkeyPatch, *, locked: bool, tender: str | None = "original") -> BOQService:
    bill = SimpleNamespace(
        id=uuid.uuid4(), status="final" if locked else "draft", metadata_={"kss_tender_bill_id": tender, "keep": 1}
    )
    service = BOQService.__new__(BOQService)
    service.get_boq = AsyncMock(return_value=bill)
    # Keep the real write guard; only the database column lookup is replaced.
    service.session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(first=lambda: (locked,))))
    service.boq_repo = SimpleNamespace(update_fields=AsyncMock())
    monkeypatch.setattr("app.modules.boq.service._safe_publish", AsyncMock())
    return service


@pytest.mark.parametrize("metadata", [{"kss_tender_bill_id": "other"}, {"kss_tender_bill_id": None}, None])
async def test_a_locked_bill_cannot_change_or_clear_its_tender(monkeypatch: pytest.MonkeyPatch, metadata) -> None:
    service = _service(monkeypatch, locked=True)
    with pytest.raises(HTTPException) as error:
        await service.update_boq(uuid.uuid4(), BOQUpdate(metadata=metadata))
    assert error.value.status_code == 409
    service.boq_repo.update_fields.assert_not_awaited()


async def test_a_locked_bill_cannot_acquire_a_different_validation_basis(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(monkeypatch, locked=True, tender=None)
    with pytest.raises(HTTPException) as error:
        await service.update_boq(uuid.uuid4(), BOQUpdate(metadata={"kss_tender_bill_id": "new"}))
    assert error.value.status_code == 409
    service.boq_repo.update_fields.assert_not_awaited()


async def test_an_unlocked_bill_can_link_a_tender_without_losing_other_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(monkeypatch, locked=False)
    bill_id = uuid.uuid4()
    await service.update_boq(bill_id, BOQUpdate(metadata={"kss_tender_bill_id": "other"}))
    service.boq_repo.update_fields.assert_awaited_once_with(
        bill_id, metadata_={"kss_tender_bill_id": "other", "keep": 1}
    )


@pytest.mark.parametrize("metadata", [{"unrelated": 2}, {"kss_tender_bill_id": "original"}])
async def test_existing_locked_header_metadata_behavior_is_preserved(monkeypatch: pytest.MonkeyPatch, metadata) -> None:
    service = _service(monkeypatch, locked=True)
    await service.update_boq(uuid.uuid4(), BOQUpdate(metadata=metadata))
    service.session.execute.assert_not_awaited()
    service.boq_repo.update_fields.assert_awaited_once()
