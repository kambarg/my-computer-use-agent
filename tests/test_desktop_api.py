"""Per-session noVNC, proxied through the backend."""

from uuid import UUID, uuid4

import pytest
import websockets
from fastapi import HTTPException
from httpx import AsyncClient
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocketDisconnect

from backend.api.desktop import _reject_bad_path
from backend.app import create_app
from backend.config import Settings
from backend.database import WorkerRepository
from tests.conftest import serve_app


async def _vnc_html(request):
    flag = request.query_params.get("autoconnect", "")
    return HTMLResponse(f"<html>novnc autoconnect={flag}</html>")


async def _asset(_request):
    return PlainTextResponse("ui-js", media_type="application/javascript")


async def _echo(websocket):
    await websocket.accept(subprotocol="binary")
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                await websocket.send_bytes(message["bytes"])
            elif message.get("text") is not None:
                await websocket.send_text(message["text"])
    except WebSocketDisconnect:
        return


def fake_novnc():
    return Starlette(
        routes=[
            Route("/vnc.html", _vnc_html),
            Route("/app/ui.js", _asset),
            WebSocketRoute("/websockify", _echo),
        ]
    )


async def bind_session(app, session_id: UUID, vnc_url: str) -> None:
    async with app.state.session_factory() as db:
        await WorkerRepository(db).register(
            name="desktop-1",
            base_url="http://worker.internal:8000",
            vnc_url=vnc_url,
        )
        claimed = await WorkerRepository(db).claim(session_id)
        assert claimed is not None
        await db.commit()


async def create_session(client) -> UUID:
    response = await client.post("/sessions")
    assert response.status_code == 201
    return UUID(response.json()["id"])


class TestDesktopHttp:
    async def test_an_unknown_session_is_not_found(self, api_client):
        response = await api_client.get(f"/sessions/{uuid4()}/desktop")

        assert response.status_code == 404

    async def test_a_session_without_a_worker_has_no_desktop(self, api_client):
        session_id = await create_session(api_client)

        response = await api_client.get(f"/sessions/{session_id}/desktop")

        assert response.status_code == 409
        assert "no desktop" in response.json()["detail"]

    async def test_the_entry_redirects_to_novnc(self, api_app, api_client):
        session_id = await create_session(api_client)
        await bind_session(api_app, session_id, "http://127.0.0.1:9")

        response = await api_client.get(
            f"/sessions/{session_id}/desktop", follow_redirects=False
        )

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"/sessions/{session_id}/desktop/vnc.html?autoconnect=1&resize=scale"
        )

    async def test_assets_are_fetched_from_the_worker(self, settings):
        async with serve_app(fake_novnc()) as (vnc_url, _novnc):
            app = create_app(
                Settings(
                    database_url=settings.database_url,
                    blob_dir=settings.blob_dir,
                )
            )
            async with serve_app(app) as (backend_url, started):
                async with AsyncClient(base_url=backend_url, timeout=None) as client:
                    session_id = await create_session(client)
                    await bind_session(started, session_id, vnc_url)
                    page = await client.get(
                        f"/sessions/{session_id}/desktop/vnc.html",
                        params={"autoconnect": "1"},
                    )
                    asset = await client.get(
                        f"/sessions/{session_id}/desktop/app/ui.js"
                    )

        assert page.status_code == 200
        assert "autoconnect=1" in page.text
        assert asset.text == "ui-js"


def test_dotdot_paths_are_rejected():
    """Starlette collapses `..` in URLs; this is the backstop if one still arrives."""
    with pytest.raises(HTTPException) as caught:
        _reject_bad_path("foo/../secret")

    assert caught.value.status_code == 400


class TestDesktopWebSocket:
    async def test_frames_are_copied_in_both_directions(self, settings):
        async with serve_app(fake_novnc()) as (vnc_url, _novnc):
            app = create_app(
                Settings(
                    database_url=settings.database_url,
                    blob_dir=settings.blob_dir,
                )
            )
            async with serve_app(app) as (backend_url, started):
                async with AsyncClient(base_url=backend_url, timeout=None) as client:
                    session_id = await create_session(client)
                    await bind_session(started, session_id, vnc_url)

                ws_url = (
                    backend_url.replace("http://", "ws://")
                    + f"/sessions/{session_id}/desktop/websockify"
                )
                async with websockets.connect(
                    ws_url, subprotocols=["binary"]
                ) as socket:
                    await socket.send(b"frame")
                    assert await socket.recv() == b"frame"
