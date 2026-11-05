"""The workspace refresher must not outlive its application's database pool."""

import asyncio
from unittest.mock import AsyncMock

import pytest_asyncio

from app.modules.ai import workspace


@pytest_asyncio.fixture(autouse=True)
async def isolated_worker(monkeypatch):
    await workspace.stop()
    monkeypatch.setattr(workspace, "_refresh_task", None)
    monkeypatch.setattr(workspace, "_current", None)
    monkeypatch.setattr(workspace, "refresh", AsyncMock(return_value=None))
    yield
    await workspace.stop()


async def test_start_reuses_worker_and_stop_allows_a_clean_restart():
    await workspace.start()
    first = workspace._refresh_task
    assert first is not None and not first.done()
    await workspace.start()
    assert workspace._refresh_task is first

    await workspace.stop()
    assert first.cancelled()
    assert workspace._refresh_task is None
    await workspace.stop()

    await workspace.start()
    second = workspace._refresh_task
    assert second is not None and second is not first and not second.done()
    await workspace.stop()
    assert second.cancelled()
    assert workspace._refresh_task is None


async def test_stop_awaits_cleanup_of_an_inflight_refresh(monkeypatch):
    started = asyncio.Event()
    cleaning = asyncio.Event()
    allow_cleanup = asyncio.Event()
    cleaned = asyncio.Event()
    calls = 0

    async def refresh():
        nonlocal calls
        calls += 1
        if calls == 1:
            workspace.set_current(workspace.WorkspaceAI("deepseek", "synthetic-key", "model", "", True))
            return
        started.set()
        try:
            await asyncio.Future()
        finally:
            # A real refresh's async database context also needs to finish
            # releasing its connection before the engine can be disposed.
            cleaning.set()
            await allow_cleanup.wait()
            cleaned.set()

    monkeypatch.setattr(workspace, "refresh", refresh)
    monkeypatch.setattr(workspace, "REFRESH_SECONDS", 0)
    stopping = None
    try:
        await workspace.start()
        worker = workspace._refresh_task
        await asyncio.wait_for(started.wait(), timeout=5)
        stopping = asyncio.create_task(workspace.stop())
        await asyncio.wait_for(cleaning.wait(), timeout=5)
        assert not stopping.done()
        assert not cleaned.is_set()
        allow_cleanup.set()
        await asyncio.wait_for(stopping, timeout=5)
        assert worker is not None and worker.cancelled()
        assert cleaned.is_set()
        assert workspace._refresh_task is None
        assert workspace.current() is None
    finally:
        allow_cleanup.set()
        if stopping is not None:
            await stopping
