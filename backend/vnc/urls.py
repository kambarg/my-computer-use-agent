"""Build the noVNC origin URL for a worker's API URL."""

from urllib.parse import urlsplit, urlunsplit

DEFAULT_NOVNC_PORT = 6080


def vnc_url_from_base(base_url: str, *, port: int = DEFAULT_NOVNC_PORT) -> str:
    """Same host as the worker API, noVNC's port.

    The pool is registered by API URL; the desktop is a different port on the
    same container, unpublished. Deriving it here means the registry does not
    need a second URL unless someone overrides it.
    """
    parts = urlsplit(base_url)
    host = parts.hostname or "localhost"
    netloc = f"{host}:{port}"
    if parts.username:
        userinfo = parts.username
        if parts.password is not None:
            userinfo = f"{userinfo}:{parts.password}"
        netloc = f"{userinfo}@{netloc}"
    return urlunsplit((parts.scheme or "http", netloc, "", "", ""))


def http_to_ws(url: str) -> str:
    parts = urlsplit(url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))
