"""The Compose file is the local topology: Postgres, backend, a pool of workers."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "compose.yaml"
BACKEND_IMAGE = ROOT / "docker/backend.Dockerfile"
WORKER_IMAGE = ROOT / "docker/worker.Dockerfile"


def test_the_compose_file_lives_at_the_repo_root():
    assert COMPOSE.is_file()


def test_the_stack_is_postgres_backend_and_a_worker_pool():
    text = COMPOSE.read_text()

    assert "postgres:" in text
    assert "backend:" in text
    assert "worker-1:" in text
    assert "worker-2:" in text
    assert "WORKER_URLS: http://worker-1:8000,http://worker-2:8000" in text
    assert "postgresql+asyncpg://" in text


def test_only_the_backend_publishes_a_host_port():
    """Worker 6080/5900 stay on the private network; the backend proxies noVNC."""
    text = COMPOSE.read_text()

    assert '"8000:8000"' in text
    assert "6080:6080" not in text
    assert "5900:5900" not in text
    assert "5432:5432" not in text


def test_workers_join_a_user_defined_bridge():
    text = COMPOSE.read_text()

    assert "networks:" in text
    assert "driver: bridge" in text
    assert "agent:" in text


def test_the_backend_image_serves_the_demo_client():
    text = BACKEND_IMAGE.read_text()

    assert "COPY frontend/" in text
    assert "uvicorn" in text
    assert "3.11" in text


def test_the_worker_image_is_the_desktop_plus_the_agent():
    text = WORKER_IMAGE.read_text()

    assert "computer-use-demo" in text
    assert "COPY --chown=computeruse:computeruse worker/" in text
    assert "worker-entrypoint.sh" in text


def test_secrets_are_not_committed():
    example = (ROOT / ".env.example").read_text()
    ignored = (ROOT / ".gitignore").read_text().splitlines()

    assert "ANTHROPIC_API_KEY=" in example
    assert ".env" in ignored


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker is not installed")
def test_compose_config_renders():
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "config"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    rendered = result.stdout
    assert "worker-1" in rendered
    assert "worker-2" in rendered
    assert 'published: "8000"' in rendered
    assert 'published: "6080"' not in rendered
    assert 'published: "5900"' not in rendered
