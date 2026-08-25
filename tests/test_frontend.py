"""The demo client, served by the backend at `/`."""

from backend.app import FRONTEND_DIR

PNG = b"\x89PNG\r\n\x1a\nfake image bytes"


class TestDemoClient:
    async def test_the_page_is_served_at_the_root(self, api_client):
        response = await api_client.get("/")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert 'id="session-list"' in response.text
        assert 'id="event-log"' in response.text
        assert 'id="prompt-form"' in response.text
        assert 'id="desktop"' in response.text

    async def test_the_page_matches_the_files_on_disk(self, api_client):
        response = await api_client.get("/")

        assert response.text == (FRONTEND_DIR / "index.html").read_text()

    async def test_the_assets_are_served(self, api_client):
        js = await api_client.get("/app.js")
        css = await api_client.get("/style.css")

        assert js.status_code == 200
        assert css.status_code == 200
        assert "EventSource" in js.text
        assert "/sessions/${sessionId}/events" in js.text
        assert "/sessions/${sessionId}/desktop" in js.text
        assert "searchParams" in js.text
        assert "?session=" in js.text


class TestScreenshotBlobs:
    async def test_a_stored_screenshot_is_served_at_its_url(self, api_client, api_app):
        key = await api_app.state.blobs.put(PNG)
        url = api_app.state.blobs.url_for(key)

        response = await api_client.get(url)

        assert response.status_code == 200
        assert response.content == PNG
        assert response.headers["content-type"] == "image/png"

    async def test_an_unknown_blob_is_not_found(self, api_client):
        response = await api_client.get("/blobs/deadbeef.png")

        assert response.status_code == 404

    async def test_a_jpeg_is_served_with_its_media_type(self, api_client, api_app):
        key = await api_app.state.blobs.put(b"jpeg-bytes", suffix=".jpg")

        response = await api_client.get(api_app.state.blobs.url_for(key))

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
