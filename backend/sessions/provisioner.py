"""Start a dedicated desktop container for a session, and tear it down after.

The tools act on the machine they run on, so concurrency is a container per
session — not a second X display in one process, and not a YAML list of N
workers. A safety cap (`max_workers`) stops a stampede; it is not the pool.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import httpx


class ProvisionFailed(Exception):
    """The container never became reachable; the session has no desktop."""

    def __init__(self, session_id: UUID, message: str) -> None:
        super().__init__(message)
        self.session_id = session_id


@dataclass(frozen=True)
class ProvisionedWorker:
    name: str
    base_url: str
    vnc_url: str


class WorkerProvisioner(Protocol):
    async def start(self, session_id: UUID) -> ProvisionedWorker: ...

    async def stop(self, name: str) -> None: ...


def worker_name_for(session_id: UUID) -> str:
    return f"cu-worker-{session_id}"


class FakeProvisioner:
    """Records start/stop so tests can prove two sessions spawn in parallel."""

    def __init__(self, *, delay: float = 0.0, fail: bool = False) -> None:
        self.delay = delay
        self.fail = fail
        self.started: list[UUID] = []
        self.stopped: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def start(self, session_id: UUID) -> ProvisionedWorker:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self.started.append(session_id)
        try:
            if self.fail:
                raise ProvisionFailed(session_id, "fake provisioner refused")
            if self.delay:
                await asyncio.sleep(self.delay)
            name = worker_name_for(session_id)
            return ProvisionedWorker(
                name=name,
                base_url=f"http://{name}:8000",
                vnc_url=f"http://{name}:6080",
            )
        finally:
            self.in_flight -= 1

    async def stop(self, name: str) -> None:
        self.stopped.append(name)


class DockerProvisioner:
    """Creates worker containers on the Docker daemon the backend can see."""

    def __init__(
        self,
        *,
        image: str,
        network: str,
        api_key: str = "",
        api_provider: str = "anthropic",
        ready_timeout: float = 90.0,
        shm_size: int = 2 * 1024 * 1024 * 1024,
    ) -> None:
        self._image = image
        self._network = network
        self._api_key = api_key
        self._api_provider = api_provider
        self._ready_timeout = ready_timeout
        self._shm_size = shm_size

    def _client(self):
        import docker

        return docker.from_env()

    async def start(self, session_id: UUID) -> ProvisionedWorker:
        name = worker_name_for(session_id)
        try:
            await asyncio.to_thread(self._run_container, name)
        except Exception as exc:
            raise ProvisionFailed(session_id, f"could not start worker: {exc}") from exc
        base_url = f"http://{name}:8000"
        try:
            await self._wait_healthy(base_url)
        except Exception as exc:
            await self.stop(name)
            raise ProvisionFailed(
                session_id, f"worker {name} did not become ready: {exc}"
            ) from exc
        return ProvisionedWorker(
            name=name, base_url=base_url, vnc_url=f"http://{name}:6080"
        )

    async def stop(self, name: str) -> None:
        await asyncio.to_thread(self._remove_container, name)

    def _run_container(self, name: str) -> None:
        client = self._client()
        self._remove_container(name)
        kwargs: dict = {
            "image": self._image,
            "name": name,
            "hostname": name,
            "detach": True,
            "environment": {
                "ANTHROPIC_API_KEY": self._api_key,
                "API_PROVIDER": self._api_provider,
            },
            "shm_size": self._shm_size,
            "init": True,
            "labels": {"computer-use.worker": "1", "computer-use.container": name},
        }
        if self._network:
            kwargs["network"] = self._network
        client.containers.run(**kwargs)

    def _remove_container(self, name: str) -> None:
        import docker.errors

        client = self._client()
        try:
            container = client.containers.get(name)
        except docker.errors.NotFound:
            return
        try:
            container.remove(force=True)
        except docker.errors.APIError:
            return

    async def _wait_healthy(self, base_url: str) -> None:
        deadline = asyncio.get_running_loop().time() + self._ready_timeout
        async with httpx.AsyncClient(timeout=httpx.Timeout(2.0, connect=2.0)) as client:
            while True:
                try:
                    response = await client.get(f"{base_url}/health")
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError(
                        f"{base_url}/health after {self._ready_timeout}s"
                    )
                await asyncio.sleep(1.0)
