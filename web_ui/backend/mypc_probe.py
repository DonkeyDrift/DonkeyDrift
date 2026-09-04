"""
My-PC environment probe.

Diagnoses whether the user's own computer (the machine running the browser,
reached via an SSH callback from this backend) is ready for "Lan Host"
(mypc) training.

This is intentionally a lightweight, side-effect-free pre-flight check: it
connects over SSH, detects the remote OS, finds a usable Python interpreter,
and verifies the donkeycar training environment. It does NOT package data or
write any config file. Keeping it separate from
``donkeycar.management.train_online.OnlineTrainer`` means the UI can show
actionable setup guidance before a training job is started, instead of only
surfacing a failed job after the fact.
"""
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

import paramiko


# ----------------------------------------------------------------------
# Result model
# ----------------------------------------------------------------------
@dataclass
class ProbeCheck:
    name: str
    status: str  # 'ok' | 'warn' | 'fail' | 'info'
    message: str
    hint: str = ""


@dataclass
class ProbeResult:
    ok: bool
    platform: str = "unknown"  # 'linux' | 'macos' | 'windows' | 'unknown'
    shell: str = "posix"       # 'posix' | 'windows'
    checks: List[ProbeCheck] = field(default_factory=list)
    python_path: str = ""      # effective python path (auto-detected or configured)
    suggestions: List[str] = field(default_factory=list)


# ----------------------------------------------------------------------
# Low-level SSH helpers (kept small so tests can patch them easily)
# ----------------------------------------------------------------------
def _open_ssh(host: str, user: str, password: str, port: int = 22, timeout: int = 10):
    """Open a Paramiko SSH client with host-key checking disabled (same as
    the training pipeline) and no interactive auth fallbacks."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        port=port,
        username=user,
        password=password,
        timeout=timeout,
        allow_agent=False,
        look_for_keys=False,
    )
    return client


def _run_remote(ssh, command: str, timeout: int = 20):
    """Run a command on the remote and return (exit_code, stdout, stderr)."""
    stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="ignore").strip()
    err = stderr.read().decode("utf-8", errors="ignore").strip()
    code = stdout.channel.recv_exit_status()
    return code, out, err


# ----------------------------------------------------------------------
# Python candidate paths (best effort across Linux / macOS / Windows)
# ----------------------------------------------------------------------
def _default_python_candidates() -> List[str]:
    home = os.path.expanduser("~")
    return [
        "python3",
        "python",
        f"{home}/miniconda3/envs/donkey/bin/python",
        f"{home}/miniconda3/bin/python",
        f"{home}/anaconda3/bin/python",
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
        "/usr/bin/python",
        "py",
    ]


def _python_exec_probe(python_cmd: str) -> str:
    """Command that prints sys.executable when the interpreter is usable."""
    return (
        f"{python_cmd} -c \"import sys; print(sys.executable)\""
    )


def _donkeycar_probe(python_cmd: str) -> str:
    """Command that succeeds only when donkeycar is importable."""
    return f"{python_cmd} -c \"import donkeycar\""


def _donkey_cli_probe(python_cmd: str, resolved_python: str) -> str:
    """Check the ``donkey`` console script sitting next to the interpreter."""
    if "/" in resolved_python:
        donkey_bin = resolved_python.rsplit("/", 1)[0] + "/donkey"
    else:
        donkey_bin = "donkey"
    return f"{donkey_bin} --help"


# ----------------------------------------------------------------------
# Probe orchestration
# ----------------------------------------------------------------------
def probe_mypc_environment(
    host: str,
    user: str,
    password: str,
    remote_dir_base: str = "~/projects",
    python_path: str = "",
    port: int = 22,
    ssh_timeout: int = 10,
) -> ProbeResult:
    """Connect to the user's computer and diagnose its training readiness."""
    result = ProbeResult(ok=False)

    # 1. SSH connectivity
    try:
        ssh = _open_ssh(host, user, password, port=port, timeout=ssh_timeout)
    except Exception as exc:  # noqa: BLE001 - surface a clean hint, not a stack
        result.checks.append(ProbeCheck(
            name="ssh",
            status="fail",
            message=f"无法通过 SSH 连接到 {host}:{port}: {exc}",
            hint=(
                "请确认目标电脑已开启 SSH 服务且防火墙放行 22 端口。"
                "macOS：系统设置 > 通用 > 共享 > 远程登录；"
                "Linux：安装并启动 openssh-server；"
                "Windows：设置 > 应用 > 可选功能 > 安装 OpenSSH 服务器，"
                "或使用 WSL 并在其中开启 SSH。"
            ),
        ))
        result.suggestions.append(
            "SSH 连接失败，请先按上面的提示开启目标电脑的 SSH 服务。"
        )
        return result

    try:
        result.checks.append(ProbeCheck(
            name="ssh",
            status="ok",
            message=f"已通过 SSH 连接到 {host}:{port}",
        ))

        # 2. OS / platform detection
        _detect_platform(ssh, result)

        # 3. Python interpreter discovery
        _detect_python(ssh, result, python_path)

        # 4. donkeycar environment
        if result.python_path:
            _check_donkeycar(ssh, result)
    finally:
        try:
            ssh.close()
        except Exception:
            pass

    _summarize(result)
    return result


def _detect_platform(ssh, result: ProbeResult):
    code, out, _ = _run_remote(ssh, "uname -s")
    system = out.strip().lower()
    if code == 0 and system:
        if "darwin" in system:
            result.platform = "macos"
        elif "linux" in system:
            result.platform = "linux"
        else:
            result.platform = system or "unknown"
        result.shell = "posix"
        result.checks.append(ProbeCheck(
            name="platform",
            status="info",
            message=f"检测到远程系统: {result.platform}",
        ))
        return

    # uname failed -> likely a Windows native SSH shell (cmd.exe)
    result.platform = "windows"
    result.shell = "windows"
    result.checks.append(ProbeCheck(
        name="platform",
        status="warn",
        message="检测到 Windows 目标机（SSH 默认 shell 为 cmd）。",
        hint=(
            "推荐在 WSL 内安装 donkeycar 并通过 WSL 的 SSH 使用局域网主机训练，"
            "以兼容训练管线的 POSIX 命令（tar / cd / bash）。"
        ),
    ))
    # Best-effort WSL detection (available on Windows 10/11)
    code, out, _ = _run_remote(ssh, "wsl.exe -e uname -s")
    if code == 0 and "linux" in out.strip().lower():
        result.checks.append(ProbeCheck(
            name="wsl",
            status="ok",
            message="检测到可用的 WSL，可在其中训练。",
        ))
    else:
        result.checks.append(ProbeCheck(
            name="wsl",
            status="warn",
            message="未检测到 WSL（或 WSL 未安装）。",
            hint="Windows 原生 SSH 下训练管线暂不支持，请安装 WSL 并在其中安装 donkeycar。",
        ))


def _detect_python(ssh, result: ProbeResult, configured_python: str):
    candidates: List[str] = []
    if configured_python and configured_python.strip():
        candidates.append(configured_python.strip())
    candidates.extend(_default_python_candidates())

    # De-duplicate while preserving order
    seen = set()
    ordered = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            ordered.append(c)

    for cmd in ordered:
        code, out, _ = _run_remote(ssh, _python_exec_probe(cmd))
        executable = out.strip()
        if code == 0 and executable:
            result.python_path = executable
            result.checks.append(ProbeCheck(
                name="python",
                status="ok",
                message=f"找到可用 Python: {executable}",
            ))
            return

    result.checks.append(ProbeCheck(
        name="python",
        status="fail",
        message="未找到可用的 Python 解释器。",
        hint=(
            "请先安装 Python 3（Windows 安装时勾选 Add Python to PATH；"
            "macOS 可用 Homebrew 安装），或在表单里手动填写正确的 python_path。"
        ),
    ))


def _check_donkeycar(ssh, result: ProbeResult):
    code, _, err = _run_remote(ssh, _donkeycar_probe(result.python_path))
    if code == 0:
        result.checks.append(ProbeCheck(
            name="donkeycar",
            status="ok",
            message="donkeycar 已安装。",
        ))
    else:
        result.checks.append(ProbeCheck(
            name="donkeycar",
            status="fail",
            message="Python 可用，但未检测到 donkeycar 包。",
            hint="请在目标电脑运行: pip install donkeycar（或本仓库的安装方式）。",
        ))

    code, _, err = _run_remote(ssh, _donkey_cli_probe(result.python_path, result.python_path))
    if code == 0:
        result.checks.append(ProbeCheck(
            name="donkey_cli",
            status="ok",
            message="donkey 命令可用，可创建训练工作目录。",
        ))
    else:
        result.checks.append(ProbeCheck(
            name="donkey_cli",
            status="fail",
            message="未找到 donkey 命令，无法创建远程训练工作目录。",
            hint="请确认 donkeycar 已安装到 PATH（或与 Python 同目录的 bin 目录）。",
        ))


def _summarize(result: ProbeResult):
    failures = [c for c in result.checks if c.status == "fail"]
    if not failures:
        result.ok = True
        result.suggestions.append("环境就绪，可以开始局域网主机训练。")
        return

    result.ok = False
    for c in failures:
        if c.hint:
            result.suggestions.append(c.hint)
