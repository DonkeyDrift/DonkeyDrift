import asyncio
import importlib
import io
import json
import sys
import urllib.error
from pathlib import Path

from conftest import collect_route_paths

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class _FakeRequest:
    """starlette Request 替身：_forward_launch 只用到 await request.body()。"""

    def __init__(self, body: bytes = b"{}"):
        self._body = body

    async def body(self):
        return self._body


def test_main_registers_launch_router():
    main = importlib.import_module("main")
    routes = collect_route_paths(main.app.routes)
    assert "/api/launch/kimi-code-web" in routes
    assert "/api/launch/dsh" in routes


def test_post_to_launcher_posts_body_and_preserves_timeout(monkeypatch):
    launch = importlib.import_module("routers.launch")
    captured = {}

    class FakeResponse:
        status = 200

        def read(self):
            return b'{"status":"ok","url":"http://x:8081/"}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["body"] = req.data
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(launch.urllib.request, "urlopen", fake_urlopen)

    status, payload = launch._post_to_launcher("/api/launch/kimi-code-web", b"{}")

    assert status == 200
    assert payload == b'{"status":"ok","url":"http://x:8081/"}'
    assert captured["url"] == launch.LAUNCHER_BASE_URL + "/api/launch/kimi-code-web"
    assert captured["method"] == "POST"
    assert captured["body"] == b"{}"
    assert captured["timeout"] == launch.FORWARD_TIMEOUT_S


def test_post_to_launcher_passthrough_launcher_business_error(monkeypatch):
    # launcher 的业务错误（400/500）同样带 JSON 体，原样透传
    launch = importlib.import_module("routers.launch")

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 500, "Internal Server Error", {},
            io.BytesIO(b'{"status":"error","error":"boom"}'))

    monkeypatch.setattr(launch.urllib.request, "urlopen", fake_urlopen)

    status, payload = launch._post_to_launcher("/api/launch/dsh", b"{}")
    assert status == 500
    assert payload == b'{"status":"error","error":"boom"}'


def test_forward_launch_kimi_code_web_returns_launcher_json(monkeypatch):
    launch = importlib.import_module("routers.launch")
    captured = {}

    def fake_post(path, body):
        captured["path"] = path
        captured["body"] = body
        return 200, json.dumps(
            {"status": "ok", "url": "http://localhost:8081/"}).encode()

    monkeypatch.setattr(launch, "_post_to_launcher", fake_post)

    resp = asyncio.run(launch.launch_kimi_code_web(_FakeRequest()))

    assert captured["path"] == "/api/launch/kimi-code-web"
    assert captured["body"] == b"{}"
    assert resp.status_code == 200
    assert json.loads(resp.body) == {
        "status": "ok", "url": "http://localhost:8081/"}


def test_forward_launch_launcher_unreachable_returns_502(monkeypatch):
    launch = importlib.import_module("routers.launch")

    def fake_post(path, body):
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(launch, "_post_to_launcher", fake_post)

    resp = asyncio.run(launch.launch_dsh(_FakeRequest()))

    assert resp.status_code == 502
    assert json.loads(resp.body)["status"] == "error"
    assert "无法连接 launcher" in json.loads(resp.body)["error"]


def test_forward_launch_non_json_response_returns_502(monkeypatch):
    launch = importlib.import_module("routers.launch")
    monkeypatch.setattr(
        launch, "_post_to_launcher", lambda path, body: (200, b"not-json"))

    resp = asyncio.run(launch.launch_kimi_code_web(_FakeRequest()))

    assert resp.status_code == 502
    assert json.loads(resp.body)["error"] == "launcher 返回了非 JSON 响应"
