import os
import posixpath
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Iterable, Optional


_DANGEROUS_PATH_RE = re.compile(r"[\n\r\x00;&|`$<>]")
_VALID_FORMATS = {"h5", "savedmodel", "tflite", "trt"}


@dataclass
class ConnectorConfig:
    host: str
    user: str
    port: int = 22
    car_dir: str = "~/mycar"
    key_path: Optional[str] = None

    @property
    def target(self) -> str:
        return f"{self.user}@{self.host}"


def validate_remote_path(path: str) -> str:
    value = path.strip()
    if not value:
        raise ValueError("远端路径不能为空")
    if _DANGEROUS_PATH_RE.search(value):
        raise ValueError("远端路径包含不安全字符")
    return value


def validate_remote_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise ValueError("远端名称不能为空")
    if "/" in value or "\\" in value or value in {".", ".."}:
        raise ValueError("远端名称不能包含路径分隔符")
    return validate_remote_path(value)


def remote_join(*parts: str) -> str:
    cleaned = [validate_remote_path(part).rstrip("/") for part in parts if part]
    if not cleaned:
        raise ValueError("远端路径不能为空")
    result = cleaned[0]
    for part in cleaned[1:]:
        result = posixpath.join(result, part.lstrip("/"))
    return result


def build_ssh_base(config: ConnectorConfig) -> list[str]:
    command = ["ssh", "-p", str(config.port), "-o", "ConnectTimeout=3"]
    if config.key_path:
        command.extend(["-i", os.path.expanduser(config.key_path)])
    command.append(config.target)
    return command


def build_pull_tub_command(
    config: ConnectorConfig,
    remote_tub: str,
    local_data_path: str,
    create_new_dir: bool,
) -> list[str]:
    car_dir = validate_remote_path(config.car_dir)
    tub_name = validate_remote_name(remote_tub)
    remote_path = remote_join(car_dir, tub_name)
    if not create_new_dir:
        remote_path += "/"
    return [
        "rsync",
        "-rv",
        "--progress",
        "--partial",
        f"{config.target}:{remote_path}",
        local_data_path,
    ]


def build_push_pilots_command(
    config: ConnectorConfig,
    local_models_path: str,
    formats: Iterable[str],
) -> list[str]:
    selected = [fmt for fmt in formats if fmt]
    invalid = [fmt for fmt in selected if fmt not in _VALID_FORMATS]
    if invalid:
        raise ValueError(f"不支持的模型格式: {', '.join(invalid)}")

    filters = ["--include=database.json"]
    for fmt in selected:
        if fmt in {"savedmodel", "trt"}:
            filters.append(f"--include=*.{fmt}/***")
        else:
            filters.append(f"--include=*.{fmt}")
    filters.append("--exclude=*" if selected else "--include=*")

    source = local_models_path.rstrip("/\\") + "/"
    destination = f"{config.target}:{remote_join(config.car_dir, 'models')}"
    return ["rsync", "-rv", "--progress", "--partial", *filters, source, destination]


def validate_bridge_url(url: str) -> str:
    value = url.strip()
    if not value.startswith(("ws://", "wss://")):
        raise ValueError("DriveApiBridge 回连地址必须以 ws:// 或 wss:// 开头")
    if _DANGEROUS_PATH_RE.search(value):
        raise ValueError("DriveApiBridge 回连地址包含不安全字符")
    return value


def build_remote_drive_start_command(
    config: ConnectorConfig,
    model_type: Optional[str] = None,
    pilot: Optional[str] = None,
    bridge_server_url: Optional[str] = None,
) -> list[str]:
    car_dir = validate_remote_path(config.car_dir)
    parts = []
    if bridge_server_url:
        parts.append(f"DRIVE_API_SERVER_URL={shlex.quote(validate_bridge_url(bridge_server_url))}")
    parts.extend(["python", "manage.py", "drive"])
    if pilot:
        model_name = validate_remote_name(pilot)
        if not model_type:
            raise ValueError("选择 pilot 时必须提供模型类型")
        parts.extend(["--type", shlex.quote(model_type), "--model", shlex.quote(remote_join(car_dir, "models", model_name))])
    drive_command = " ".join(parts)
    remote_command = (
        f"cd {shlex.quote(car_dir)} && "
        f"nohup {drive_command} > .donkeycar_drive.log 2>&1 & "
        "pid=$!; "
        "echo \"$pid\" > .donkeycar_drive.pid; "
        "echo \"$pid\""
    )
    return [*build_ssh_base(config), remote_command]


def build_remote_drive_stop_command(config: ConnectorConfig, pid: int) -> list[str]:
    if pid <= 0:
        raise ValueError("PID 无效")
    car_dir = validate_remote_path(config.car_dir)
    remote_command = " && ".join([
        f"cd {shlex.quote(car_dir)}",
        "car_dir=$(pwd -P)",
        f"pid={pid}",
        "if [ -f .donkeycar_drive.pid ]; then file_pid=$(cat .donkeycar_drive.pid); if [ \"$file_pid\" != \"$pid\" ]; then echo 'PID 与 .donkeycar_drive.pid 不匹配，已拒绝停止'; exit 1; fi; fi",
        "args=$(ps -p \"$pid\" -o args=) || { echo 'PID 不存在或已退出'; exit 1; }",
        "case \"$args\" in *'manage.py drive'*) ;; *) echo 'PID 不是 Donkeycar drive 进程，已拒绝停止'; exit 1; ;; esac",
        "cwd=$(readlink /proc/$pid/cwd) || { echo '无法读取 PID 工作目录，已拒绝停止'; exit 1; }",
        "if [ \"$cwd\" != \"$car_dir\" ]; then echo 'PID 工作目录不匹配，已拒绝停止'; exit 1; fi",
        "kill -SIGINT \"$pid\"",
        "rm -f .donkeycar_drive.pid",
        "echo '远程驾驶进程已停止'",
    ])
    return [*build_ssh_base(config), remote_command]


def build_remote_rsync_check_command(config: ConnectorConfig) -> list[str]:
    remote_command = "command -v rsync >/dev/null 2>&1 || { echo '车端缺少 rsync，请在车端安装: sudo apt install rsync'; exit 127; }"
    return [*build_ssh_base(config), remote_command]


def parse_rsync_progress(line: str) -> Optional[float]:
    match = re.search(r"to-(?:check|chk)=(\d+)/(\d+)\)", line)
    if not match:
        return None
    remaining = int(match.group(1))
    total = int(match.group(2))
    if total == 0:
        return 100.0
    return 100.0 * (1.0 - remaining / total)


class RemoteCarClient:
    def __init__(self, config: ConnectorConfig):
        self.config = config

    def check_connection(self) -> tuple[bool, str]:
        command = [*build_ssh_base(self.config), "date"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=8, check=False)
        except FileNotFoundError:
            return False, "ssh 命令不可用，请先安装 OpenSSH 客户端"
        except subprocess.TimeoutExpired:
            return False, f"连接超时: {self.config.host}"
        if result.returncode == 0:
            return True, f"已连接到 {self.config.host}"
        message = (result.stderr or result.stdout or "SSH 连接失败").strip()
        return False, message

    def list_remote_dir(self, path: str) -> list[str]:
        remote_path = validate_remote_path(path)
        command = [*build_ssh_base(self.config), f"ls -1 {shlex.quote(remote_path)}"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
        except FileNotFoundError as exc:
            raise RuntimeError("ssh 命令不可用，请先安装 OpenSSH 客户端") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"读取远端目录超时: {remote_path}") from exc
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "远端目录读取失败").strip())
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def list_tubs(self) -> list[str]:
        return self.list_remote_dir(self.config.car_dir)

    def list_models(self) -> list[str]:
        return self.list_remote_dir(remote_join(self.config.car_dir, "models"))
