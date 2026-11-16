#!/usr/bin/env python3
"""One-click local deployment of the DonkeyDrift environment.

Runs the same nine idempotent install steps as the DD Trainer "Lan Host"
one-click installer (``web_ui/backend/install_steps.py``) directly on this
machine — no SSH and no second machine required. Supports macOS Apple
Silicon and Windows; stdlib only, so it runs under the system python3 of a
fresh machine.
"""
import argparse
import os
import platform
import queue
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "web_ui" / "backend"))

from install_steps import (  # noqa: E402
    INSTALL_TIMEOUT,
    InstallStep,
    _build_install_steps,
    _clean_line,
    _is_python_download_timeout,
    _normalize_remote_path,
)


def detect_platform() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        if machine == "arm64":
            return "macos"
        raise ValueError("仅支持 macOS Apple Silicon（arm64），Intel Mac 不受支持。")
    if system == "windows":
        return "windows"
    raise ValueError(
        f"不支持的平台: {system} {machine}；仅支持 macOS Apple Silicon 和 Windows。"
    )


def default_gym_path(repo_root: Path) -> Path:
    return repo_root.parent / "gym-donkeycar"


def _run_step(step: InstallStep, deadline: float) -> tuple[int, list[str]]:
    if os.name == "nt":
        argv = step.command.split()
    else:
        argv = shlex.split(step.command)
    try:
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=os.path.expanduser("~"),
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"无法启动步骤 {step.name}: {exc}") from exc

    lines: list[str] = []
    out_queue: "queue.Queue[bytes | None]" = queue.Queue()

    def _read_stdout() -> None:
        for raw in iter(process.stdout.readline, b""):
            out_queue.put(raw)
        out_queue.put(None)

    threading.Thread(target=_read_stdout, daemon=True).start()
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            process.kill()
            raise TimeoutError("安装超时。")
        try:
            raw = out_queue.get(timeout=min(0.2, remaining))
        except queue.Empty:
            continue
        if raw is None:
            break
        line = _clean_line(raw.decode("utf-8", errors="ignore"))
        if line:
            lines.append(line)
            print(f"  {line}", flush=True)
    process.wait()
    return process.returncode, lines


def deploy(repo_path: str, gym_path: str, timeout: int = INSTALL_TIMEOUT,
           dry_run: bool = False) -> int:
    platform_name = detect_platform()
    home = os.path.expanduser("~")
    repo_path = _normalize_remote_path(repo_path, platform_name, home)
    gym_path = _normalize_remote_path(gym_path, platform_name, home)
    steps = _build_install_steps(platform_name, repo_path, gym_path)

    print(f"DonkeyDrift 一键部署（平台: {platform_name}）")
    print(f"DonkeyDrift 仓库: {repo_path}")
    print(f"GymDonkeyCar 仓库: {gym_path}")
    if dry_run:
        for index, step in enumerate(steps):
            print(f"[{index + 1}/{len(steps)}] {step.name} (dry-run)")
        return 0

    deadline = time.time() + timeout
    for index, step in enumerate(steps):
        print(f"[{index + 1}/{len(steps)}] {step.name}")
        code, output = _run_step(step, deadline)
        if code != 0 and step.name == "prepare-venv" and _is_python_download_timeout(
            "\n".join(output)
        ):
            print("Python 下载超时，使用批准的南大镜像重试一次。")
            retry = _build_install_steps(
                platform_name, repo_path, gym_path, python_mirror=True
            )[index]
            code, output = _run_step(retry, deadline)
        if code != 0:
            print(f"步骤 {step.name} 失败，退出码: {code}")
            print("环境尚未完成；解决上述问题后重新运行本工具，已完成的步骤会自动复用。")
            return code

    print()
    print("DonkeyDrift 环境部署完成，安装与自动激活验收通过。")
    print(f"打开新的终端窗口，进入 {repo_path} 即自动激活环境（donkey CLI 可用）。")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "DonkeyDrift 环境一键部署：在本机执行与 DD 页面「局域网主机一键安装」"
            "完全一致的安装与验收步骤，无需 SSH。"
        )
    )
    parser.add_argument(
        "--repo",
        default=str(REPO_ROOT),
        help="DonkeyDrift 仓库路径（默认：本脚本所在仓库）",
    )
    parser.add_argument(
        "--gym",
        default=str(default_gym_path(REPO_ROOT)),
        help="GymDonkeyCar 仓库路径（默认：仓库旁路 gym-donkeycar，不存在则自动克隆）",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=INSTALL_TIMEOUT,
        help=f"整体超时秒数（默认 {INSTALL_TIMEOUT}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印将执行的步骤，不实际运行",
    )
    args = parser.parse_args(argv)
    try:
        return deploy(args.repo, args.gym, timeout=args.timeout, dry_run=args.dry_run)
    except KeyboardInterrupt:
        print("\n部署已停止；重新运行本工具可继续。")
        return 130
    except TimeoutError as exc:
        print(f"\n{exc} 重新运行本工具可继续。")
        return 124
    except (ValueError, RuntimeError) as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
