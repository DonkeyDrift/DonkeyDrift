"""POST /api/trainer/mypc/client-info 契约测试。

mock 掉 zeroconf（mDNS 浏览）、paramiko（SSH whoami 验证）与 socket 层，
覆盖：反解命中 / avahi 回退 / SSH 验证通过与失败 / 环回跳过 / GET 拒绝。
所有 IP 一律用 192.0.2.x（TEST-NET-1 文档占位段），密码用占位口令。
"""
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _build_client():
    from routers import trainer as trainer_router

    app = FastAPI()
    app.include_router(trainer_router.router, prefix="/api/trainer")
    return TestClient(app)


CLIENT_IP = "192.0.2.10"
PLACEHOLDER_PW = "testpass123"


def _post(client, password="", ip=CLIENT_IP):
    return client.post(
        "/api/trainer/mypc/client-info",
        json={"password": password},
        headers={"x-forwarded-for": ip},
    )


def test_client_info_loopback_skips_resolution_and_verification():
    """环回来源（在本机浏览器打开）不做反解也不做 SSH 验证。"""
    with _build_client() as client, \
         patch("routers.trainer._reverse_resolve",
               side_effect=AssertionError("must not resolve loopback")):
        resp = _post(client, password=PLACEHOLDER_PW, ip="127.0.0.1")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "ip": "127.0.0.1",
        "is_loopback": True,
        "hostname": "",
        "username": "",
        "verified": False,
        "ssh": "",
    }


def test_client_info_mdns_hit_guesses_username_without_password():
    """mDNS 反解命中：未给密码时只做用户名猜测，不发起 SSH 验证。"""
    with _build_client() as client, \
         patch("routers.trainer._mdns_name_for_ip", return_value="Testers-MacBook-Pro"):
        resp = _post(client)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ip"] == CLIENT_IP
    assert body["is_loopback"] is False
    assert body["hostname"] == "Testers-MacBook-Pro"
    # macOS 命名是所有格（Testers-MacBook-Pro）→ 去掉词尾 s 猜出 tester
    assert body["username"] == "tester"
    assert body["verified"] is False
    assert body["ssh"] == ""


def test_client_info_falls_back_to_avahi_when_mdns_empty():
    """mDNS 浏览空手时回退 avahi-resolve-address。"""
    class _Proc:
        returncode = 0
        stdout = f"{CLIENT_IP}\tTester-Mac.local\n"

    with _build_client() as client, \
         patch("routers.trainer._mdns_name_for_ip", return_value=""), \
         patch("routers.trainer.shutil.which",
               side_effect=lambda cmd: "/usr/bin/avahi-resolve-address"
               if cmd == "avahi-resolve-address" else None), \
         patch("routers.trainer.subprocess.run", return_value=_Proc()):
        resp = _post(client)

    assert resp.status_code == 200
    body = resp.json()
    assert body["hostname"] == "Tester-Mac.local"
    assert body["username"] == "tester"


class _FakeStdout:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text.encode()


def _fake_ssh_client(captured, whoami="tester", fail=None):
    """构造 paramiko.SSHClient 替身；fail='auth' 时 connect 抛认证异常，
    fail='conn' 时抛连接级异常。"""
    import paramiko

    class _FakeSshClient:
        def set_missing_host_key_policy(self, policy):
            pass

        def connect(self, ip, port, username, password, **kwargs):
            captured.append({"ip": ip, "username": username, "password": password})
            if fail == "auth":
                raise paramiko.AuthenticationException("bad credentials")
            if fail == "conn":
                raise OSError("unreachable")

        def exec_command(self, cmd, timeout=None):
            assert cmd == "whoami"
            return (None, _FakeStdout(f"{whoami}\n"), None)

        def close(self):
            pass

    return _FakeSshClient()


def test_client_info_verifies_username_via_ssh_whoami():
    """给了密码且能连上：用远程 whoami 的权威用户名，verified=True。"""
    captured = []
    with _build_client() as client, \
         patch("routers.trainer._mdns_name_for_ip", return_value="Testers-MacBook-Pro"), \
         patch("paramiko.SSHClient", return_value=_fake_ssh_client(captured)):
        resp = _post(client, password=PLACEHOLDER_PW)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ssh"] == "ok"
    assert body["verified"] is True
    assert body["username"] == "tester"
    # 候选用户名按 guess 优先（tester 先于所有格原形 testers），密码走 body 传入
    assert captured[0]["username"] == "tester"
    assert captured[0]["password"] == PLACEHOLDER_PW


def test_client_info_auth_failed_tries_all_candidates():
    """认证失败：按候选名单逐个尝试，最终 ssh='auth_failed'，保留猜测名。"""
    captured = []
    with _build_client() as client, \
         patch("routers.trainer._mdns_name_for_ip", return_value="Testers-MacBook-Pro"), \
         patch("paramiko.SSHClient",
               return_value=_fake_ssh_client(captured, fail="auth")):
        resp = _post(client, password=PLACEHOLDER_PW)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ssh"] == "auth_failed"
    assert body["verified"] is False
    assert body["username"] == "tester"  # 未验证时退回猜测值
    assert [c["username"] for c in captured] == ["tester", "testers"]


def test_client_info_unreachable_aborts_verification():
    """连接级错误（SSH 没开）立即中止：ssh='unreachable'，不再试下一个候选。"""
    captured = []
    with _build_client() as client, \
         patch("routers.trainer._mdns_name_for_ip", return_value="Testers-MacBook-Pro"), \
         patch("paramiko.SSHClient",
               return_value=_fake_ssh_client(captured, fail="conn")):
        resp = _post(client, password=PLACEHOLDER_PW)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ssh"] == "unreachable"
    assert body["verified"] is False
    assert len(captured) == 1


def test_client_info_get_method_rejected():
    """安全回归：密码绝不走 GET query（会进访问日志），GET 必须 405。"""
    with _build_client() as client:
        resp = client.get("/api/trainer/mypc/client-info")

    assert resp.status_code == 405
