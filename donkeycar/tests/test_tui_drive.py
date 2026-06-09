import sys

from donkeycar.management import tui


class FakeProcess:
    returncode = 0
    pid = 12345

    def __init__(self):
        self.terminated = False
        self.killed = False

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def send_signal(self, signal_value):
        self.terminated = True

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class ProcessingStreamWithoutFileno:
    def write(self, value):
        return len(value)

    def flush(self):
        pass


def test_drive_command_opens_web_console_drive_page(monkeypatch, tmp_path):
    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "myconfig.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cmd = tui.DriveCommand().get_command_line({})

    assert cmd[:2] == ["donkey", "web"]
    assert "--path" in cmd
    assert "--open" in cmd
    assert cmd[cmd.index("--route") + 1] == "/drive"
    assert "manage.py" not in cmd


def test_drive_command_starts_web_console_and_car_process(monkeypatch, tmp_path):
    popen_calls = []
    prompts = iter(["y", ""])

    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "myconfig.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(tui.console, "clear", lambda: None)
    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: next(prompts))

    def fake_popen(cmd_list, **kwargs):
        popen_calls.append((cmd_list, kwargs))
        return FakeProcess()

    monkeypatch.setattr(tui.subprocess, "Popen", fake_popen)

    tui.DriveCommand().execute()

    assert len(popen_calls) == 2
    web_cmd, web_kwargs = popen_calls[0]
    car_cmd, car_kwargs = popen_calls[1]

    assert web_cmd[:2] == ["donkey", "web"]
    assert "--route" in web_cmd
    assert web_cmd[web_cmd.index("--route") + 1] == "/drive"

    assert car_cmd == [sys.executable, "manage.py", "drive"]
    assert car_kwargs["cwd"] == tmp_path
    assert car_kwargs["env"]["DRIVE_API_SERVER_URL"] == "ws://localhost:8000/api/drive/ws"
    assert all("DRIVE_API_SERVER_URL=" not in str(cmd) for cmd, _ in popen_calls)


def test_drive_command_inherits_stdio_without_requiring_fileno(monkeypatch, tmp_path):
    popen_calls = []
    prompts = iter(["y", ""])

    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "myconfig.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(tui.console, "clear", lambda: None)
    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: next(prompts))
    monkeypatch.setattr(tui.sys, "stdout", ProcessingStreamWithoutFileno())
    monkeypatch.setattr(tui.sys, "stderr", ProcessingStreamWithoutFileno())

    def fake_popen(cmd_list, **kwargs):
        popen_calls.append((cmd_list, kwargs))
        return FakeProcess()

    monkeypatch.setattr(tui.subprocess, "Popen", fake_popen)

    tui.DriveCommand().execute()

    assert len(popen_calls) == 2
    for _, popen_kwargs in popen_calls:
        assert popen_kwargs.get("stdout") is None
        assert popen_kwargs.get("stderr") is None


def test_drive_command_does_not_start_without_manage_py(monkeypatch, tmp_path):
    popen_calls = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tui.console, "clear", lambda: None)
    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: "")
    monkeypatch.setattr(tui.subprocess, "Popen", lambda *args, **kwargs: popen_calls.append((args, kwargs)))

    tui.DriveCommand().execute()

    assert popen_calls == []


class PollingProcess(FakeProcess):
    def __init__(self, states):
        super().__init__()
        self.states = list(states)

    def poll(self):
        if len(self.states) > 1:
            return self.states.pop(0)
        return self.states[0]


def test_drive_command_keeps_web_console_when_car_process_exits(monkeypatch):
    web_process = PollingProcess([None, 0])
    car_process = PollingProcess([1, 1])

    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(tui.time, "sleep", lambda *args, **kwargs: None)

    tui.DriveCommand().monitor_processes(web_process, car_process)

    assert web_process.terminated is False
    assert web_process.killed is False
