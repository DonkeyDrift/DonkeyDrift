from donkeycar.management import tui


class FakeProcess:
    returncode = 0

    def wait(self):
        return 0


class ProcessingStreamWithoutFileno:
    def write(self, value):
        return len(value)

    def flush(self):
        pass


def test_createcar_command_inherits_stdio_without_requiring_fileno(monkeypatch, tmp_path):
    popen_kwargs = {}
    popen_cmd = []
    prompts = iter(["mycarweb", "", "n", "y", ""])

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

    tui.CreateCarCommand().execute()

    assert popen_cmd[:2] == ["donkey", "createcar"]
    assert "--path" in popen_cmd
    assert popen_kwargs.get("stdout") is None
    assert popen_kwargs.get("stderr") is None
