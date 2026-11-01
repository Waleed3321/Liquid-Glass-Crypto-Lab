"""Scanner lease exclusivity, crash recovery and restart behaviour."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.clock import utc_now
from app.db.session import session_scope
from app.models import ScannerRun
from app.repositories.system import SystemRepository


async def test_lease_is_exclusive_and_expires():
    async with session_scope() as session:
        assert await SystemRepository(session).acquire_lease("owner-a", 120, 60) is True

    async with session_scope() as session:
        assert await SystemRepository(session).acquire_lease("owner-b", 120, 60) is False

    async with session_scope() as session:
        lease = await SystemRepository(session).get_lease()
        assert lease is not None
        assert lease.owner == "owner-a"
        lease.expires_at = utc_now() - timedelta(seconds=1)

    async with session_scope() as session:
        assert await SystemRepository(session).acquire_lease("owner-b", 120, 60) is True

    async with session_scope() as session:
        lease = await SystemRepository(session).get_lease()
        assert lease is not None and lease.owner == "owner-b"


async def test_heartbeat_only_updates_the_owner_and_records_ticks():
    async with session_scope() as session:
        repo = SystemRepository(session)
        await repo.acquire_lease("owner-a", 120, 60)
        await repo.heartbeat("owner-b", 120, tick_done=True)

    async with session_scope() as session:
        lease = await SystemRepository(session).get_lease()
        assert lease is not None
        assert lease.last_tick_at is None

    async with session_scope() as session:
        await SystemRepository(session).heartbeat("owner-a", 120, tick_done=True)

    async with session_scope() as session:
        lease = await SystemRepository(session).get_lease()
        assert lease is not None and lease.last_tick_at is not None


async def test_release_lease_lets_another_instance_take_over():
    async with session_scope() as session:
        repo = SystemRepository(session)
        await repo.acquire_lease("owner-a", 120, 60)
        await repo.release_lease("owner-b")
    async with session_scope() as session:
        assert await SystemRepository(session).acquire_lease("owner-b", 120, 60) is False

    async with session_scope() as session:
        repo = SystemRepository(session)
        await repo.release_lease("owner-a")
    async with session_scope() as session:
        assert await SystemRepository(session).acquire_lease("owner-b", 120, 60) is True


async def test_orphaned_running_runs_are_marked_interrupted_on_restart():
    async with session_scope() as session:
        run = await SystemRepository(session).start_run(source="loop")

    async with session_scope() as session:
        recovered = await SystemRepository(session).mark_orphaned_runs()
    assert recovered == 1

    async with session_scope() as session:
        row = (await session.execute(select(ScannerRun))).scalar_one()
    assert row.id == run.id
    assert row.status == "INTERRUPTED"
    assert row.finished_at is not None


async def test_run_counters_are_persisted():
    async with session_scope() as session:
        repo = SystemRepository(session)
        run = await repo.start_run(source="cron")
        await repo.finish_run(
            run, status="COMPLETED", discovered=10, snapshots=8, scored=6, entries=1
        )

    async with session_scope() as session:
        row = (await session.execute(select(ScannerRun))).scalar_one()
        latest = await SystemRepository(session).latest_run()
    assert row.status == "COMPLETED"
    assert row.finished_at is not None
    assert row.duration_ms >= 0
    assert (row.discovered, row.snapshots, row.scored, row.entries) == (10, 8, 6, 1)
    assert latest is not None and latest.id == row.id
