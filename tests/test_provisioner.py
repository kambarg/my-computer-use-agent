"""Each session gets its own worker; two binds must run at the same time."""

import asyncio
import time

import pytest

from backend.database import (
    PoolExhausted,
    SessionRepository,
    SessionStatus,
    WorkerRepository,
)
from backend.sessions import PoolAllocator
from backend.sessions.provisioner import (
    FakeProvisioner,
    ProvisionFailed,
    worker_name_for,
)


async def _session(session_factory):
    async with session_factory() as db:
        session = await SessionRepository(db).create()
        await db.commit()
        return session.id


class TestProvisionOnBind:
    async def test_the_first_bind_starts_a_container(self, session_factory):
        session_id = await _session(session_factory)
        provisioner = FakeProvisioner()

        bound = await PoolAllocator(session_factory, provisioner, max_workers=8).bind(
            session_id
        )

        assert bound.name == worker_name_for(session_id)
        assert bound.base_url == f"http://{bound.name}:8000"
        assert provisioner.started == [session_id]

    async def test_a_later_bind_does_not_start_another_container(self, session_factory):
        session_id = await _session(session_factory)
        provisioner = FakeProvisioner()
        allocator = PoolAllocator(session_factory, provisioner, max_workers=8)
        await allocator.bind(session_id)
        await allocator.mark_idle(session_id)

        await allocator.bind(session_id)

        assert provisioner.started == [session_id]

    async def test_two_sessions_are_provisioned_in_parallel(self, session_factory):
        first = await _session(session_factory)
        second = await _session(session_factory)
        provisioner = FakeProvisioner(delay=0.25)
        allocator = PoolAllocator(session_factory, provisioner, max_workers=8)

        started = time.perf_counter()
        bound = await asyncio.gather(allocator.bind(first), allocator.bind(second))
        elapsed = time.perf_counter() - started

        assert {worker.session_id for worker in bound} == {first, second}
        assert set(provisioner.started) == {first, second}
        assert provisioner.max_in_flight == 2
        assert elapsed < 0.45

    async def test_the_cap_is_a_safety_limit_not_a_queue(self, session_factory):
        first = await _session(session_factory)
        second = await _session(session_factory)
        provisioner = FakeProvisioner()
        allocator = PoolAllocator(session_factory, provisioner, max_workers=1)

        await allocator.bind(first)
        with pytest.raises(PoolExhausted):
            await allocator.bind(second)

        assert provisioner.started == [first]

    async def test_a_failed_start_frees_the_slot_and_the_session(self, session_factory):
        session_id = await _session(session_factory)
        provisioner = FakeProvisioner(fail=True)
        allocator = PoolAllocator(session_factory, provisioner, max_workers=8)

        with pytest.raises(ProvisionFailed):
            await allocator.bind(session_id)

        async with session_factory() as db:
            assert (await SessionRepository(db).get(session_id)).status is (
                SessionStatus.ACTIVE
            )
            assert await WorkerRepository(db).for_session(session_id) is None
            assert await WorkerRepository(db).count() == 0

    async def test_release_stops_the_container(self, session_factory):
        session_id = await _session(session_factory)
        provisioner = FakeProvisioner()
        allocator = PoolAllocator(session_factory, provisioner, max_workers=8)
        bound = await allocator.bind(session_id)

        await allocator.release(session_id)

        assert provisioner.stopped == [bound.name]
        async with session_factory() as db:
            assert await WorkerRepository(db).for_session(session_id) is None
