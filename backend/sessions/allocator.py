"""Bind a desktop to a session: reuse, claim, or spawn one.

A session holds a desktop for its lifetime. The first bind either claims a
pre-registered worker (tests / a warm pool) or starts a new container. Later
prompts reuse it. `RUNNING` is the in-flight lock.
"""

import asyncio
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.database import (
    PoolExhausted,
    SessionNotFound,
    SessionRepository,
    SessionStatus,
    Worker,
    WorkerRepository,
)
from backend.sessions.provisioner import (
    WorkerProvisioner,
    worker_name_for,
)


class WorkerAllocator(Protocol):
    """What the session manager needs, so tests can substitute one."""

    async def bind(self, session_id: UUID) -> Worker: ...

    async def mark_idle(self, session_id: UUID) -> None: ...

    async def release(self, session_id: UUID) -> None: ...


class PoolAllocator:
    """Bind a worker to a session, spawning one when a provisioner is set.

    Without a provisioner this is a fixed registry (`WORKER_URLS`). With one,
    each new session gets its own container. `max_workers` is a safety cap,
    not the size of a demo pool — two sessions must start at the same time.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provisioner: WorkerProvisioner | None = None,
        *,
        max_workers: int = 8,
    ) -> None:
        self._factory = session_factory
        self._provisioner = provisioner
        self._max_workers = max_workers
        self._reserve_lock = asyncio.Lock()

    async def bind(self, session_id: UUID) -> Worker:
        """Mark the session running and return the worker it holds or just started."""
        async with self._factory() as db:
            await SessionRepository(db).try_begin_run(session_id)
            workers = WorkerRepository(db)
            existing = await workers.for_session(session_id)
            if existing is not None:
                await db.commit()
                return existing
            if self._provisioner is None:
                worker = await workers.claim(session_id)
                if worker is None:
                    await SessionRepository(db).set_status(
                        session_id, SessionStatus.ACTIVE
                    )
                    await db.commit()
                    raise PoolExhausted()
                await db.commit()
                return worker
            async with self._reserve_lock:
                reserved = await workers.reserve(
                    session_id,
                    name=worker_name_for(session_id),
                    max_workers=self._max_workers,
                )
            if reserved is None:
                await SessionRepository(db).set_status(session_id, SessionStatus.ACTIVE)
                await db.commit()
                raise PoolExhausted()
            await db.commit()

        assert self._provisioner is not None
        try:
            provisioned = await self._provisioner.start(session_id)
        except Exception:
            async with self._factory() as db:
                await WorkerRepository(db).drop_for_session(session_id)
                try:
                    await SessionRepository(db).set_status(
                        session_id, SessionStatus.ACTIVE
                    )
                except SessionNotFound:
                    await db.rollback()
                    raise
                await db.commit()
            raise

        async with self._factory() as db:
            worker = await WorkerRepository(db).register(
                name=provisioned.name,
                base_url=provisioned.base_url,
                vnc_url=provisioned.vnc_url,
            )
            await db.commit()
            return worker

    async def mark_idle(self, session_id: UUID) -> None:
        """The run ended; keep the desktop, allow another prompt."""
        async with self._factory() as db:
            try:
                await SessionRepository(db).set_status(session_id, SessionStatus.ACTIVE)
            except SessionNotFound:
                await db.rollback()
                return
            await db.commit()

    async def release(self, session_id: UUID) -> None:
        """Drop the desktop. Called when the session is deleted."""
        async with self._factory() as db:
            workers = WorkerRepository(db)
            if self._provisioner is not None:
                name = await workers.drop_for_session(session_id)
            else:
                worker = await workers.for_session(session_id)
                name = worker.name if worker is not None else None
                await workers.release(session_id)
            await db.commit()
        if name is not None and self._provisioner is not None:
            await self._provisioner.stop(name)
