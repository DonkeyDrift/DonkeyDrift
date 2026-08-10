import socket

import pytest

from donkeycar.management.base import Web


def test_web_command_accepts_open_route_options():
    args = Web().parse_args(["--open", "--route", "/drive"])

    assert args.open is True
    assert args.route == "/drive"


def test_web_command_builds_hash_router_frontend_url():
    web = Web()

    assert web._build_frontend_url(5188, None) == "http://localhost:5188/"
    assert web._build_frontend_url(5188, "/") == "http://localhost:5188/"
    assert web._build_frontend_url(5188, "/drive") == "http://localhost:5188/#/drive"
    assert web._build_frontend_url(5188, "drive") == "http://localhost:5188/#/drive"


def test_web_command_passes_backend_url_to_frontend_when_port_changes(monkeypatch, tmp_path):
    frontend_path = tmp_path / "web_ui" / "frontend"
    backend_path = tmp_path / "web_ui" / "backend"
    frontend_path.mkdir(parents=True)
    backend_path.mkdir(parents=True)
    popen_calls = []

    class FakeProcess:
        def __init__(self, return_codes):
            self.return_codes = iter(return_codes)
            self.returncode = None

        def poll(self):
            try:
                self.returncode = next(self.return_codes)
            except StopIteration:
                pass
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode or 0

    processes = [FakeProcess([None, 0]), FakeProcess([None, None])]

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        return processes.pop(0)

    monkeypatch.setattr("donkeycar.management.base.shutil.which", lambda name: "npm")
    monkeypatch.setattr(Web, "_choose_available_port", lambda self, host, preferred_port: preferred_port)
    monkeypatch.setattr("donkeycar.management.base.subprocess.Popen", fake_popen)
    monkeypatch.setattr("donkeycar.management.base.webbrowser.open", lambda _url: None)
    monkeypatch.setattr("donkeycar.management.base.time.sleep", lambda _seconds: None)

    with pytest.raises(SystemExit):
        Web().run(["--path", str(tmp_path / "web_ui"), "--backend-port", "8001"])

    _, frontend_kwargs = popen_calls[1]
    # 前端不再需要 VITE_API_BASE_URL，使用相对路径 /api 并依赖 Vite 代理转发
    # 这样无论是本地访问还是局域网远程访问都能正常工作
    assert "VITE_API_BASE_URL" not in frontend_kwargs["env"]


def test_web_command_opens_requested_route(monkeypatch, tmp_path):
    frontend_path = tmp_path / "web_ui" / "frontend"
    backend_path = tmp_path / "web_ui" / "backend"
    frontend_path.mkdir(parents=True)
    backend_path.mkdir(parents=True)
    opened_urls = []
    popen_calls = []

    class FakeProcess:
        def __init__(self, return_codes):
            self.return_codes = iter(return_codes)
            self.returncode = None

        def poll(self):
            try:
                self.returncode = next(self.return_codes)
            except StopIteration:
                pass
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode or 0

    processes = [FakeProcess([None, 0]), FakeProcess([None, None])]

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        return processes.pop(0)

    monkeypatch.setattr("donkeycar.management.base.shutil.which", lambda name: "npm")
    monkeypatch.setattr(Web, "_choose_available_port", lambda self, host, preferred_port: preferred_port)
    monkeypatch.setattr(Web, "_wait_for_port_ready", lambda self, port, timeout=30.0: True)
    monkeypatch.setattr("donkeycar.management.base.subprocess.Popen", fake_popen)
    monkeypatch.setattr("donkeycar.management.base.webbrowser.open", opened_urls.append)
    monkeypatch.setattr("donkeycar.management.base.time.sleep", lambda _seconds: None)

    with pytest.raises(SystemExit):
        Web().run(["--path", str(tmp_path / "web_ui"), "--open", "--route", "/drive"])

    assert opened_urls == ["http://localhost:5188/#/drive"]
    assert len(popen_calls) == 2


def test_web_command_sets_vite_proxy_target_to_actual_backend_port(monkeypatch, tmp_path):
    """--backend-port 选定端口后，必须把该端口作为 Vite 代理目标传给前端环境，
    否则 Vite 会用默认的 8000；当后端不在 8000 时浏览器 /api 请求会 ECONNREFUSED。"""
    frontend_path = tmp_path / "web_ui" / "frontend"
    backend_path = tmp_path / "web_ui" / "backend"
    frontend_path.mkdir(parents=True)
    backend_path.mkdir(parents=True)
    popen_calls = []

    class FakeProcess:
        def __init__(self, return_codes):
            self.return_codes = iter(return_codes)
            self.returncode = None

        def poll(self):
            try:
                self.returncode = next(self.return_codes)
            except StopIteration:
                pass
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode or 0

    processes = [FakeProcess([None, 0]), FakeProcess([None, None])]

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        return processes.pop(0)

    monkeypatch.setattr("donkeycar.management.base.shutil.which", lambda name: "npm")
    monkeypatch.setattr(Web, "_choose_available_port", lambda self, host, preferred_port: preferred_port)
    monkeypatch.setattr("donkeycar.management.base.subprocess.Popen", fake_popen)
    monkeypatch.setattr("donkeycar.management.base.webbrowser.open", lambda _url: None)
    monkeypatch.setattr("donkeycar.management.base.time.sleep", lambda _seconds: None)

    with pytest.raises(SystemExit):
        Web().run(["--path", str(tmp_path / "web_ui"), "--backend-port", "8100"])

    _, frontend_kwargs = popen_calls[1]
    assert frontend_kwargs["env"]["VITE_API_PROXY_TARGET"] == "http://127.0.0.1:8100"


def test_wait_for_port_ready_detects_listening_and_closed_ports():
    """_wait_for_port_ready 应对监听中的端口返回 True，对未监听端口超时返回 False。"""
    web = Web()

    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        assert web._wait_for_port_ready(port, timeout=2.0) is True

    # socket 已关闭，端口不再监听
    assert web._wait_for_port_ready(port, timeout=0.3) is False


def test_web_command_waits_for_frontend_port_before_opening_browser(monkeypatch, tmp_path):
    """--open 时必须等前端端口就绪再开浏览器。

    Vite 启动需要数秒；若在其监听前打开浏览器，页面会显示无法连接且不会自动恢复。
    """
    frontend_path = tmp_path / "web_ui" / "frontend"
    backend_path = tmp_path / "web_ui" / "backend"
    frontend_path.mkdir(parents=True)
    backend_path.mkdir(parents=True)
    opened_urls = []
    wait_calls = []

    class FakeProcess:
        def __init__(self, return_codes):
            self.return_codes = iter(return_codes)
            self.returncode = None

        def poll(self):
            try:
                self.returncode = next(self.return_codes)
            except StopIteration:
                pass
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode or 0

    processes = [FakeProcess([None, 0]), FakeProcess([None, None])]

    def fake_popen(cmd, **kwargs):
        return processes.pop(0)

    def fake_wait(self, port, timeout=30.0):
        wait_calls.append(port)
        return True

    monkeypatch.setattr("donkeycar.management.base.shutil.which", lambda name: "npm")
    monkeypatch.setattr(Web, "_choose_available_port", lambda self, host, preferred_port: preferred_port)
    monkeypatch.setattr(Web, "_wait_for_port_ready", fake_wait)
    monkeypatch.setattr("donkeycar.management.base.subprocess.Popen", fake_popen)
    monkeypatch.setattr("donkeycar.management.base.webbrowser.open", opened_urls.append)
    monkeypatch.setattr("donkeycar.management.base.time.sleep", lambda _seconds: None)

    with pytest.raises(SystemExit):
        Web().run(["--path", str(tmp_path / "web_ui"), "--open", "--route", "/drive"])

    # 等待的是前端端口（5188），且浏览器最终打开正确的 URL
    assert wait_calls == [5188]
    assert opened_urls == ["http://localhost:5188/#/drive"]


def test_web_command_opens_browser_even_when_frontend_wait_times_out(monkeypatch, tmp_path):
    """前端端口等待超时也仍应打开浏览器（与旧行为一致，由用户自行刷新）。"""
    frontend_path = tmp_path / "web_ui" / "frontend"
    backend_path = tmp_path / "web_ui" / "backend"
    frontend_path.mkdir(parents=True)
    backend_path.mkdir(parents=True)
    opened_urls = []

    class FakeProcess:
        def __init__(self, return_codes):
            self.return_codes = iter(return_codes)
            self.returncode = None

        def poll(self):
            try:
                self.returncode = next(self.return_codes)
            except StopIteration:
                pass
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode or 0

    processes = [FakeProcess([None, 0]), FakeProcess([None, None])]

    def fake_popen(cmd, **kwargs):
        return processes.pop(0)

    monkeypatch.setattr("donkeycar.management.base.shutil.which", lambda name: "npm")
    monkeypatch.setattr(Web, "_choose_available_port", lambda self, host, preferred_port: preferred_port)
    monkeypatch.setattr(Web, "_wait_for_port_ready", lambda self, port, timeout=30.0: False)
    monkeypatch.setattr("donkeycar.management.base.subprocess.Popen", fake_popen)
    monkeypatch.setattr("donkeycar.management.base.webbrowser.open", opened_urls.append)
    monkeypatch.setattr("donkeycar.management.base.time.sleep", lambda _seconds: None)

    with pytest.raises(SystemExit):
        Web().run(["--path", str(tmp_path / "web_ui"), "--open", "--route", "/drive"])

    assert opened_urls == ["http://localhost:5188/#/drive"]
