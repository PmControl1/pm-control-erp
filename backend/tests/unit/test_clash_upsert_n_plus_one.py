# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""N+1 query audit for the smart-issue upsert + bulk-suppress fan-out.

The clash engine used to link every result row to its persistent
``ClashIssue`` one row at a time (``upsert_clash_with_signature`` in a
loop), and each call issued two SELECTs (suppression + issue lookup) plus
a COUNT-backed ``next_issue_seq`` for every brand-new issue. On a
federated run that emits thousands of clashes that is a hard N+1.

``ClashService.upsert_clashes_with_signatures`` collapses the read side
to a fixed number of queries regardless of the result count:
  * 1 batched suppression fetch
  * 1 batched issue fetch
  * 1 ``next_issue_seq`` COUNT
  * 1 flush (+ no per-row SELECT)

Likewise ``bulk_suppress`` now pulls every member result row of the
selected issues in ONE query (``results_for_issue_ids``) and groups them
in Python, instead of a per-issue SELECT inside its loop.

Both guards instrument the session connection's ``before_cursor_execute`` to count
real data statements (PRAGMA / SAVEPOINT / RELEASE admin chatter is
skipped, mirroring ``test_clash_n_plus_one``) and assert the count does
NOT grow with the row / issue count. Other sessions sharing the engine
must not enter the operation's count.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator

import pytest_asyncio

logger = logging.getLogger(__name__)

# ── Fixture ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def db_engine():
    from app.config import get_settings

    get_settings.cache_clear()
    # Import all models so Base.metadata is fully populated before create_all.
    import app.modules.clash.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401
    from app.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine


@pytest_asyncio.fixture
async def session(db_engine) -> AsyncIterator:
    from app.database import async_session_factory

    async with async_session_factory() as s:
        yield s


# ── SQL statement counter (same idiom as test_clash_n_plus_one) ─────────────


class _QueryCounter:
    """Counts real SQL statements on the connection it is attached to."""

    def __init__(self) -> None:
        self.count = 0
        self.statements: list[str] = []

    def _handler(self, conn, cursor, statement, parameters, context, executemany) -> None:
        stmt_upper = statement.strip().upper()
        if stmt_upper.startswith(("PRAGMA", "SAVEPOINT", "RELEASE")):
            return
        self.count += 1
        self.statements.append(statement)


# ── Seeding helpers ──────────────────────────────────────────────────────────


async def _seed_project_and_run(session) -> tuple[uuid.UUID, object]:
    from app.modules.clash.models import ClashRun
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"upsert-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Upsert Tester",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Upsert N+1 Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    run = ClashRun(
        project_id=project.id,
        name="Upsert N+1 Run",
        model_ids=[],
        status="running",
        created_by=str(user.id),
        summary={},
    )
    session.add(run)
    await session.flush()
    return project.id, run


def _make_results(run_id: uuid.UUID, n: int, *, distinct: bool) -> list:
    """Build N unpersisted ClashResult rows with stamped signatures.

    ``distinct=True`` gives every row its own signature hash (worst case
    for the upsert - one new issue each); ``distinct=False`` collapses
    them onto a handful of shared hashes (exercises the in-run duplicate
    path).
    """
    from app.modules.clash.models import ClashResult

    rows = []
    for i in range(n):
        h = f"{i:040x}" if distinct else f"{i % 4:040x}"
        rows.append(
            ClashResult(
                run_id=run_id,
                a_element_id=uuid.uuid4(),
                b_element_id=uuid.uuid4(),
                a_stable_id=f"a-{i}",
                b_stable_id=f"b-{i}",
                a_name=f"Wall {i}",
                b_name=f"Pipe {i}",
                a_discipline="Structural",
                b_discipline="Mechanical",
                a_model_id=uuid.uuid4(),
                b_model_id=uuid.uuid4(),
                clash_type="hard",
                penetration_m=0.01,
                distance_m=0.0,
                cx=float(i),
                cy=0.0,
                cz=0.0,
                status="new",
                severity="medium",
                signature=h[:16],
                signature_hash=h,
                signature_quality="strong",
            )
        )
    return rows


# ── Tests ──────────────────────────────────────────────────────────────────


async def _count_upsert_queries(session, n_results: int, *, distinct: bool) -> tuple[int, list]:
    from sqlalchemy import event

    from app.modules.clash.service import ClashService

    project_id, run = await _seed_project_and_run(session)
    rows = _make_results(run.id, n_results, distinct=distinct)
    session.add_all(rows)
    await session.flush()

    counter = _QueryCounter()
    connection = (await session.connection()).sync_connection
    event.listen(connection, "before_cursor_execute", counter._handler)
    try:
        svc = ClashService(session)
        await svc.upsert_clashes_with_signatures(run, rows)
    finally:
        event.remove(connection, "before_cursor_execute", counter._handler)
    logger.info("Clash upsert: results=%s statements=%s", n_results, counter.count)
    return counter.count, rows


async def test_upsert_signatures_query_count_is_bounded(session):
    """Upserting 60 distinct-signature clashes issues a fixed, small query count.

    The batched path issues: 1 suppression fetch + 1 issue fetch + 1
    next_issue_seq COUNT + 1 flush. Allow a little headroom (<= 6) for the
    re-link flush bookkeeping; the key property is that it does NOT scale
    with the 60 rows (the old per-row loop would be ~120+).
    """
    count, rows = await _count_upsert_queries(session, 60, distinct=True)
    assert all(r.issue_id is not None for r in rows), "every signed row must be linked to an issue"
    assert count <= 6, f"N+1 regression: {count} SQL statements to upsert 60 clashes (expected <= 6)"


async def test_upsert_signatures_query_count_stable_across_sizes(session):
    """Query count does NOT grow with the number of clashes."""
    small, _ = await _count_upsert_queries(session, 10, distinct=True)
    large, _ = await _count_upsert_queries(session, 100, distinct=True)
    assert large <= 6, f"upsert of 100 clashes issued {large} statements (expected <= 6)"
    # The count must be flat - a per-row regression would make `large`
    # roughly 10x `small`.
    assert large <= small + 1, f"query count scaled with row count: {small} -> {large}"


async def test_upsert_shared_signatures_link_to_same_issue(session):
    """Rows sharing a signature in one run all link to one issue (behavior preserved)."""
    _count, rows = await _count_upsert_queries(session, 12, distinct=False)
    # 12 rows over 4 distinct hashes -> exactly 4 issues, every row linked.
    assert all(r.issue_id is not None for r in rows)
    assert len({r.issue_id for r in rows}) == 4, "rows must collapse onto 4 distinct issues"


async def _count_bulk_suppress_queries(session, n_issues: int, *, unrelated_query: bool = False) -> int:
    from sqlalchemy import event, select, text

    from app.database import engine
    from app.modules.clash.models import ClashIssue, ClashResult, ClashSuppression
    from app.modules.clash.service import ClashService

    # Two members per issue make the audit guard exercise a real fan-out.
    project_id, run = await _seed_project_and_run(session)
    rows = _make_results(run.id, n_issues * 2, distinct=True)
    for i, row in enumerate(rows):
        row.signature_hash = f"{i // 2:040x}"
        row.signature = row.signature_hash[:16]
    session.add_all(rows)
    await session.flush()
    svc = ClashService(session)
    await svc.upsert_clashes_with_signatures(run, rows)
    await session.flush()
    issue_ids = sorted({r.issue_id for r in rows})
    assert len(issue_ids) == n_issues

    counter = _QueryCounter()
    connection = (await session.connection()).sync_connection
    observer = _QueryCounter() if unrelated_query else None
    probe = "SELECT 1 /* unrelated query-count probe */"
    event.listen(connection, "before_cursor_execute", counter._handler)
    if observer is not None:
        event.listen(engine.sync_engine, "before_cursor_execute", observer._handler)
    try:
        if observer is not None:
            # Deterministically demonstrate why an engine-wide counter can
            # report an extra statement unrelated to the operation.
            async with engine.connect() as other:
                await other.execute(text(probe))
        out = await svc.bulk_suppress(project_id, issue_ids, reason="dup", user_id=None)
    finally:
        event.remove(connection, "before_cursor_execute", counter._handler)
        if observer is not None:
            event.remove(engine.sync_engine, "before_cursor_execute", observer._handler)

    assert out["suppressed_count"] == n_issues
    assert out["skipped_count"] == 0
    reads = [statement for statement in counter.statements if statement.lstrip().upper().startswith("SELECT")]
    trace = "\n".join(counter.statements)
    assert len(reads) == 3, trace
    assert sum("FROM OE_CLASH_RESULT" in statement.upper() for statement in reads) == 1, trace
    # Three batched reads plus batched issue UPDATE, history UPDATE and
    # suppression INSERT. Keep the original ceiling, including writes.
    assert counter.count <= 6, (
        f"N+1 regression: bulk_suppress of {n_issues} issues issued {counter.count} statements "
        "(expected <= 6 - the member-row fan-out must be a single batched query).\n" + trace
    )
    if observer is not None:
        assert probe in observer.statements
        assert probe not in counter.statements
        assert observer.count >= counter.count + 1

    # Read column values back from PostgreSQL after removing the counter;
    # checking only the objects already in the identity map misses lost writes.
    statuses = (await session.execute(select(ClashIssue.status).where(ClashIssue.id.in_(issue_ids)))).scalars().all()
    reasons = (
        (await session.execute(select(ClashSuppression.reason).where(ClashSuppression.project_id == project_id)))
        .scalars()
        .all()
    )
    histories = (await session.execute(select(ClashResult.history).where(ClashResult.run_id == run.id))).scalars().all()
    assert statuses == ["ignored"] * n_issues
    assert reasons == ["dup"] * n_issues
    assert len(histories) == n_issues * 2
    for history in histories:
        assert len(history) == 1
        assert (
            history[0].items()
            >= {
                "actor": "system",
                "field": "suppression",
                "before": "new",
                "after": "ignored",
            }.items()
        )
    logger.info(
        "Clash bulk suppress: issues=%s members=%s statements=%s reads=%s unrelated_probe=%s engine_statements=%s",
        n_issues,
        len(histories),
        counter.count,
        len(reads),
        unrelated_query,
        observer.count if observer is not None else None,
    )
    return counter.count


async def test_bulk_suppress_audit_fanout_is_bounded(session):
    """Reads and writes stay bounded as both issue and member counts grow."""
    counts = [await _count_bulk_suppress_queries(session, n) for n in (1, 30, 100)]
    assert counts == [counts[0]] * len(counts), f"query count scaled with issue count: {counts}"


async def test_bulk_suppress_counter_excludes_other_connections(session):
    """An unrelated same-engine query cannot masquerade as an N+1 regression."""
    await _count_bulk_suppress_queries(session, 30, unrelated_query=True)
