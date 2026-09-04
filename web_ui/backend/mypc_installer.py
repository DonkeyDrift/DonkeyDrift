"""
My-PC training dependency installer.

Companion to ``mypc_probe``: once the probe has found a usable Python
interpreter on the user's own computer, this module SSHes in and runs
``<python> -m pip install --upgrade "donkeydrifter[pc]"`` (the [pc] extra
from setup.cfg, PyPI name of this project), streaming pip's output line by
line into a queue so the web UI can show live install logs through the same
job / SSE pattern used by the trainers (see ``web_online_trainer``).

Like the probe, credentials are only used in-memory for this install job.
"""
import re
import time
from typing import Optional

from mypc_probe import _open_ssh

# The [pc] training extra defined in setup.cfg [options.extras_require].
PACKAGE_SPEC = 'donkeydrifter[pc]'

# pip downloads can be slow; allow plenty of time before giving up.
INSTALL_TIMEOUT = 3600  # seconds

# Regex to strip ANSI escape codes (colour, cursor movement, etc.)
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _clean_line(raw: str) -> str:
    """Remove ANSI codes, keep only the last \\r segment (pip progress bars)."""
    cleaned = _ANSI_RE.sub('', raw)
    if '\r' in cleaned:
        cleaned = cleaned.split('\r')[-1]
    return cleaned.strip()


def build_install_command(python_path: str, package: str = PACKAGE_SPEC) -> str:
    """Build the remote pip install command for the detected interpreter.

    Double quotes work in both POSIX shells and Windows cmd, so they are used
    for the interpreter path (which may contain spaces) and the extras spec.
    """
    return f'"{python_path}" -m pip install --upgrade "{package}"'


def _emit(log_queue, message: str, level: str = "info"):
    if log_queue is not None:
        log_queue.put({
            "type": "log",
            "line": message,
            "level": level,
            "timestamp": time.time()
        })


def install_mypc_environment(
    host: str,
    user: str,
    password: str,
    python_path: str,
    port: int = 22,
    ssh_timeout: int = 10,
    log_queue: Optional[object] = None,
    stop_event=None,
    timeout: int = INSTALL_TIMEOUT,
    key_path: str = "",
) -> int:
    """Install training dependencies on the user's computer over SSH.

    Blocking (run it in a worker thread). Streams pip output into
    ``log_queue`` line by line and returns the pip exit code; raises on SSH
    failures and timeouts so the caller can surface a clean error.
    """
    if not python_path or not python_path.strip():
        raise ValueError("缺少 Python 解释器路径，请先运行环境检测。")

    _emit(log_queue, f"正在连接 {host}:{port} ...")
    ssh = _open_ssh(host, user, password, port=port, timeout=ssh_timeout, key_path=key_path)
    try:
        command = build_install_command(python_path.strip())
        _emit(log_queue, f"开始安装训练依赖: {command}")

        # get_pty merges stderr into stdout so pip warnings are streamed too.
        stdin, stdout, stderr = ssh.exec_command(command, get_pty=True)
        del stdin, stderr  # not used with a pty

        start_time = time.time()
        buffer = ""

        def _flush(buffer: str):
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                clean = _clean_line(line)
                if clean:
                    _emit(log_queue, clean)
            return buffer

        while not stdout.channel.exit_status_ready():
            if stop_event is not None and stop_event.is_set():
                _emit(log_queue, "安装已停止。", "warning")
                try:
                    stdout.channel.close()
                except Exception:
                    pass
                return -1
            if time.time() - start_time > timeout:
                raise TimeoutError(f"安装超时（> {timeout // 60} 分钟）")

            if stdout.channel.recv_ready():
                chunk = stdout.channel.recv(4096).decode("utf-8", errors="ignore")
                buffer = _flush(buffer + chunk)
            time.sleep(0.1)

        # Drain whatever is left after the channel closed.
        try:
            while stdout.channel.recv_ready():
                chunk = stdout.channel.recv(4096).decode("utf-8", errors="ignore")
                buffer = _flush(buffer + chunk)
        except Exception:
            pass
        remaining = _clean_line(buffer)
        if remaining:
            _emit(log_queue, remaining)

        code = stdout.channel.recv_exit_status()
        if code == 0:
            _emit(log_queue, "训练依赖安装完成。", "success")
        else:
            _emit(log_queue, f"pip 安装失败，退出码: {code}", "error")
        return code
    finally:
        try:
            ssh.close()
        except Exception:
            pass
