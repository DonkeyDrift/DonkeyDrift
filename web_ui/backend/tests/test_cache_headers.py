import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class _Resp:
    def __init__(self, content_type: str = ""):
        self.headers = {"content-type": content_type}


def test_assets_are_immutable():
    main = importlib.import_module("main")
    resp = _Resp("text/javascript; charset=utf-8")

    main.apply_cache_headers(resp, "/assets/index-abc123.js")

    assert resp.headers["Cache-Control"] == "public, max-age=31536000, immutable"


def test_html_is_no_cache():
    main = importlib.import_module("main")
    resp = _Resp("text/html; charset=utf-8")

    main.apply_cache_headers(resp, "/")

    assert resp.headers["Cache-Control"] == "no-cache"


def test_api_response_untouched():
    main = importlib.import_module("main")
    resp = _Resp("application/json")

    main.apply_cache_headers(resp, "/api/config")

    assert "Cache-Control" not in resp.headers
