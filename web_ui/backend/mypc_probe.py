"""
My-PC environment probe.

Diagnoses whether the Lan Host (the remote development machine reached via an
SSH callback from this backend) is ready for "Lan Host" (mypc) training.

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
def _open_ssh(host: str, user: str, password: str, port: int = 22, timeout: int = 10, key_path: str = ""):
    """Open a Paramiko SSH client with host-key checking disabled (same as
    the training pipeline) and no interactive auth fallbacks."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    connect_kwargs = {}
    if key_path:
        # 显式指定私钥（与 Car Connector 的 key_path 用法对齐）
        connect_kwargs["key_filename"] = os.path.expanduser(key_path)
    elif not password:
        # 未提供密码时回退到默认密钥 / ssh-agent（~/.ssh/id_rsa 等）
        connect_kwargs["look_for_keys"] = True
        connect_kwargs["allow_agent"] = True
    else:
        connect_kwargs["allow_agent"] = False
        connect_kwargs["look_for_keys"] = False
    client.connect(
        host,
        port=port,
        username=user,
        password=password,
        timeout=timeout,
        **connect_kwargs,
    )
    return client


def _run_remote(ssh, command: str, timeout: int = 20):
    """Run a command on the remote and return (exit_code, stdout, stderr).

    Never raises: a timeout or channel error (e.g. ``source ~/.zshrc`` taking
    longer than the timeout) returns ``(1, '', '')`` so a single slow/hung
    command can't abort the whole multi-layer Python discovery — the next
    layer (glob, ``command -v donkey``) still gets to run.
    """
    try:
        stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="ignore").strip()
        err = stderr.read().decode("utf-8", errors="ignore").strip()
        code = stdout.channel.recv_exit_status()
        return code, out, err
    except Exception:
        return 1, "", ""


# ----------------------------------------------------------------------
# Python candidate paths (best effort across Linux / macOS / Windows)
# ----------------------------------------------------------------------
def _default_python_candidates() -> List[str]:
    # "$HOME" is expanded by the remote shell, not on this backend host.
    return [
        "$HOME/miniconda3/envs/donkey/bin/python",
        "$HOME/anaconda3/envs/donkey/bin/python",
        "$HOME/miniforge3/envs/donkey/bin/python",
        "$HOME/mambaforge3/envs/donkey/bin/python",
        "$HOME/miniconda3/bin/python",
        "$HOME/anaconda3/bin/python",
        "$HOME/miniforge3/bin/python",
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "python3",
        "python",
        "/usr/bin/python3",
        "py",
    ]


def _discover_env_pythons(ssh) -> List[str]:
    """Ask the remote host to enumerate conda-env interpreters.

    Four read-only discovery layers; a layer that fails or prints nothing
    is skipped silently, and on a Windows cmd shell all of them do:

    1. Ask conda itself (``conda env list`` after sourcing the user's rc),
       so envs are found no matter where conda is installed or how the env
       is named. Tried under zsh (macOS default shell), a bash login shell,
       and a zsh login shell (covers ``conda init`` writing to ~/.zprofile
       instead of ~/.zshrc); whichever lists env paths first wins.
    1b. If no rc file exposes conda, glob for the conda binary itself —
        under ``$HOME`` and system-wide roots (``/opt``, ``/usr/local``),
        wrapped in ``sh`` so zsh's nomatch behaviour cannot abort the
        command — and ask each located binary for its env list.
    2. Glob the well-known conda roots, both under ``$HOME`` and
       system-wide (``/opt``, ``/usr/local``).
    3. Reverse-lookup the ``donkey`` console script (``command -v donkey``)
       and use the interpreters sitting in the same bin directory.
    """
    found: List[str] = []

    def _collect_env_list(out: str) -> int:
        """Append ``<env_dir>/bin/python3`` and ``<env_dir>/bin/python`` for
        every ``conda env list`` line whose last field is an absolute path;
        returns how many interpreters were appended."""
        added = 0
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Lines look like "donkey  *  /Users/u/miniconda3/envs/donkey";
            # sourcing someone's rc may also print junk, so only accept
            # lines whose last whitespace-separated field is an absolute
            # path.
            env_dir = line.split()[-1]
            if not env_dir.startswith("/"):
                continue
            found.append(f"{env_dir}/bin/python3")
            found.append(f"{env_dir}/bin/python")
            added += 2
        return added

    # 1. conda knows where its envs live, regardless of install root or name.
    # 短超时：sourcing ~/.zshrc 在某些 Mac 上极慢（>15s），三层最坏 18s；
    # 找不到就快速落到下面的 glob 层（能直接命中 /opt、~ 等标准根）。
    for cmd in (
        "zsh -c 'source ~/.zshrc >/dev/null 2>&1; conda env list 2>/dev/null'",
        "bash -lc 'conda env list 2>/dev/null'",
        "zsh -lc 'conda env list 2>/dev/null'",
    ):
        code, out, _ = _run_remote(ssh, cmd, timeout=6)
        if code != 0 or not out:
            continue
        if _collect_env_list(out):
            break

    # 1b. No rc file put conda on PATH: locate the conda binary itself
    # (user-level and system-wide install roots) and ask it directly.
    if not found:
        locate_cmd = (
            "sh -c 'ls -d \"$HOME\"/*/condabin/conda \"$HOME\"/*/*/condabin/conda "
            "/opt/*/condabin/conda /usr/local/*/condabin/conda 2>/dev/null'"
        )
        _, out, _ = _run_remote(ssh, locate_cmd, timeout=15)
        for conda_bin in (line.strip() for line in out.splitlines() if line.strip()):
            code, out, _ = _run_remote(
                ssh, f"{conda_bin} env list 2>/dev/null", timeout=15)
            if code != 0 or not out:
                continue
            if _collect_env_list(out):
                break

    # 2. Glob the well-known conda roots, both under $HOME and system-wide.
    # The sh wrapper matters: an unmatched glob makes zsh abort the whole
    # command (nomatch).
    glob_cmd = (
        "sh -c 'for b in \"$HOME/miniconda3\" \"$HOME/opt/miniconda3\" "
        "\"$HOME/anaconda3\" \"$HOME/opt/anaconda3\" \"$HOME/miniforge3\" "
        "\"$HOME/mambaforge3\" \"/opt/miniconda3\" \"/opt/anaconda3\" "
        "\"/opt/miniforge3\" \"/opt/mambaforge3\" \"/opt/conda\" "
        "\"/usr/local/miniconda3\" \"/usr/local/anaconda3\" "
        "\"/usr/local/miniforge3\" \"/usr/local/mambaforge3\"; do "
        "ls -d \"$b\"/envs/*/bin/python3 \"$b\"/envs/*/bin/python "
        "2>/dev/null; done'"
    )
    _, out, _ = _run_remote(ssh, glob_cmd, timeout=15)
    # ls exits non-zero when any single operand is missing, so its exit
    # code is meaningless here; whatever made it to stdout is usable.
    if out:
        found.extend(line.strip() for line in out.splitlines() if line.strip())

    # 3. If a donkey console script is on PATH, its env's interpreters sit
    # in the same bin directory.
    # 短超时：zsh -lc / source ~/.zshrc 在某些 Mac 上极慢（>15s），两层最坏 12s；
    # glob 层已覆盖标准 conda 根，这里只是补充 PATH 上的 donkey。
    for cmd in (
        "zsh -c 'source ~/.zshrc >/dev/null 2>&1; command -v donkey'",
        "bash -lc 'command -v donkey'",
    ):
        code, out, _ = _run_remote(ssh, cmd, timeout=6)
        if code != 0 or not out:
            continue
        donkey_path = ""
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("/") and line.endswith("/donkey"):
                donkey_path = line
        if donkey_path:
            bin_dir = donkey_path.rsplit("/", 1)[0]
            found.append(f"{bin_dir}/python3")
            found.append(f"{bin_dir}/python")
            break

    # De-duplicate while preserving order
    seen = set()
    ordered = []
    for path in found:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def _python_exec_probe(python_cmd: str) -> str:
    """Command that prints sys.executable when the interpreter is usable."""
    return (
        f"{python_cmd} -c \"import sys; print(sys.executable)\""
    )


def _donkeycar_probe(python_cmd: str) -> str:
    """Command that succeeds only when donkeycar is importable (find_spec
    only — no real import, so it is fast and side-effect free)."""
    return (
        f"{python_cmd} -c \"import importlib.util,sys; "
        "sys.exit(0 if importlib.util.find_spec('donkeycar') else 1)\""
    )


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
    key_path: str = "",
) -> ProbeResult:
    """Connect to the user's computer and diagnose its training readiness."""
    result = ProbeResult(ok=False)

    # 1. SSH connectivity
    try:
        ssh = _open_ssh(host, user, password, port=port, timeout=ssh_timeout, key_path=key_path)
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

        # 3. Python interpreter discovery (also verifies donkeycar)
        donkeycar_verified = _detect_python(ssh, result, python_path)

        # 4. donkeycar environment
        if result.python_path:
            _check_donkeycar(ssh, result, donkeycar_verified)
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
            display = "macOS"
            _, version, _ = _run_remote(ssh, "sw_vers -productVersion")
            version = version.strip()
            if version:
                display = f"macOS {version}"
        elif "linux" in system:
            result.platform = "linux"
            display = "Linux"
        else:
            result.platform = system or "unknown"
            display = result.platform
        result.shell = "posix"
        result.checks.append(ProbeCheck(
            name="platform",
            status="ok",
            message=f"检测到远程系统: {display}",
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


def _detect_python(ssh, result: ProbeResult, configured_python: str) -> bool:
    """Select a usable interpreter, preferring ones that ship donkeycar.

    Returns True when the selected interpreter's donkeycar package has
    already been verified here, so ``_check_donkeycar`` can skip re-probing.
    """
    candidates: List[str] = []
    if configured_python and configured_python.strip():
        candidates.append(configured_python.strip())
    candidates.extend(_discover_env_pythons(ssh))
    candidates.extend(_default_python_candidates())

    # De-duplicate while preserving order
    seen = set()
    ordered = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            ordered.append(c)

    usable: List[str] = []  # resolved sys.executable of each working candidate
    for cmd in ordered:
        code, out, _ = _run_remote(ssh, _python_exec_probe(cmd))
        executable = out.strip()
        if code != 0 or not executable:
            continue
        usable.append(executable)
        code, _, _ = _run_remote(ssh, _donkeycar_probe(cmd))
        if code == 0:
            result.python_path = executable
            result.checks.append(ProbeCheck(
                name="python",
                status="ok",
                message=f"找到可用 Python: {executable}",
            ))
            return True

    if usable:
        # No usable interpreter carries donkeycar; fall back to the first
        # usable one and let _check_donkeycar flag the missing package.
        result.python_path = usable[0]
        result.checks.append(ProbeCheck(
            name="python",
            status="ok",
            message=f"找到可用 Python: {usable[0]}",
        ))
        return False

    result.checks.append(ProbeCheck(
        name="python",
        status="fail",
        message="未找到可用的 Python 解释器。",
        hint=(
            "请先安装 Python 3（Windows 安装时勾选 Add Python to PATH；"
            "macOS 可用 Homebrew 安装），或在表单里手动填写正确的 python_path。"
        ),
    ))
    return False


def find_donkeycar_python(ssh, configured_python: str = "") -> str:
    """给定一个已打开的 SSH 连接，返回远程某个能 import donkeycar 的解释器的
    sys.executable；找不到返回 ''。

    候选顺序：先 configured_python（原样作为远程命令，~ 由远程 shell 展开），
    再 _discover_env_pythons(ssh)，再 _default_python_candidates()；去重保序。
    对每个候选：_python_exec_probe 可用（exit 0 且输出 sys.executable）后，
    再用 _donkeycar_probe 验证 donkeycar 可导入，通过即返回该 sys.executable。
    """
    candidates: List[str] = []
    if configured_python and configured_python.strip():
        candidates.append(configured_python.strip())
    candidates.extend(_discover_env_pythons(ssh))
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
        if code != 0 or not executable:
            continue
        code, _, _ = _run_remote(ssh, _donkeycar_probe(cmd))
        if code == 0:
            return executable
    return ""


def _check_donkeycar(ssh, result: ProbeResult, donkeycar_verified: bool = False):
    if donkeycar_verified:
        # _detect_python already probed this interpreter successfully.
        result.checks.append(ProbeCheck(
            name="donkeycar",
            status="ok",
            message="donkeycar 已安装。",
        ))
    else:
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
                hint=(
                    "未在常见 conda 环境（~/miniconda3/envs、/opt/miniconda3/envs 等"
                    "用户目录或系统级位置）的解释器中检测到 donkeycar；"
                    "如已安装在其他环境，请在表单中手动填写该环境的 python 路径。"
                ),
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
