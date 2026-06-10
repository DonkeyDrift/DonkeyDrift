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
    assert frontend_kwargs["env"]["VITE_API_BASE_URL"] == "http://localhost:8001/api"


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
    monkeypatch.setattr("donkeycar.management.base.subprocess.Popen", fake_popen)
    monkeypatch.setattr("donkeycar.management.base.webbrowser.open", opened_urls.append)
    monkeypatch.setattr("donkeycar.management.base.time.sleep", lambda _seconds: None)

    with pytest.raises(SystemExit):
        Web().run(["--path", str(tmp_path / "web_ui"), "--open", "--route", "/drive"])

    assert opened_urls == ["http://localhost:5188/#/drive"]
    assert len(popen_calls) == 2
