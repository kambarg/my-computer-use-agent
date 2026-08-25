"""Screenshot bytes, so the event log can display what the agent saw."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status

router = APIRouter(tags=["blobs"])

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


@router.get("/blobs/{key}")
async def read_blob(key: str, request: Request) -> Response:
    data = await request.app.state.blobs.get(key)
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown blob")
    media_type = _MEDIA_TYPES.get(Path(key).suffix.lower(), "application/octet-stream")
    return Response(content=data, media_type=media_type)
