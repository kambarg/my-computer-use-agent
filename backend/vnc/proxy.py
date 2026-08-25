"""Reverse-proxy a bound worker's noVNC, HTTP and WebSocket.

Worker ports stay on the private network. The client only ever talks to the
backend, which is what lets us refuse a session that has no desktop.
"""

import asyncio
from collections.abc import AsyncIterator, Mapping

import httpx
from fastapi import WebSocket, WebSocketDisconnect
from starlette.responses import StreamingResponse
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}


def _forward_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        key: value for key, value in headers.items() if key.lower() not in HOP_BY_HOP
    }


async def proxy_http(
    client: httpx.AsyncClient,
    *,
    method: str,
    url: str,
    headers: Mapping[str, str],
    query: bytes | str = b"",
) -> StreamingResponse:
    request = client.build_request(
        method,
        url,
        headers=_forward_headers(headers),
        params=httpx.QueryParams(query.decode() if isinstance(query, bytes) else query)
        if query
        else None,
    )
    response = await client.send(request, stream=True)

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()

    return StreamingResponse(
        body(),
        status_code=response.status_code,
        headers=_forward_headers(response.headers),
        media_type=response.headers.get("content-type"),
    )


async def proxy_websocket(client_ws: WebSocket, upstream_url: str) -> None:
    """Copy frames in both directions until either side hangs up."""
    requested = client_ws.scope.get("subprotocols") or ["binary"]
    subprotocol = requested[0] if requested else "binary"
    await client_ws.accept(subprotocol=subprotocol)
    try:
        async with ws_connect(upstream_url, subprotocols=[subprotocol]) as upstream:
            await _copy_until_close(client_ws, upstream)
    except (OSError, ConnectionClosed):
        await _close_quietly(client_ws)


async def _copy_until_close(client_ws: WebSocket, upstream) -> None:
    async def from_client() -> None:
        try:
            while True:
                message = await client_ws.receive()
                if message["type"] == "websocket.disconnect":
                    await upstream.close()
                    return
                data = message.get("bytes")
                if data is not None:
                    await upstream.send(data)
                    continue
                text = message.get("text")
                if text is not None:
                    await upstream.send(text)
        except WebSocketDisconnect:
            await upstream.close()

    async def from_upstream() -> None:
        try:
            async for message in upstream:
                if isinstance(message, bytes):
                    await client_ws.send_bytes(message)
                else:
                    await client_ws.send_text(message)
        except ConnectionClosed:
            pass
        finally:
            await _close_quietly(client_ws)

    tasks = [
        asyncio.create_task(from_client()),
        asyncio.create_task(from_upstream()),
    ]
    _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


async def _close_quietly(client_ws: WebSocket) -> None:
    try:
        await client_ws.close()
    except Exception:
        return
