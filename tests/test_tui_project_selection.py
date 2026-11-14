"""TUI 项目选择/路径输入辅助函数测试。

覆盖项目不在默认扫描目录（~/projects）下时的手动输入兜底链路，
以及 DriveCommand 无车辆进程时的命令预览。
"""
from pathlib import Path

import pytest

from donkeycar.management import tui


@pytest.fixture
def mycar_project(tmp_path):
    """构造一个有效的 mycar 项目目录（同时含 manage.py 与 myconfig.py）。"""
    project = tmp_path / "mycar"
    project.mkdir()
    (project / "manage.py").write_text("# manage\n")
    (project / "myconfig.py").write_text("# myconfig\n")
    return project


class FakePrompt:
    """脚本化的 rich Prompt 替身：依次返回预置回答。"""

    answers = []

    @classmethod
    def ask(cls, prompt_text, **kwargs):
        assert cls.answers, f"未预置 Prompt 回答: {prompt_text}"
        return cls.answers.pop(0)


@pytest.fixture
def fake_prompt(monkeypatch):
    monkeypatch.setattr(tui, "Prompt", FakePrompt)
    FakePrompt.answers = []
    return FakePrompt


@pytest.fixture
def no_rc(monkeypatch):
    """隔离真实的 ~/.donkeyrc，避免测试污染 last_project_path。"""
    monkeypatch.setattr(tui, "rc_handler", None)


class TestResolveProjectInput:
    def test_accepts_valid_absolute_path(self, mycar_project):
        assert tui._resolve_project_input(str(mycar_project)) == mycar_project.resolve()

    def test_accepts_relative_path(self, tmp_path, monkeypatch, mycar_project):
        monkeypatch.chdir(tmp_path)
        assert tui._resolve_project_input("mycar") == mycar_project.resolve()

    def test_rejects_directory_without_project_files(self, tmp_path):
        empty = tmp_path / "not_a_car"
        empty.mkdir()
        assert tui._resolve_project_input(str(empty)) is None

    def test_rejects_nonexistent_path(self, tmp_path):
        assert tui._resolve_project_input(str(tmp_path / "missing")) is None


class TestPromptProjectPath:
    def test_accepts_valid_path(self, fake_prompt, mycar_project):
        fake_prompt.answers = [str(mycar_project)]
        assert tui._prompt_project_path() == mycar_project.resolve()

    def test_cancel_returns_none(self, fake_prompt):
        fake_prompt.answers = ["0"]
        assert tui._prompt_project_path() is None

    def test_empty_input_returns_none(self, fake_prompt):
        fake_prompt.answers = [""]
        assert tui._prompt_project_path() is None

    def test_reprompts_after_invalid_then_accepts(self, fake_prompt, mycar_project):
        fake_prompt.answers = [str(mycar_project / "nope"), str(mycar_project)]
        assert tui._prompt_project_path() == mycar_project.resolve()

    def test_supports_home_expansion(self, fake_prompt, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        project = tmp_path / "homecar"
        project.mkdir()
        (project / "manage.py").write_text("")
        (project / "myconfig.py").write_text("")
        fake_prompt.answers = ["~/homecar"]
        assert tui._prompt_project_path() == project.resolve()


class TestChooseProject:
    def test_select_by_index(self, fake_prompt, mycar_project, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        (other / "manage.py").write_text("")
        (other / "myconfig.py").write_text("")
        fake_prompt.answers = ["2"]
        assert tui._choose_project([mycar_project, other]) == other

    def test_select_by_pasted_path(self, fake_prompt, mycar_project, tmp_path):
        other = tmp_path / "elsewhere" / "mycar2"
        other.mkdir(parents=True)
        (other / "manage.py").write_text("")
        (other / "myconfig.py").write_text("")
        fake_prompt.answers = [str(other)]
        assert tui._choose_project([mycar_project]) == other.resolve()

    def test_cancel(self, fake_prompt, mycar_project):
        fake_prompt.answers = ["0"]
        assert tui._choose_project([mycar_project]) is None


class TestOpenProjectCommand:
    def test_manual_input_when_scan_finds_nothing(self, fake_prompt, no_rc,
                                                  monkeypatch, tmp_path,
                                                  mycar_project):
        """~/projects 扫描不到项目时，应允许手动输入任意路径下的项目。"""
        monkeypatch.chdir(tmp_path)
        fake_prompt.answers = [str(mycar_project), ""]
        tui.OpenProjectCommand().execute()
        assert Path.cwd() == mycar_project.resolve()


class TestDrivePreviewCommand:
    def _cmd(self):
        return tui.DriveCommand()

    def test_preview_with_car_process(self):
        cmd = self._cmd()
        preview = cmd.get_preview_command(
            ["donkey", "web"], ["python", "manage.py", "drive"],
            drive_api_server_url="ws://localhost:8000/api/drive/ws")
        assert "manage.py drive" in preview
        assert "DRIVE_API_SERVER_URL=ws://localhost:8000/api/drive/ws" in preview

    def test_preview_without_car_process_omits_vehicle_section(self):
        cmd = self._cmd()
        preview = cmd.get_preview_command(
            ["donkey", "web"], None,
            drive_api_server_url="ws://localhost:8000/api/drive/ws")
        assert "manage.py" not in preview
        assert "DRIVE_API_SERVER_URL" not in preview
        assert "donkey web" in preview

    def test_preview_without_car_process_keeps_probe_flag_out(self):
        cmd = self._cmd()
        preview = cmd.get_preview_command(None, None, probe=True)
        assert "DRIVE_WEBRTC_LATENCY_PROBE" not in preview
