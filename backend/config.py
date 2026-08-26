"""Backend settings, read from the environment."""

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/app.db"
DEFAULT_BLOB_DIR = Path("./data/blobs")
DEFAULT_BLOB_URL_PREFIX = "/blobs"
DEFAULT_SSE_KEEPALIVE_SECONDS = 15.0
DEFAULT_POOL_RETRY_AFTER_SECONDS = 5
DEFAULT_MAX_WORKERS = 8
DEFAULT_WORKER_IMAGE = "computer-use-worker:local"
DEFAULT_WORKER_READY_TIMEOUT = 90.0


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _flag(name: str, *, default: bool) -> bool:
    """Boolean env var that distinguishes unset (use default) from an explicit off."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes"}


def _worker_urls_from_env() -> tuple[str, ...]:
    raw = os.environ.get("WORKER_URLS", "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    blob_dir: Path = DEFAULT_BLOB_DIR
    blob_url_prefix: str = DEFAULT_BLOB_URL_PREFIX
    sse_keepalive_seconds: float = DEFAULT_SSE_KEEPALIVE_SECONDS
    worker_urls: tuple[str, ...] = ()
    pool_retry_after_seconds: int = DEFAULT_POOL_RETRY_AFTER_SECONDS
    provision_workers: bool = False
    worker_image: str = DEFAULT_WORKER_IMAGE
    worker_network: str = ""
    max_workers: int = DEFAULT_MAX_WORKERS
    worker_ready_timeout: float = DEFAULT_WORKER_READY_TIMEOUT
    anthropic_api_key: str = ""
    api_provider: str = "anthropic"
    enable_docs: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
            blob_dir=Path(os.environ.get("BLOB_DIR", DEFAULT_BLOB_DIR)),
            blob_url_prefix=os.environ.get("BLOB_URL_PREFIX", DEFAULT_BLOB_URL_PREFIX),
            sse_keepalive_seconds=float(
                os.environ.get(
                    "SSE_KEEPALIVE_SECONDS", str(DEFAULT_SSE_KEEPALIVE_SECONDS)
                )
            ),
            worker_urls=_worker_urls_from_env(),
            pool_retry_after_seconds=int(
                os.environ.get(
                    "POOL_RETRY_AFTER_SECONDS", str(DEFAULT_POOL_RETRY_AFTER_SECONDS)
                )
            ),
            provision_workers=_truthy("PROVISION_WORKERS"),
            worker_image=os.environ.get("WORKER_IMAGE", DEFAULT_WORKER_IMAGE),
            worker_network=os.environ.get("WORKER_NETWORK", ""),
            max_workers=int(os.environ.get("MAX_WORKERS", str(DEFAULT_MAX_WORKERS))),
            worker_ready_timeout=float(
                os.environ.get(
                    "WORKER_READY_TIMEOUT", str(DEFAULT_WORKER_READY_TIMEOUT)
                )
            ),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            api_provider=os.environ.get("API_PROVIDER", "anthropic"),
            enable_docs=_flag("ENABLE_DOCS", default=True),
        )
