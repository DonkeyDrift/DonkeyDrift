"""CORS 白名单默认收紧到回环来源的回归测试。

背景：main.py 旧实现固定 allow_origins=["*"] + allow_credentials=True，
浏览器 Fetch 规范不允许凭据模式下返回通配符 origin，且局域网任意来源
都能带 cookie 打到本机 API。收紧为默认仅回环，需要跨域时通过
DRIVE_WEB_CORS_ORIGINS 显式放开（列表或 "*"），或用
DRIVE_WEB_CORS_ALLOW_ORIGIN_REGEX 走正则。

注意：Starlette 1.x 的 is_allowed_origin() 对 allow_origins 是精确匹配
（不支持 scheme+host 前缀、不剥端口），因此默认白名单必须列全
「回环地址 × 端口」组合——测试要锁住这一点，避免有人把白名单
简化成 http://localhost 后静默放行失败。
"""
import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _reload_main(monkeypatch, origins_env=None, regex_env=None):
    if origins_env is None:
        monkeypatch.delenv("DRIVE_WEB_CORS_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("DRIVE_WEB_CORS_ORIGINS", origins_env)
    if regex_env is None:
        monkeypatch.delenv("DRIVE_WEB_CORS_ALLOW_ORIGIN_REGEX", raising=False)
    else:
        monkeypatch.setenv("DRIVE_WEB_CORS_ALLOW_ORIGIN_REGEX", regex_env)
    sys.modules.pop("main", None)
    return importlib.import_module("main")


def _preflight(main, origin, path="/api/config"):
    client = TestClient(main.app)
    return client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )


def test_default_cors_origins_are_loopback_only(monkeypatch):
    main = _reload_main(monkeypatch)

    origins, regex = main._resolve_cors_config()

    assert "*" not in origins
    assert regex is None
    assert set(origins) == set(main.DEFAULT_CORS_ORIGINS)
    assert all(o.startswith("http://") or o.startswith("https://") for o in origins)


def test_default_origins_cover_loopback_with_dev_and_prod_ports(monkeypatch):
    """Starlette 精确匹配：必须显式列全 localhost:5188 / localhost:8000 等组合。"""
    main = _reload_main(monkeypatch)

    origins = set(main.DEFAULT_CORS_ORIGINS)

    for host in ("localhost", "127.0.0.1", "[::1]"):
        for port in ("", ":5188", ":8000"):
            assert f"http://{host}{port}" in origins
            assert f"https://{host}{port}" in origins


def test_wildcard_opt_in_restores_legacy_behavior(monkeypatch):
    main = _reload_main(monkeypatch, origins_env="*")

    origins, _ = main._resolve_cors_config()

    assert origins == ["*"]


def test_explicit_allowlist_is_honored(monkeypatch):
    main = _reload_main(
        monkeypatch,
        origins_env="http://192.168.1.10:5188, http://car:8000",
    )

    origins, _ = main._resolve_cors_config()

    assert origins == ["http://192.168.1.10:5188", "http://car:8000"]


def test_blank_env_falls_back_to_loopback(monkeypatch):
    main = _reload_main(monkeypatch, origins_env="   ")

    origins, _ = main._resolve_cors_config()

    assert origins == list(main.DEFAULT_CORS_ORIGINS)


def test_regex_option_wildcard_equivalently_allows_any_origin(monkeypatch):
    main = _reload_main(monkeypatch, regex_env="*")

    origins, regex = main._resolve_cors_config()

    assert origins == ["*"]
    assert regex is None


def test_regex_option_complements_allowlist(monkeypatch):
    main = _reload_main(
        monkeypatch,
        origins_env="http://car:8000",
        regex_env=r"https?://.*\.lan(:[0-9]+)?$",
    )

    origins, regex = main._resolve_cors_config()

    assert origins == ["http://car:8000"]
    assert regex == r"https?://.*\.lan(:[0-9]+)?$"


def test_unknown_origin_is_not_reflected_by_cors_middleware(monkeypatch):
    main = _reload_main(monkeypatch)

    response = _preflight(main, "http://evil.example")

    assert "access-control-allow-origin" not in response.headers


def test_loopback_dev_origin_is_allowed_by_cors_middleware(monkeypatch):
    main = _reload_main(monkeypatch)

    response = _preflight(main, "http://localhost:5188")

    assert response.headers.get("access-control-allow-origin") == "http://localhost:5188"


def test_loopback_prod_origin_is_allowed_by_cors_middleware(monkeypatch):
    main = _reload_main(monkeypatch)

    response = _preflight(main, "http://127.0.0.1:8000")

    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:8000"


def test_lan_origin_allowed_only_when_explicitly_configured(monkeypatch):
    denied = _reload_main(monkeypatch)
    assert "access-control-allow-origin" not in _preflight(
        denied, "http://192.168.1.10:5188"
    ).headers

    allowed = _reload_main(monkeypatch, origins_env="http://192.168.1.10:5188")
    assert (
        _preflight(allowed, "http://192.168.1.10:5188").headers.get(
            "access-control-allow-origin"
        )
        == "http://192.168.1.10:5188"
    )


def test_regex_option_allows_matching_lan_origin(monkeypatch):
    main = _reload_main(monkeypatch, regex_env=r"https?://.*\.lan(:[0-9]+)?$")

    response = _preflight(main, "http://car.lan:8000")

    assert response.headers.get("access-control-allow-origin") == "http://car.lan:8000"
