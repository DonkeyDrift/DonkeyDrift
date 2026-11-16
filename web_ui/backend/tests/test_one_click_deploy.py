import importlib.util
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from install_steps import build_install_steps as shared_build_install_steps

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import mypc_installer

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_PATH = REPO_ROOT / "scripts" / "one_click_deploy.py"

_spec = importlib.util.spec_from_file_location("one_click_deploy", RUNNER_PATH)
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

STEP_NAMES = (
    "prepare-tools",
    "prepare-gym",
    "prepare-venv",
    "install-dependencies",
    "remove-upstream-donkeycar",
    "install-shell-hook",
    "verify-installation",
    "verify-shell-hook",
    "print-summary",
)


def _zsh_or_skip():
    zsh = shutil.which("zsh")
    if not zsh:
        pytest.skip("zsh not available on this host")
    return zsh


def test_mypc_installer_reexports_shared_module():
    import install_steps

    assert mypc_installer.build_install_steps is install_steps.build_install_steps
    assert mypc_installer._build_install_steps is install_steps._build_install_steps
    assert mypc_installer._ps_quote is install_steps._ps_quote
    assert mypc_installer._profile_update_script is install_steps._profile_update_script
    assert mypc_installer._verification_script is install_steps._verification_script
    assert mypc_installer._HOOK_START == install_steps._HOOK_START
    assert mypc_installer._HOOK_END == install_steps._HOOK_END


def test_shared_build_install_steps_keeps_nine_step_contract():
    steps = shared_build_install_steps("macos", "/Users/test/DonkeyDrift", "/Users/test/gym-donkeycar")
    assert tuple(step.name for step in steps) == STEP_NAMES


def test_detect_platform_rejects_unsupported(monkeypatch):
    monkeypatch.setattr(runner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runner.platform, "machine", lambda: "x86_64")
    with pytest.raises(ValueError, match="不支持的平台"):
        runner.detect_platform()


def test_detect_platform_rejects_intel_mac(monkeypatch):
    monkeypatch.setattr(runner.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(runner.platform, "machine", lambda: "x86_64")
    with pytest.raises(ValueError, match="Intel Mac"):
        runner.detect_platform()


def test_default_gym_path_is_repo_sibling():
    assert runner.default_gym_path(Path("/Users/test/DonkeyDrift")) == Path(
        "/Users/test/gym-donkeycar"
    )


def test_deploy_runs_steps_locally(tmp_path, monkeypatch, capsys):
    _zsh_or_skip()
    monkeypatch.setattr(runner, "detect_platform", lambda: "macos")
    steps = [
        runner.InstallStep("prepare-tools", "zsh -lc 'echo tool-ok'"),
        runner.InstallStep("prepare-gym", "zsh -lc 'echo gym-ok'"),
    ]
    monkeypatch.setattr(runner, "_build_install_steps", lambda *a, **k: steps)
    code = runner.deploy(str(tmp_path / "repo"), str(tmp_path / "gym"))
    out = capsys.readouterr().out
    assert code == 0
    assert "tool-ok" in out
    assert "gym-ok" in out
    assert "环境部署完成" in out


def test_deploy_returns_step_exit_code(tmp_path, monkeypatch, capsys):
    _zsh_or_skip()
    monkeypatch.setattr(runner, "detect_platform", lambda: "macos")
    steps = [runner.InstallStep("prepare-tools", "zsh -lc 'exit 3'")]
    monkeypatch.setattr(runner, "_build_install_steps", lambda *a, **k: steps)
    code = runner.deploy(str(tmp_path / "repo"), str(tmp_path / "gym"))
    out = capsys.readouterr().out
    assert code == 3
    assert "prepare-tools 失败" in out
    assert "自动复用" in out


def test_deploy_retries_prepare_venv_with_python_mirror(tmp_path, monkeypatch, capsys):
    _zsh_or_skip()
    monkeypatch.setattr(runner, "detect_platform", lambda: "macos")

    calls = []

    def fake_build(platform, repo, gym, python_mirror=False, remote_home=""):
        calls.append(python_mirror)
        venv_command = (
            "zsh -lc 'echo venv-ok'"
            if python_mirror
            else "zsh -lc 'echo \"Python download timed out\"; exit 1'"
        )
        steps = [
            runner.InstallStep(name, "zsh -lc 'echo ok'")
            for name in STEP_NAMES
        ]
        steps[2] = runner.InstallStep("prepare-venv", venv_command)
        return steps

    monkeypatch.setattr(runner, "_build_install_steps", fake_build)
    code = runner.deploy(str(tmp_path / "repo"), str(tmp_path / "gym"))
    out = capsys.readouterr().out
    assert code == 0
    assert calls == [False, True]
    assert "南大镜像" in out
    assert "venv-ok" in out


def test_run_step_executes_in_neutral_home_cwd(tmp_path):
    _zsh_or_skip()
    step = runner.InstallStep("print-cwd", "zsh -lc 'pwd'")
    code, lines = runner._run_step(step, time.time() + 30)
    assert code == 0
    assert lines[-1] == os.path.expanduser("~")


def test_main_dry_run_prints_steps(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, "detect_platform", lambda: "macos")
    code = runner.main(
        ["--dry-run", "--repo", str(tmp_path / "repo"), "--gym", str(tmp_path / "gym")]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("(dry-run)") == len(STEP_NAMES)
