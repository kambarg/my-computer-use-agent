"""Settings read from the environment, including the docs switch."""

from pathlib import Path

from backend.config import Settings


def test_defaults_need_no_environment(monkeypatch):
    """A checkout should run against SQLite without any setup."""
    for name in (
        "DATABASE_URL",
        "BLOB_DIR",
        "BLOB_URL_PREFIX",
        "SSE_KEEPALIVE_SECONDS",
        "WORKER_URLS",
        "POOL_RETRY_AFTER_SECONDS",
        "PROVISION_WORKERS",
        "WORKER_IMAGE",
        "WORKER_NETWORK",
        "MAX_WORKERS",
        "ENABLE_DOCS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    assert settings.database_url.startswith("sqlite+aiosqlite://")
    assert settings.blob_dir == Path("./data/blobs")
    assert settings.sse_keepalive_seconds == 15.0
    assert settings.worker_urls == ()
    assert settings.pool_retry_after_seconds == 5
    assert settings.provision_workers is False
    assert settings.max_workers == 8
    assert settings.enable_docs is True


def test_the_environment_wins(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user@db/app")
    monkeypatch.setenv("BLOB_DIR", "/srv/blobs")
    monkeypatch.setenv("BLOB_URL_PREFIX", "/media")
    monkeypatch.setenv("SSE_KEEPALIVE_SECONDS", "30")
    monkeypatch.setenv("WORKER_URLS", "http://w1:8000, http://w2:8000")
    monkeypatch.setenv("POOL_RETRY_AFTER_SECONDS", "12")
    monkeypatch.setenv("PROVISION_WORKERS", "1")
    monkeypatch.setenv("WORKER_IMAGE", "worker:test")
    monkeypatch.setenv("WORKER_NETWORK", "agent")
    monkeypatch.setenv("MAX_WORKERS", "16")
    monkeypatch.setenv("ENABLE_DOCS", "0")

    settings = Settings.from_env()

    assert settings.database_url == "postgresql+asyncpg://user@db/app"
    assert settings.blob_dir == Path("/srv/blobs")
    assert settings.blob_url_prefix == "/media"
    assert settings.sse_keepalive_seconds == 30.0
    assert settings.worker_urls == ("http://w1:8000", "http://w2:8000")
    assert settings.pool_retry_after_seconds == 12
    assert settings.provision_workers is True
    assert settings.worker_image == "worker:test"
    assert settings.worker_network == "agent"
    assert settings.max_workers == 16
    assert settings.enable_docs is False


def test_docs_stay_on_when_the_flag_is_unset(monkeypatch):
    monkeypatch.delenv("ENABLE_DOCS", raising=False)

    assert Settings.from_env().enable_docs is True


def test_docs_turn_off_when_the_flag_is_explicitly_false(monkeypatch):
    monkeypatch.setenv("ENABLE_DOCS", "0")

    assert Settings.from_env().enable_docs is False


def test_docs_turn_on_when_the_flag_is_true(monkeypatch):
    monkeypatch.setenv("ENABLE_DOCS", "true")

    assert Settings.from_env().enable_docs is True
