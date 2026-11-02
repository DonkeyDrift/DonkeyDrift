import asyncio
import base64
import gzip
import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import mypc_installer


MAC_REPO = "/Users/test/My Projects/DonkeyDrift"
MAC_GYM = "/Users/test/My Projects/GymDonkeyCar"
WIN_REPO = r"C:\Users\Test\My Projects\DonkeyDrift"
WIN_GYM = r"C:\Users\Test\My Projects\GymDonkeyCar"
PINS = (
    "numpy==1.26.4",
    "scipy==1.17.1",
    "opencv-python-headless==4.11.0.86",
    "gymnasium==1.3.0",
)


def _zsh_or_skip():
    zsh = shutil.which("zsh")
    if not zsh:
        pytest.skip("zsh not available on this host")
    return zsh


# ----------------------------------------------------------------------
# Fakes for the paramiko SSH layer
# ----------------------------------------------------------------------
class FakeChannel:
    def __init__(self, data=b"", exit_code=0, never_ready=False, on_poll=None):
        self._data = data
        self.exit_code = exit_code
        self.never_ready = never_ready
        self.on_poll = on_poll
        self.closed = False

    def recv_ready(self):
        return len(self._data) > 0

    def recv(self, n):
        chunk, self._data = self._data[:n], self._data[n:]
        return chunk

    def exit_status_ready(self):
        if self.on_poll is not None:
            self.on_poll()
        return not self.never_ready and len(self._data) == 0

    def recv_exit_status(self):
        return self.exit_code

    def close(self):
        self.closed = True


class FakeStdout:
    def __init__(self, channel):
        self.channel = channel


class FakeSsh:
    def __init__(self, handler=None):
        self.handler = handler or (lambda command, index: (b"", 0))
        self.commands = []
        self.channels = []
        self.command_timeouts = []
        self.closed = False

    def exec_command(self, command, get_pty=False, timeout=None):
        self.commands.append(command)
        self.command_timeouts.append(timeout)
        result = self.handler(command, len(self.commands))
        if isinstance(result, FakeChannel):
            channel = result
        else:
            data, exit_code = result
            if isinstance(data, str):
                data = data.encode()
            channel = FakeChannel(data, exit_code)
        self.channels.append(channel)
        return None, FakeStdout(channel), None

    def close(self):
        self.closed = True


class BlockingStartSsh(FakeSsh):
    def __init__(self):
        super().__init__()
        self.exec_started = threading.Event()
        self.connection_closed = threading.Event()

    def exec_command(self, command, get_pty=False, timeout=None):
        self.commands.append(command)
        self.command_timeouts.append(timeout)
        self.exec_started.set()
        self.connection_closed.wait()
        raise OSError("SSH channel closed")

    def close(self):
        self.closed = True
        self.connection_closed.set()


def _platform_handler(platform="macos", extra=None):
    def handle(command, index):
        if index == 1:
            if platform == "macos":
                return b"Darwin\narm64\n", 0
            if platform == "intel":
                return b"Darwin\nx86_64\n", 0
            if platform == "linux":
                return b"Linux\nx86_64\n", 0
            return b"uname is not recognized\n", 1
        if index == 2 and platform == "windows":
            return b"DonkeyDriftPlatform=windows\n", 0
        if extra is not None:
            return extra(command, index)
        return b"ok\n", 0

    return handle


def _install(ssh, **kwargs):
    logs = queue.Queue()
    defaults = dict(
        host="192.168.1.10",
        user="u",
        password="p",
        repo_path=MAC_REPO,
        gym_path=MAC_GYM,
        log_queue=logs,
    )
    defaults.update(kwargs)
    with patch.object(mypc_installer, "_open_ssh", return_value=ssh):
        code = mypc_installer.install_mypc_environment(**defaults)
    drained = []
    while not logs.empty():
        drained.append(logs.get())
    return code, drained


def _decode_powershell(command):
    encoded = command.rsplit(" ", 1)[-1]
    script = base64.b64decode(encoded).decode("utf-16-le")
    compressed = re.search(r"\$ddGzip='([A-Za-z0-9+/=]+)'", script)
    if compressed:
        return gzip.decompress(base64.b64decode(compressed.group(1))).decode("utf-8")
    return script


def _step_commands(platform, windows=False):
    steps = mypc_installer.build_install_steps(
        platform, WIN_REPO if windows else MAC_REPO, WIN_GYM if windows else MAC_GYM
    )
    return steps, [
        _decode_powershell(step.command) if windows else step.command
        for step in steps
    ]


# ----------------------------------------------------------------------
# Command plans
# ----------------------------------------------------------------------
def test_macos_plan_uses_zsh_uv_shared_venv_and_exact_dependencies():
    steps, commands = _step_commands("macos")
    scripts = [command.removeprefix("zsh -lc ") for command in commands]
    joined = "\n".join(scripts)

    assert steps
    assert all(command.startswith("zsh -lc ") for command in commands)
    assert "command -v uv" in joined
    assert "command -v git" in joined
    assert "uv venv --python 3.11" in joined
    assert f"{MAC_REPO}/.venv" in joined
    assert f"{MAC_GYM}/.venv" not in joined
    assert f"{MAC_REPO}[macos,dev]" in joined
    for pin in PINS:
        assert pin in joined
    assert "https://pypi.tuna.tsinghua.edu.cn/simple" in joined
    assert "uv sync" not in joined
    assert "uv lock" not in joined
    assert "requirements-lock.txt" not in joined


def test_windows_plan_is_encoded_powershell_with_pc_dev_extras():
    _, scripts = _step_commands("windows", windows=True)
    joined = "\n".join(scripts)

    assert "Get-Command uv" in joined
    assert "Get-Command git" in joined
    assert "uv venv --python 3.11" in joined
    assert f"{WIN_REPO}\\.venv\\Scripts\\python.exe" in joined
    assert f"{WIN_REPO}[pc,dev]" in joined
    assert "[macos,dev]" not in joined
    for pin in PINS:
        assert pin in joined
    assert "https://pypi.tuna.tsinghua.edu.cn/simple" in joined


def test_gym_step_reuses_existing_repo_and_otherwise_clones_only_upstream():
    _, commands = _step_commands("macos")
    gym_script = next(command for command in commands if "gym-donkeycar" in command)

    assert "https://github.com/tawnkramer/gym-donkeycar" in gym_script
    assert "rev-parse HEAD" in gym_script
    assert ".git" in gym_script
    assert "git clone" in gym_script
    assert "rm -rf" not in gym_script


def test_venv_step_reuses_existing_environment_without_deleting_it():
    _, commands = _step_commands("macos")
    venv_script = next(command for command in commands if "uv venv --python 3.11" in command)

    assert "if" in venv_script
    assert ".venv" in venv_script
    assert "rm -rf" not in venv_script
    assert "unlink" not in venv_script


def test_upstream_donkeycar_is_removed_and_only_donkeydrifter_is_reinstalled():
    _, commands = _step_commands("macos")
    repair = next(command for command in commands if "uv pip uninstall" in command)

    assert "uv pip show" in repair
    assert "donkeycar" in repair
    assert repair.count(" -e ") == 1
    assert f"{MAC_REPO}[macos,dev]" in repair
    assert MAC_GYM not in repair
    assert "donkeydrifter" in repair


@pytest.mark.parametrize("platform,windows,extras", [
    ("macos", False, "macos,dev"),
    ("windows", True, "pc,dev"),
])
def test_install_gives_dd_and_gym_separate_editable_flags(platform, windows, extras):
    steps = mypc_installer.build_install_steps(
        platform, WIN_REPO if windows else MAC_REPO, WIN_GYM if windows else MAC_GYM
    )
    install = next(step for step in steps if step.name == "install-dependencies")
    script = (_decode_powershell(install.command) if windows
              else shlex.split(install.command)[2])
    repo = WIN_REPO if windows else MAC_REPO
    gym = WIN_GYM if windows else MAC_GYM

    assert script.count(" -e ") == 2
    assert re.search(r"-e\s+['\"]?" + re.escape(f"{repo}[{extras}]"), script)
    assert re.search(r"-e\s+['\"]?" + re.escape(gym), script)


def test_final_verification_rejects_upstream_donkeycar_distribution():
    verify = mypc_installer._verification_script("macos")

    assert "PackageNotFoundError" in verify
    assert "distribution('donkeydrifter')" in verify
    assert "distribution('gym_donkeycar')" in verify
    assert "distribution('donkeycar')" in verify


def test_macos_hook_is_idempotent_and_covers_both_directory_trees():
    _, commands = _step_commands("macos")
    hook = next(command for command in commands if ".zshrc" in command)
    compressed = base64.b64decode(re.search(r"DD_HOOK_B64=([A-Za-z0-9+/=]+)", hook).group(1))
    decoded = gzip.decompress(compressed).decode()

    assert "add-zsh-hook chpwd" in decoded
    assert MAC_REPO in decoded
    assert MAC_GYM in decoded
    assert f"{MAC_REPO}/.venv" in decoded
    assert "deactivate" in decoded
    assert "donkeydrift-auto-activate" in decoded
    assert "DD_HOOK_B64" in hook


def test_windows_hook_targets_current_profile_and_restores_on_exit():
    _, scripts = _step_commands("windows", windows=True)
    hook = next(script for script in scripts if "DD_HOOK_B64" in script)
    encoded = re.search(r"DD_HOOK_B64='([A-Za-z0-9+/=]+)'", hook).group(1)
    decoded = gzip.decompress(base64.b64decode(encoded)).decode()

    assert "$PROFILE" in hook
    assert WIN_REPO in decoded
    assert WIN_GYM in decoded
    assert "Activate.ps1" in decoded
    assert "deactivate" in decoded
    assert "donkeydrift-auto-activate" in decoded


def _update_profile_for_test(profile, block, windows=False):
    compressed = gzip.compress(block.encode("utf-8"), mtime=0)
    env = dict(os.environ, DD_HOOK_B64=base64.b64encode(compressed).decode())
    if windows:
        env["DD_HOOK_WINDOWS"] = "1"
    subprocess.run(
        [sys.executable, "-c", mypc_installer._profile_update_script(), str(profile)],
        env=env,
        check=True,
        capture_output=True,
    )


@pytest.mark.parametrize("encoding,bom,newline", [
    ("utf-8", b"\xef\xbb\xbf", "\r\n"),
    ("utf-16-le", b"\xff\xfe", "\r\n"),
    ("utf-8", b"", "\n"),
])
def test_profile_update_preserves_encoding_bom_and_newlines(
    tmp_path, encoding, bom, newline
):
    profile = tmp_path / "profile.ps1"
    original = f"# 用户设置 café{newline}$existing = '值'{newline}"
    profile.write_bytes(bom + original.encode(encoding))
    block = (
        f"{mypc_installer._HOOK_START}\n$DD = '仓库'\n"
        f"{mypc_installer._HOOK_END}\n"
    )

    _update_profile_for_test(profile, block, windows=True)
    first = profile.read_bytes()
    _update_profile_for_test(profile, block, windows=True)

    assert profile.read_bytes() == first
    assert first.startswith(bom)
    text = first[len(bom):].decode(encoding)
    assert "# 用户设置 café" in text
    assert "$existing = '值'" in text
    assert "$DD = '仓库'" in text
    assert text.count(mypc_installer._HOOK_START) == 1
    assert text.count(mypc_installer._HOOK_END) == 1
    if newline == "\r\n":
        assert "\n" not in text.replace("\r\n", "")
    else:
        assert "\r" not in text


def test_windows_new_profile_defaults_to_utf8_bom(tmp_path):
    profile = tmp_path / "Documents" / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1"
    block = f"{mypc_installer._HOOK_START}\n$DD = '仓库'\n{mypc_installer._HOOK_END}\n"

    _update_profile_for_test(profile, block, windows=True)

    data = profile.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")
    assert "$DD = '仓库'" in data.decode("utf-8-sig")


def test_verification_steps_cover_install_imports_cli_gym_and_activation():
    _, commands = _step_commands("macos")
    verify = next(command for command in commands if "uv pip check" in command)
    activation = next(command for command in commands if "zsh -ic" in command)

    assert "donkeycar.__file__" in verify
    assert "gym_donkeycar.__file__" in verify
    assert "tensorflow" in verify
    assert "list_physical_devices" in verify
    assert "numpy" in verify
    assert "donkey --help" in verify
    assert "gymnasium.envs.registry" in verify
    assert "$VIRTUAL_ENV" in activation
    assert MAC_GYM in activation


def test_summary_includes_tool_repositories_versions_gpu_and_hook():
    _, commands = _step_commands("macos")
    summary = commands[-1]

    assert "uv --version" in summary
    assert "rev-parse HEAD" in summary
    assert "Python:" in summary
    assert "TensorFlow:" in summary
    assert "numpy:" in summary
    assert "GPU:" in summary
    assert "Hook:" in summary


def test_windows_raw_commands_fit_cmd_limit_with_special_character_paths():
    repo = "C:\\Users\\Test\\O'Brien $(whoami) `whoami` \"My Projects\"\\DonkeyDrift"
    gym = "C:\\Users\\Test\\O'Brien $(whoami) `whoami` \"My Projects\"\\GymDonkeyCar"
    steps = mypc_installer.build_install_steps("windows", repo, gym)

    lengths = {step.name: len(step.command) for step in steps}
    assert all(length <= 8191 for length in lengths.values()), lengths


def test_windows_user_paths_are_powershell_single_quoted_everywhere():
    repo = "C:\\Users\\Test\\O'Brien $(whoami) `whoami` \"My Projects\"\\DonkeyDrift"
    gym = "C:\\Users\\Test\\O'Brien $(whoami) `whoami` \"My Projects\"\\GymDonkeyCar"
    steps = mypc_installer.build_install_steps("windows", repo, gym)
    scripts = {step.name: _decode_powershell(step.command) for step in steps}

    tools_error = f"DonkeyDrift 仓库不存在或不是 Git 仓库: {repo}"
    assert f"throw {mypc_installer._ps_quote(tools_error)}" in scripts["prepare-tools"]
    assert f"Write-Output {mypc_installer._ps_quote(f'DD path: {repo}')}" in scripts["print-summary"]
    assert f"Write-Output {mypc_installer._ps_quote(f'Gym path: {gym}')}" in scripts["print-summary"]
    venv_summary = f"Venv: {repo}\\.venv"
    assert f"Write-Output {mypc_installer._ps_quote(venv_summary)}" in scripts["print-summary"]


def test_macos_summary_cannot_execute_path_shell_substitutions(tmp_path):
    repo = str(tmp_path / "DD $(touch DD_DOLLAR) `touch DD_BACKTICK` ' \" space")
    gym = str(tmp_path / "Gym $(touch GYM_DOLLAR) ' \" space")
    steps = mypc_installer.build_install_steps("macos", repo, gym)
    scripts = {step.name: shlex.split(step.command)[2] for step in steps}

    tools_error = f"DonkeyDrift 仓库不存在或不是 Git 仓库: {repo}"
    assert f"echo {shlex.quote(tools_error)} >&2" in scripts["prepare-tools"]

    venv_python = tmp_path / repo.removeprefix(str(tmp_path) + os.sep) / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\nexit 0\n")
    venv_python.chmod(0o755)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    for tool in ("uv", "git"):
        path = fake_bin / tool
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)

    result = subprocess.run(
        [_zsh_or_skip(), "-c", scripts["print-summary"]],
        cwd=tmp_path,
        env=dict(os.environ, HOME=str(tmp_path), PATH=f"{fake_bin}:{os.environ['PATH']}"),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "DD_DOLLAR").exists()
    assert not (tmp_path / "DD_BACKTICK").exists()
    assert not (tmp_path / "GYM_DOLLAR").exists()


@pytest.mark.parametrize("step_name,failing_tool", [
    ("print-summary", "uv"),
    ("print-summary", "git"),
    ("prepare-tools", "git"),
    ("prepare-gym", "git"),
])
def test_macos_version_and_commit_failures_propagate(tmp_path, step_name, failing_tool):
    repo = str(tmp_path / "DonkeyDrift")
    gym = str(tmp_path / "GymDonkeyCar")
    for repository in (repo, gym):
        (Path(repository) / ".git").mkdir(parents=True)
    venv_python = Path(repo) / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\nexit 0\n")
    venv_python.chmod(0o755)

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    for tool in ("uv", "git"):
        path = fake_bin / tool
        if tool == failing_tool == "uv":
            content = "#!/bin/sh\n[ \"${1:-}\" != \"--version\" ] || exit 1\nexit 0\n"
        elif tool == failing_tool == "git":
            content = "#!/bin/sh\ncase \" $* \" in *\" rev-parse \"*) exit 1;; esac\nexit 0\n"
        else:
            content = "#!/bin/sh\nexit 0\n"
        path.write_text(content)
        path.chmod(0o755)

    steps = mypc_installer.build_install_steps("macos", repo, gym)
    step = next(step for step in steps if step.name == step_name)
    result = subprocess.run(
        [_zsh_or_skip(), "-c", shlex.split(step.command)[2]],
        cwd=tmp_path,
        env=dict(os.environ, HOME=str(tmp_path), PATH=f"{fake_bin}:{os.environ['PATH']}"),
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, result.stdout + result.stderr


def test_windows_summary_checks_every_native_exit_status():
    steps = mypc_installer.build_install_steps("windows", WIN_REPO, WIN_GYM)
    summary = _decode_powershell(next(step for step in steps if step.name == "print-summary").command)

    assert summary.count("if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }") >= 4


def test_exec_command_receives_remaining_total_timeout():
    ssh = FakeSsh(_platform_handler("macos"))

    code, _ = _install(ssh, timeout=30)

    assert code == 0
    assert len(ssh.command_timeouts) == len(ssh.commands)
    assert all(value is not None and 0 < value <= 30 for value in ssh.command_timeouts)
    assert all(later <= earlier for earlier, later in zip(ssh.command_timeouts, ssh.command_timeouts[1:]))


def test_python_download_mirror_is_not_in_initial_plan():
    _, commands = _step_commands("macos")

    assert all("UV_PYTHON_INSTALL_MIRROR" not in command for command in commands)


def test_unsupported_plan_platform_fails_clearly():
    with pytest.raises(ValueError, match="支持"):
        mypc_installer.build_install_steps("linux", MAC_REPO, MAC_GYM)


@pytest.mark.parametrize("platform,repo,gym", [
    ("macos", "projects/DonkeyDrift", "projects/GymDonkeyCar"),
    ("windows", r"projects\DonkeyDrift", r"projects\GymDonkeyCar"),
])
def test_relative_repository_paths_fail_before_building_remote_commands(platform, repo, gym):
    with pytest.raises(ValueError, match="绝对路径"):
        mypc_installer.build_install_steps(platform, repo, gym)


def test_macos_default_tilde_paths_expand_into_commands_and_hook_before_execution():
    def remote_home(command, index):
        if "DonkeyDriftHome=" in command:
            return "DonkeyDriftHome=/Users/test Home\n", 0
        return "ok\n", 0

    ssh = FakeSsh(_platform_handler("macos", remote_home))
    code, _ = _install(
        ssh,
        repo_path="~/projects/DonkeyDrift",
        gym_path="~/projects/GymDonkeyCar",
    )

    assert code == 0
    scripts = [
        shlex.split(command)[2]
        for command in ssh.commands
        if command.startswith("zsh -lc ")
    ]
    joined = "\n".join(scripts)
    assert "/Users/test Home/projects/DonkeyDrift/.git" in joined
    assert "/Users/test Home/projects/GymDonkeyCar/.git" in joined
    assert "'~/projects/DonkeyDrift'" not in joined

    hook_script = next(script for script in scripts if ".zshrc" in script)
    compressed = base64.b64decode(re.search(
        r"DD_HOOK_B64=([A-Za-z0-9+/=]+)", hook_script
    ).group(1))
    hook = gzip.decompress(compressed).decode()
    assert "/Users/test Home/projects/DonkeyDrift" in hook
    assert "/Users/test Home/projects/GymDonkeyCar" in hook
    assert "~/projects" not in hook


def test_windows_tilde_and_mixed_separators_normalize_in_commands_and_hook():
    def remote_home(command, index):
        decoded = (_decode_powershell(command)
                   if command.startswith("powershell ") else command)
        if "DonkeyDriftHome=" in decoded:
            return "DonkeyDriftHome=C:\\Users\\Test\n", 0
        return "ok\n", 0

    ssh = FakeSsh(_platform_handler("windows", remote_home))
    code, _ = _install(
        ssh,
        repo_path="~/My Projects\\DonkeyDrift",
        gym_path="~\\My Projects/GymDonkeyCar",
    )

    assert code == 0
    scripts = [
        _decode_powershell(command)
        for command in ssh.commands[2:]
        if command.startswith("powershell ")
    ]
    joined = "\n".join(scripts)
    assert r"C:\Users\Test\My Projects\DonkeyDrift\.git" in joined
    assert r"C:\Users\Test\My Projects\GymDonkeyCar\.git" in joined

    hook_script = next(script for script in scripts if "DD_HOOK_B64" in script)
    encoded = re.search(r"DD_HOOK_B64='([A-Za-z0-9+/=]+)'", hook_script).group(1)
    hook = gzip.decompress(base64.b64decode(encoded)).decode()
    assert r"C:\Users\Test\My Projects\DonkeyDrift" in hook
    assert r"C:\Users\Test\My Projects\GymDonkeyCar" in hook
    assert "~/My Projects" not in hook
    assert "~\\My Projects" not in hook
    assert "My Projects/DonkeyDrift" not in hook
    assert "My Projects/GymDonkeyCar" not in hook


# ----------------------------------------------------------------------
# Installer executor behaviour
# ----------------------------------------------------------------------
def test_macos_install_discovers_platform_executes_all_steps_and_closes_ssh():
    ssh = FakeSsh(_platform_handler("macos"))

    code, logs = _install(ssh)

    assert code == 0
    assert ssh.closed is True
    assert len(ssh.commands) > 6
    assert ssh.commands[0] == "uname -s && uname -m"
    assert all(command.startswith("zsh -lc ") for command in ssh.commands[1:])
    assert any(event.get("level") == "success" and "环境配置完成" in event["line"] for event in logs)


def test_windows_cmd_discovers_platform_through_encoded_powershell():
    ssh = FakeSsh(_platform_handler("windows"))

    code, _ = _install(ssh, repo_path=WIN_REPO, gym_path=WIN_GYM)

    assert code == 0
    assert ssh.commands[1].startswith("powershell -NoProfile -NonInteractive -EncodedCommand ")
    assert all(command.startswith("powershell -NoProfile -NonInteractive -EncodedCommand ")
               for command in ssh.commands[2:])


def test_missing_python_path_is_not_required():
    ssh = FakeSsh(_platform_handler("macos"))

    code, _ = _install(ssh, python_path="")

    assert code == 0


def test_missing_repository_paths_fail_before_connecting():
    with patch.object(mypc_installer, "_open_ssh") as open_ssh:
        with pytest.raises(ValueError, match="仓库"):
            mypc_installer.install_mypc_environment(
                host="h", user="u", password="p", repo_path="", gym_path=MAC_GYM
            )
    open_ssh.assert_not_called()


@pytest.mark.parametrize("platform, message", [
    ("intel", "Apple Silicon"),
    ("linux", "不支持"),
])
def test_unsupported_remote_platform_fails_before_install(platform, message):
    ssh = FakeSsh(_platform_handler(platform))

    code, logs = _install(ssh)

    assert code != 0
    assert len(ssh.commands) == 1
    assert any(message in event["line"] for event in logs)
    assert not any(event.get("level") == "success" for event in logs)


def test_step_failure_stops_remaining_steps_and_returns_exact_exit_code():
    def fail_install(command, index):
        if "uv pip install" in command and "uv pip show" not in command:
            return b"resolver failed\n", 42
        return b"ok\n", 0

    ssh = FakeSsh(_platform_handler("macos", fail_install))

    code, logs = _install(ssh)
    executed = "\n".join(ssh.commands)

    assert code == 42
    assert "uv pip check" not in executed
    assert "zsh -ic" not in executed
    assert any("42" in event["line"] and "失败" in event["line"] for event in logs)
    assert not any(event.get("level") == "success" for event in logs)


def test_python_download_timeout_retries_venv_once_with_approved_mirror():
    attempts = []

    def retry_venv(command, index):
        if "uv venv --python 3.11" in command:
            attempts.append(command)
            if len(attempts) == 1:
                return b"Python download failed: operation timed out\n", 1
        return b"ok\n", 0

    ssh = FakeSsh(_platform_handler("macos", retry_venv))

    code, logs = _install(ssh)

    assert code == 0
    assert len(attempts) == 2
    assert "UV_PYTHON_INSTALL_MIRROR" not in attempts[0]
    assert "https://mirror.nju.edu.cn/github-release/astral-sh/python-build-standalone" in attempts[1]
    assert any("重试" in event["line"] for event in logs)


def test_non_timeout_venv_failure_does_not_retry_with_mirror():
    attempts = []

    def fail_venv(command, index):
        if "uv venv --python 3.11" in command:
            attempts.append(command)
            return b"invalid Python installation\n", 1
        return b"ok\n", 0

    ssh = FakeSsh(_platform_handler("macos", fail_venv))

    code, _ = _install(ssh)

    assert code == 1
    assert len(attempts) == 1
    assert "UV_PYTHON_INSTALL_MIRROR" not in attempts[0]


def test_stop_closes_active_channel_and_never_reports_success():
    stop_event = threading.Event()

    class StopChannel(FakeChannel):
        def exit_status_ready(self):
            stop_event.set()
            return False

    def handler(command, index):
        if index == 1:
            return b"Darwin\narm64\n", 0
        return StopChannel()

    ssh = FakeSsh(handler)

    code, logs = _install(ssh, stop_event=stop_event)

    assert code == -1
    assert ssh.channels[-1].closed is True
    assert not any(event.get("level") == "success" for event in logs)


def test_timeout_closes_active_channel_and_raises():
    class BusyChannel(FakeChannel):
        def exit_status_ready(self):
            return False

    def handler(command, index):
        if index == 1:
            return b"Darwin\narm64\n", 0
        return BusyChannel()

    ssh = FakeSsh(handler)

    with pytest.raises(TimeoutError):
        _install(ssh, timeout=0.2)
    assert ssh.channels[-1].closed is True


def test_pre_set_stop_does_not_start_discovery_or_report_success():
    stop_event = threading.Event()
    stop_event.set()
    ssh = FakeSsh(_platform_handler("macos"))

    code, logs = _install(ssh, stop_event=stop_event)

    assert code == -1
    assert ssh.commands == []
    assert not any(event.get("level") == "success" for event in logs)


def test_expired_deadline_does_not_start_discovery():
    ssh = FakeSsh(_platform_handler("macos"))

    with pytest.raises(TimeoutError):
        _install(ssh, timeout=-1)
    assert ssh.commands == []


def _install_in_daemon(ssh, **kwargs):
    result = {}

    def run():
        try:
            result["code"], result["logs"] = _install(ssh, **kwargs)
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, result


def test_blocking_exec_command_stop_closes_connection_and_returns():
    ssh = BlockingStartSsh()
    stop_event = threading.Event()
    thread, result = _install_in_daemon(ssh, stop_event=stop_event, timeout=30)
    assert ssh.exec_started.wait(1)

    stop_event.set()
    thread.join(0.5)
    blocked = thread.is_alive()
    closed_on_return = ssh.closed
    if thread.is_alive():
        ssh.close()
    thread.join(1)

    assert not thread.is_alive()
    assert not blocked, "stop did not interrupt exec_command startup"
    assert closed_on_return
    assert result["code"] == -1
    assert ssh.commands == ["uname -s && uname -m"]
    assert not any(event.get("level") == "success" for event in result["logs"])


def test_blocking_exec_command_deadline_closes_connection_and_raises():
    ssh = BlockingStartSsh()
    thread, result = _install_in_daemon(ssh, timeout=0.1)
    assert ssh.exec_started.wait(1)

    thread.join(0.5)
    blocked = thread.is_alive()
    closed_on_return = ssh.closed
    if thread.is_alive():
        ssh.close()
    thread.join(1)

    assert not thread.is_alive()
    assert not blocked, "deadline did not interrupt exec_command startup"
    assert closed_on_return
    assert isinstance(result.get("error"), TimeoutError)
    assert ssh.commands == ["uname -s && uname -m"]


def test_startup_result_racing_stop_is_cancelled():
    stop_event = threading.Event()

    class RacingQueue:
        def put_nowait(self, item):
            pass

        def get(self, timeout):
            stop_event.set()
            return True, (None, FakeStdout(FakeChannel(b"", 0)), None)

    class FakeWorker:
        def start(self):
            pass

        def join(self, timeout):
            pass

    ssh = FakeSsh()
    with patch.object(mypc_installer.queue, "Queue", return_value=RacingQueue()), \
         patch.object(mypc_installer.threading, "Thread", return_value=FakeWorker()):
        result = mypc_installer._exec_command_cancellable(
            ssh, "command", stop_event, mypc_installer.time.time() + 30
        )

    assert result is None
    assert ssh.closed is True


def test_output_is_streamed_cleaned_and_password_is_redacted():
    def output(command, index):
        if index == 2:
            return b"\x1b[32mDownloading...\rDownloading 50%\npassword=super-secret\n", 0
        return b"ok\n", 0

    ssh = FakeSsh(_platform_handler("macos", output))

    code, logs = _install(ssh, password="super-secret")
    lines = [event["line"] for event in logs]

    assert code == 0
    assert "Downloading 50%" in lines
    assert all("\x1b" not in line for line in lines)
    assert "super-secret" not in json.dumps(logs, ensure_ascii=False)
    assert any("[REDACTED]" in line for line in lines)


def test_install_ssh_failure_propagates():
    with patch.object(mypc_installer, "_open_ssh", side_effect=ConnectionError("connection refused")), \
         pytest.raises(ConnectionError):
        mypc_installer.install_mypc_environment(
            host="h", user="u", password="p", repo_path=MAC_REPO, gym_path=MAC_GYM
        )


# ----------------------------------------------------------------------
# Job engine and router contracts
# ----------------------------------------------------------------------
def _run_engine(install_result=0, install_exc=None, stop=False):
    from trainer_engine import TrainingJob, TrainingJobManager

    captured = {}

    def fake_install(**kwargs):
        captured.update(kwargs)
        q = kwargs["log_queue"]
        q.put({"type": "log", "line": "uv environment ready", "level": "info"})
        if stop:
            kwargs["stop_event"].set()
        if install_exc:
            raise install_exc
        return install_result

    manager = TrainingJobManager()
    job = TrainingJob(id="test1234", mode="mypc_install")

    async def run():
        with patch.object(mypc_installer, "install_mypc_environment", side_effect=fake_install):
            await manager.run_mypc_install(
                job, host="h", user="u", password="p",
                repo_path=MAC_REPO, gym_path=MAC_GYM,
            )

    asyncio.run(run())
    return job, captured


def test_run_mypc_install_success_completes_job_and_forwards_paths():
    job, captured = _run_engine()

    assert job.status == "completed"
    assert "uv environment ready" in job.logs
    assert captured["repo_path"] == MAC_REPO
    assert captured["gym_path"] == MAC_GYM
    assert captured["python_path"] == ""


def test_run_mypc_install_step_failure_fails_job():
    job, _ = _run_engine(install_result=1)

    assert job.status == "failed"
    assert "退出码" in (job.error_message or "")


def test_run_mypc_install_exception_fails_job():
    job, _ = _run_engine(install_exc=ConnectionError("connection refused"))

    assert job.status == "failed"
    assert "connection refused" in (job.error_message or "")


def test_run_mypc_install_timeout_fails_job():
    job, _ = _run_engine(install_exc=TimeoutError("安装超时"))

    assert job.status == "failed"
    assert "安装超时" in (job.error_message or "")


def test_run_mypc_install_stop_is_not_completed():
    job, _ = _run_engine(install_result=-1, stop=True)

    assert job.status == "stopped"


def _build_client():
    from routers import trainer as trainer_router

    app = FastAPI()
    app.include_router(trainer_router.router, prefix="/api/trainer")
    return TestClient(app)


def test_install_route_requires_repository_paths_not_python():
    client = _build_client()
    resp = client.post("/api/trainer/mypc/install", json={
        "host": "192.168.1.10", "user": "u", "password": "p",
        "repo_path": " ", "gym_path": MAC_GYM,
    })

    assert resp.status_code == 400
    assert "仓库" in resp.json()["detail"]


def test_install_route_creates_job_and_forwards_new_and_legacy_args():
    client = _build_client()
    captured = {}

    from trainer_engine import TrainingJob

    def fake_create_job(mode):
        captured["mode"] = mode
        return TrainingJob(id="abc12345", mode=mode)

    async def fake_run(job, host, user, password, repo_path, gym_path,
                       python_path="", port=22, key_path=""):
        captured.update(job=job, host=host, user=user, password=password,
                        repo_path=repo_path, gym_path=gym_path,
                        python_path=python_path, port=port, key_path=key_path)

    with patch("trainer_engine.job_manager.create_job", side_effect=fake_create_job), \
         patch("trainer_engine.job_manager.run_mypc_install", side_effect=fake_run):
        resp = client.post("/api/trainer/mypc/install", json={
            "host": "192.168.1.10", "user": "u", "password": "p",
            "repo_path": MAC_REPO, "gym_path": MAC_GYM,
            "python_path": "/legacy/python", "port": 22,
        })

    assert resp.status_code == 200
    assert resp.json()["job_id"] == "abc12345"
    assert captured["mode"] == "mypc_install"
    assert captured["repo_path"] == MAC_REPO
    assert captured["gym_path"] == MAC_GYM
    assert captured["python_path"] == "/legacy/python"


def test_install_route_accepts_request_without_python_path():
    client = _build_client()

    from trainer_engine import TrainingJob

    async def fake_run(*args, **kwargs):
        return None

    with patch("trainer_engine.job_manager.create_job", return_value=TrainingJob(id="abc12345", mode="mypc_install")), \
         patch("trainer_engine.job_manager.run_mypc_install", side_effect=fake_run):
        resp = client.post("/api/trainer/mypc/install", json={
            "host": "192.168.1.10", "user": "u", "password": "p",
            "repo_path": MAC_REPO, "gym_path": MAC_GYM,
        })

    assert resp.status_code == 200


def _run_install_api_flow(monkeypatch, handler):
    from trainer_engine import job_manager

    monkeypatch.setattr(job_manager, "jobs", {})
    release_ssh = threading.Event()

    def gated_handler(command, index):
        if index == 1 and not release_ssh.wait(60):
            return b"test SSH gate timed out\n", 1
        return handler(command, index)

    ssh = FakeSsh(gated_handler)
    with patch.object(mypc_installer, "_open_ssh", return_value=ssh), \
         _build_client() as client:
        created = client.post("/api/trainer/mypc/install", json={
            "host": "192.168.1.10", "user": "u", "password": "p",
            "repo_path": MAC_REPO, "gym_path": MAC_GYM, "python_path": "",
        })
        assert created.status_code == 200
        job_id = created.json()["job_id"]
        assert job_id

        # 等 job 真正进入 running 后再放行 fake SSH 与订阅 SSE，
        # 避免把正确性建立在「SSE 首行先于安装执行到达」的流式时序上。
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            current = client.get(f"/api/trainer/train/{job_id}/status").json()["status"]
            if current != "pending":
                break
            time.sleep(0.05)
        else:
            raise AssertionError("job never left pending state")
        release_ssh.set()

        with client.stream("GET", f"/api/trainer/train/{job_id}/logs") as streamed:
            assert streamed.status_code == 200
            assert streamed.headers["content-type"].startswith("text/event-stream")
            raw_lines = list(streamed.iter_lines())
        status = client.get(f"/api/trainer/train/{job_id}/status")

    events = [
        json.loads(line.removeprefix("data: "))
        for line in raw_lines if line.startswith("data: ")
    ]
    return created.json(), status, events, ssh, job_manager.get_job(job_id)


def test_install_api_job_and_sse_complete_full_macos_flow(monkeypatch):
    platform = _platform_handler("macos")

    def successful_install(command, index):
        if "=== DonkeyDrift installation summary ===" in command:
            return (
                "=== DonkeyDrift installation summary ===\n"
                "uv: 0.5.0\n"
                f"DD path: {MAC_REPO}\n"
                "DD commit: fake-dd-commit\n"
                f"Gym path: {MAC_GYM}\n"
                "Gym commit: fake-gym-commit\n"
                f"Venv: {MAC_REPO}/.venv\n"
                "Python: 3.11.9\n"
                "TensorFlow: 2.16.2\n"
                "numpy: 1.26.4\n"
                "GPU: fake-metal\n"
                "Hook: $HOME/.zshrc (donkeydrift-auto-activate)\n"
                "Acceptance: installation and automatic activation passed\n"
            ), 0
        return platform(command, index)

    created, status, events, ssh, job = _run_install_api_flow(
        monkeypatch, successful_install
    )

    assert created["status"] in ("pending", "running")
    assert status.status_code == 200
    assert status.json()["job_id"] == created["job_id"]
    assert status.json()["mode"] == "mypc_install"
    assert status.json()["status"] == "completed"
    assert status.json()["error"] is None
    assert status.json()["finished_at"] is not None
    assert events[-1]["type"] == "status"
    assert events[-1]["status"] == "completed"
    assert not any(event["type"] == "error" for event in events)

    lines = list(job.logs)
    stage_lines = [line for line in lines if re.fullmatch(r"\[\d+/\d+\] .+", line)]
    assert stage_lines == [
        "[1/9] prepare-tools",
        "[2/9] prepare-gym",
        "[3/9] prepare-venv",
        "[4/9] install-dependencies",
        "[5/9] remove-upstream-donkeycar",
        "[6/9] install-shell-hook",
        "[7/9] verify-installation",
        "[8/9] verify-shell-hook",
        "[9/9] print-summary",
    ]
    for expected in (
        "=== DonkeyDrift installation summary ===",
        "uv: 0.5.0",
        "DD commit: fake-dd-commit",
        "Gym commit: fake-gym-commit",
        "Python: 3.11.9",
        "TensorFlow: 2.16.2",
        "numpy: 1.26.4",
        "GPU: fake-metal",
        "Hook: $HOME/.zshrc (donkeydrift-auto-activate)",
        "Acceptance: installation and automatic activation passed",
        "DonkeyDrift 环境配置完成，安装与自动激活验收通过。",
    ):
        assert expected in lines
    assert len(ssh.commands) == 10
    assert ssh.closed is True
    assert job.logs[-len(lines):] == lines
    assert job.subscribers == []
    assert not job.trainer_thread.is_alive()


def test_install_api_job_and_sse_stop_at_failed_stage(monkeypatch):
    def fail_dependencies(command, index):
        if "uv pip install" in command and "uv pip show" not in command:
            return b"resolver failed\n", 42
        return _platform_handler("macos")(command, index)

    created, status, events, ssh, job = _run_install_api_flow(
        monkeypatch, fail_dependencies
    )

    assert status.status_code == 200
    assert status.json()["job_id"] == created["job_id"]
    assert status.json()["status"] == "failed"
    assert status.json()["error"] == "环境配置失败，退出码: 42"
    assert status.json()["finished_at"] is not None
    assert events[-1]["type"] == "status"
    assert events[-1]["status"] == "failed"
    error_events = [event for event in events if event["type"] == "error"]
    assert not error_events or error_events[-1]["message"] == "环境配置失败，退出码: 42"

    lines = list(job.logs)
    stage_lines = [line for line in lines if re.fullmatch(r"\[\d+/\d+\] .+", line)]
    assert stage_lines == [
        "[1/9] prepare-tools",
        "[2/9] prepare-gym",
        "[3/9] prepare-venv",
        "[4/9] install-dependencies",
    ]
    assert "resolver failed" in lines
    assert "步骤 install-dependencies 失败，退出码: 42" in lines
    assert not any("环境配置完成" in line for line in lines)
    assert len(ssh.commands) == 5
    executed = "\n".join(ssh.commands)
    assert "uv pip uninstall" not in executed
    assert "uv pip check" not in executed
    assert "zsh -ic" not in executed
    assert "=== DonkeyDrift installation summary ===" not in executed
    assert ssh.closed is True
    assert job.logs[-len(lines):] == lines
    assert job.subscribers == []
    assert not job.trainer_thread.is_alive()
