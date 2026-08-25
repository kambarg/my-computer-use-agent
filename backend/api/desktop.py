"""Per-session desktop: noVNC, proxied so worker ports stay closed."""

from urllib.parse import urljoin
from uuid import UUID

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    WebSocket,
    WebSocketException,
    status,
)
from fastapi.responses import RedirectResponse

from backend.database import SessionNotFound, SessionRepository, WorkerRepository
from backend.vnc.proxy import proxy_http, proxy_websocket
from backend.vnc.urls import http_to_ws

router = APIRouter(prefix="/sessions", tags=["desktop"])


class NoDesktop(Exception):
    """The session exists but has no bound worker (or the worker has no VNC)."""

    def __init__(self, session_id: UUID) -> None:
        super().__init__(f"session {session_id} has no desktop")
        self.session_id = session_id


def _reject_bad_path(path: str) -> None:
    if path.startswith("/") or any(part == ".." for part in path.split("/")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid desktop path")


async def _vnc_origin(app, session_id: UUID) -> str:
    factory = app.state.session_factory
    async with factory() as db:
        await SessionRepository(db).get(session_id)
        worker = await WorkerRepository(db).for_session(session_id)
    if worker is None or not worker.vnc_url:
        raise NoDesktop(session_id)
    return worker.vnc_url.rstrip("/") + "/"


@router.get("/{session_id}/desktop")
@router.get("/{session_id}/desktop/")
async def desktop_entry(session_id: UUID, request: Request) -> RedirectResponse:
    """Send the browser to noVNC, already pointed at this session's stream."""
    await _vnc_origin(request.app, session_id)
    return RedirectResponse(
        url=f"/sessions/{session_id}/desktop/vnc.html?autoconnect=1&resize=scale",
        status_code=307,
    )


@router.api_route("/{session_id}/desktop/{path:path}", methods=["GET", "HEAD"])
async def desktop_http(session_id: UUID, path: str, request: Request):
    origin = await _vnc_origin(request.app, session_id)
    _reject_bad_path(path)
    return await proxy_http(
        request.app.state.http,
        method=request.method,
        url=urljoin(origin, path),
        headers=request.headers,
        query=request.scope.get("query_string", b""),
    )


@router.websocket("/{session_id}/desktop/{path:path}")
async def desktop_ws(session_id: UUID, path: str, websocket: WebSocket) -> None:
    try:
        origin = await _vnc_origin(websocket.app, session_id)
    except SessionNotFound as exc:
        raise WebSocketException(code=1008, reason=str(exc)) from exc
    except NoDesktop as exc:
        raise WebSocketException(code=1008, reason=str(exc)) from exc
    if path.startswith("/") or any(part == ".." for part in path.split("/")):
        raise WebSocketException(code=1008, reason="invalid desktop path")
    query = websocket.scope.get("query_string", b"")
    suffix = f"?{query.decode()}" if query else ""
    await proxy_websocket(websocket, http_to_ws(urljoin(origin, path)) + suffix)
