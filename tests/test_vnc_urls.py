from backend.vnc.urls import http_to_ws, vnc_url_from_base


def test_vnc_url_is_the_same_host_on_novnc_port():
    assert vnc_url_from_base("http://worker-1:8000") == "http://worker-1:6080"


def test_https_is_preserved():
    assert vnc_url_from_base("https://desktop.internal:8000") == (
        "https://desktop.internal:6080"
    )


def test_an_explicit_port_can_be_chosen():
    assert vnc_url_from_base("http://w:8000", port=6090) == "http://w:6090"


def test_http_to_ws_matches_the_scheme():
    assert http_to_ws("http://w:6080/websockify") == "ws://w:6080/websockify"
    assert http_to_ws("https://w:6080/websockify") == "wss://w:6080/websockify"
