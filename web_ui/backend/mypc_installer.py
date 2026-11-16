"""SSH-driven DonkeyDrift uv environment installer for My-PC training."""
import queue
import re
import threading
import time
from typing import Optional

from install_steps import (  # noqa: F401 — re-exports kept for existing callers/tests
    INSTALL_TIMEOUT,
    _HOOK_END,
    _HOOK_START,
    _build_install_steps,
    _clean_line,
    _is_python_download_timeout,
    _normalize_remote_path,
    _path_needs_home,
    _powershell_command,
    _profile_update_script,
    _ps_quote,
    _verification_script,
    build_install_steps,
)
from mypc_probe import _open_ssh


def _emit(log_queue, message: str, level: str = "info", redactions=()):
    for secret in redactions:
        if len(secret) >= 4:
            message = message.replace(secret, "[REDACTED]")
        elif secret:
            message = re.sub(
                rf"(?<!\w){re.escape(secret)}(?!\w)", "[REDACTED]", message
            )
    if log_queue is not None:
        log_queue.put({
            "type": "log",
            "line": message,
            "level": level,
            "timestamp": time.time(),
        })


def _exec_command_cancellable(ssh, command: str, stop_event, deadline: float):
    startup_result = queue.Queue(maxsize=1)

    def start_command():
        try:
            result = ssh.exec_command(
                command,
                get_pty=True,
                timeout=max(0.001, deadline - time.time()),
            )
            startup_result.put_nowait((True, result))
        except BaseException as exc:
            startup_result.put_nowait((False, exc))

    worker = threading.Thread(target=start_command, daemon=True)
    worker.start()

    def cancel_startup():
        try:
            ssh.close()
        except Exception:
            pass
        worker.join(timeout=1)

    while True:
        if stop_event is not None and stop_event.is_set():
            cancel_startup()
            return None
        remaining = deadline - time.time()
        if remaining <= 0:
            cancel_startup()
            raise TimeoutError("安装超时。")
        try:
            succeeded, payload = startup_result.get(
                timeout=max(0.001, min(0.05, remaining))
            )
        except queue.Empty:
            continue
        if stop_event is not None and stop_event.is_set():
            cancel_startup()
            return None
        if time.time() > deadline:
            cancel_startup()
            raise TimeoutError("安装超时。")
        if not succeeded:
            raise payload
        return payload


def _run_command(ssh, command: str, log_queue, stop_event, deadline: float,
                 redactions=()) -> tuple[int, str]:
    if stop_event is not None and stop_event.is_set():
        _emit(log_queue, "安装已停止。", "warning", redactions)
        return -1, ""
    if time.time() > deadline:
        raise TimeoutError("安装超时。")
    startup = _exec_command_cancellable(ssh, command, stop_event, deadline)
    if startup is None:
        _emit(log_queue, "安装已停止。", "warning", redactions)
        return -1, ""
    stdin, stdout, stderr = startup
    del stdin, stderr
    buffer = ""
    lines = []

    def flush(value: str):
        while "\n" in value:
            line, value = value.split("\n", 1)
            clean = _clean_line(line)
            if clean:
                lines.append(clean)
                _emit(log_queue, clean, redactions=redactions)
        return value

    while not stdout.channel.exit_status_ready():
        if stop_event is not None and stop_event.is_set():
            _emit(log_queue, "安装已停止。", "warning", redactions)
            try:
                stdout.channel.close()
            except Exception:
                pass
            return -1, "\n".join(lines)
        if time.time() > deadline:
            try:
                stdout.channel.close()
            except Exception:
                pass
            raise TimeoutError("安装超时。")
        if stdout.channel.recv_ready():
            chunk = stdout.channel.recv(4096).decode("utf-8", errors="ignore")
            buffer = flush(buffer + chunk)
        time.sleep(0.05)

    try:
        while stdout.channel.recv_ready():
            chunk = stdout.channel.recv(4096).decode("utf-8", errors="ignore")
            buffer = flush(buffer + chunk)
    except Exception:
        pass
    remaining = _clean_line(buffer)
    if remaining:
        lines.append(remaining)
        _emit(log_queue, remaining, redactions=redactions)
    return stdout.channel.recv_exit_status(), "\n".join(lines)


def _detect_platform(ssh, log_queue, stop_event, deadline, redactions) -> tuple[str, int]:
    code, output = _run_command(
        ssh, "uname -s && uname -m", log_queue, stop_event, deadline, redactions
    )
    if code == -1:
        return "", -1
    if code == 0:
        lowered = output.lower()
        if "darwin" in lowered and "arm64" in lowered:
            return "macos", 0
        if "darwin" in lowered:
            _emit(log_queue, "仅支持 macOS Apple Silicon（arm64），Intel Mac 不受支持。", "error", redactions)
            return "", 1
        _emit(log_queue, f"不支持的平台: {output}；仅支持 macOS Apple Silicon 和 Windows。", "error", redactions)
        return "", 1

    discovery = _powershell_command("Write-Output 'DonkeyDriftPlatform=windows'")
    windows_code, windows_output = _run_command(
        ssh, discovery, log_queue, stop_event, deadline, redactions
    )
    if windows_code == -1:
        return "", -1
    if windows_code == 0 and "DonkeyDriftPlatform=windows" in windows_output:
        return "windows", 0
    _emit(log_queue, "无法识别远程平台；仅支持 macOS Apple Silicon 和 Windows PowerShell。", "error", redactions)
    return "", 1


def _detect_remote_home(ssh, platform: str, log_queue, stop_event,
                        deadline, redactions) -> tuple[str, int]:
    script = "Write-Output ('DonkeyDriftHome=' + $HOME)"
    command = (_powershell_command(script) if platform == "windows"
               else "printf 'DonkeyDriftHome=%s\\n' \"$HOME\"")
    code, output = _run_command(
        ssh, command, log_queue, stop_event, deadline, redactions
    )
    if code != 0:
        return "", code
    marker = "DonkeyDriftHome="
    for line in output.splitlines():
        if line.startswith(marker) and line[len(marker):].strip():
            return line[len(marker):].strip(), 0
    return "", 1


def install_mypc_environment(
    host: str,
    user: str,
    password: str,
    repo_path: str,
    gym_path: str,
    python_path: str = "",
    port: int = 22,
    ssh_timeout: int = 10,
    log_queue: Optional[object] = None,
    stop_event=None,
    timeout: int = INSTALL_TIMEOUT,
    key_path: str = "",
) -> int:
    """Configure a shared Python 3.11 uv environment over one SSH connection."""
    del python_path
    repo_path = repo_path.strip()
    gym_path = gym_path.strip()
    if not repo_path or not gym_path:
        raise ValueError("DonkeyDrift 和 GymDonkeyCar 仓库路径不能为空。")

    redactions = (password,)
    _emit(log_queue, f"正在连接 {host}:{port} ...", redactions=redactions)
    ssh = _open_ssh(host, user, password, port=port, timeout=ssh_timeout, key_path=key_path)
    deadline = time.time() + timeout
    try:
        platform, code = _detect_platform(ssh, log_queue, stop_event, deadline, redactions)
        if code != 0:
            return code
        _emit(log_queue, f"检测到平台: {platform}", redactions=redactions)
        remote_home = ""
        if any(_path_needs_home(path, platform == "windows")
               for path in (repo_path, gym_path)):
            remote_home, code = _detect_remote_home(
                ssh, platform, log_queue, stop_event, deadline, redactions
            )
            if code == -1:
                return -1
            if code != 0:
                raise ValueError("无法检测远程用户主目录，不能展开仓库路径。")
        repo_path = _normalize_remote_path(repo_path, platform, remote_home)
        gym_path = _normalize_remote_path(gym_path, platform, remote_home)
        steps = _build_install_steps(platform, repo_path, gym_path)
        for index, step in enumerate(steps):
            _emit(log_queue, f"[{index + 1}/{len(steps)}] {step.name}", redactions=redactions)
            code, output = _run_command(
                ssh, step.command, log_queue, stop_event, deadline, redactions
            )
            if code == -1:
                return -1
            if code != 0 and step.name == "prepare-venv" and _is_python_download_timeout(output):
                _emit(log_queue, "Python 下载超时，使用批准的南大镜像重试一次。", "warning", redactions)
                retry = _build_install_steps(
                    platform, repo_path, gym_path, python_mirror=True
                )[index]
                code, _ = _run_command(
                    ssh, retry.command, log_queue, stop_event, deadline, redactions
                )
                if code == -1:
                    return -1
            if code != 0:
                _emit(log_queue, f"步骤 {step.name} 失败，退出码: {code}", "error", redactions)
                return code
        _emit(log_queue, "DonkeyDrift 环境配置完成，安装与自动激活验收通过。", "success", redactions)
        return 0
    finally:
        try:
            ssh.close()
        except Exception:
            pass
