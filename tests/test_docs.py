"""Swagger / OpenAPI are a local convenience, not the demo UI."""

from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.config import Settings
from tests.conftest import client_for


async def test_docs_are_on_by_default():
    async with AsyncClient(
        transport=ASGITransport(app=create_app(Settings(enable_docs=True))),
        base_url="http://test",
    ) as client:
        docs = await client.get("/docs")
        spec = await client.get("/openapi.json")

    assert docs.status_code == 200
    assert spec.status_code == 200
    assert spec.json()["info"]["title"] == "Computer Use Agent Service"


async def test_docs_can_be_turned_off_without_hiding_the_demo(tmp_path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'api.db'}",
        blob_dir=tmp_path / "blobs",
        enable_docs=False,
    )
    async with client_for(create_app(settings)) as client:
        assert (await client.get("/docs")).status_code == 404
        assert (await client.get("/redoc")).status_code == 404
        assert (await client.get("/openapi.json")).status_code == 404
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/")).status_code == 200
