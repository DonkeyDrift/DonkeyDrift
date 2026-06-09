from pathlib import Path

from donkeycar.management import tui


class FakeProcess:
    returncode = 0
    pid = 12345

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


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


def test_drive_command_inherits_stdio_without_requiring_fileno(monkeypatch, tmp_path):
    popen_kwargs = {}
    popen_cmd = []
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
        popen_cmd.extend(cmd_list)
        popen_kwargs.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(tui.subprocess, "Popen", fake_popen)

    tui.DriveCommand().execute()

    assert popen_cmd[:2] == ["donkey", "web"]
    assert "--route" in popen_cmd
    assert popen_cmd[popen_cmd.index("--route") + 1] == "/drive"
    assert popen_kwargs.get("stdout") is None
    assert popen_kwargs.get("stderr") is None
