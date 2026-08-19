import importlib
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from conftest import collect_route_paths

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_main_registers_console_router():
    main = importlib.import_module("main")
    routes = collect_route_paths(main.app.routes)
    assert "/api/console/proxy/{ip}" in routes
    assert "/api/console/proxy/{ip}/{path:path}" in routes


def test_validate_ip_accepts_ipv4_and_rejects_others():
    console = importlib.import_module("routers.console")
    assert console._validate_ip("192.168.3.46") == "192.168.3.46"
    with pytest.raises(HTTPException):
        console._validate_ip("example.com")
    with pytest.raises(HTTPException):
        console._validate_ip("::1")


def test_forward_sync_preserves_method_body_and_headers(monkeypatch):
    console = importlib.import_module("routers.console")
    captured = {}

    class FakeResponse:
        status = 200
        headers = {"Content-Type": "text/plain; charset=utf-8"}

        def read(self):
            return b"ACK:UPDATE_OK"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["body"] = req.data
        captured["content_type"] = req.get_header("Content-type")
        return FakeResponse()

    monkeypatch.setattr(console.urllib.request, "urlopen", fake_urlopen)

    status, headers, data = console._forward_sync(
        "http://192.168.3.46/update",
        "POST",
        b"--form--",
        "multipart/form-data; boundary=x",
    )

    assert status == 200
    assert data == b"ACK:UPDATE_OK"
    assert captured["url"] == "http://192.168.3.46/update"
    assert captured["method"] == "POST"
    assert captured["body"] == b"--form--"
    assert captured["content_type"] == "multipart/form-data; boundary=x"
