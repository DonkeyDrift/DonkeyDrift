#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web UI 实例登记与复用（issue #127）。

`donkey web` / `donkey drive` / Launcher（D 页面 6 号）/ TUI（7 号）四条
启动链路统一走"先找存活实例→复用；没有才新起并登记"，避免互杀与端口漂移：

- 实例登记文件 ``~/.donkeycar/webui.json``：
  ``{"pid": ..., "backend_port": ..., "frontend_port": ..., "started_at": ...}``
  由 ``donkey web``（base.py ``Web.run``）启动成功后写入、退出时清除。
- 复用判定（``find_live_instance``）：登记 pid 存活 + 后端 ``/docs`` 与
  前端 ``/`` 探测均通；任一失效则视为陈旧登记，清掉后返回 None。
- 车进程清理（``kill_previous_car_processes``）：只杀 ``drive.pid`` 里
  cmdline 含 ``manage.py drive`` 的进程（web 进程保留复用），解决摄像头
  等硬件占用只需重启车进程的问题；非 Linux 无 /proc 时退化为按 PID 全杀
  （与旧行为一致）。

设计参考 ``donkeycar/launcher/kimi_web.py`` 的实例登记 + 探测复用模式。
"""

import json
import os
import signal
import threading
import time
import urllib.request
from pathlib import Path

# 实例登记文件与车进程 PID 文件（与 base.py / tui.py / launcher 既有约定一致）
WEBUI_INSTANCE_FILE = Path.home() / ".donkeycar" / "webui.json"
DRIVE_PID_FILE = Path.home() / ".donkeycar" / "drive.pid"

# 探测超时（秒）：仅本机回环探测，快速失败
PROBE_TIMEOUT_S = 2.0


# ── 实例登记读写 ────────────────────────────────────────────────────

def read_instance(instance_file=None):
    """读实例登记；文件缺失/损坏返回 None。"""
    if instance_file is None:
        instance_file = WEBUI_INSTANCE_FILE
    try:
        data = json.loads(Path(instance_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("pid"), int) \
            and isinstance(data.get("backend_port"), int) \
            and isinstance(data.get("frontend_port"), int):
        return data
    return None


def write_instance(backend_port, frontend_port, pid=None,
                   instance_file=None):
    """写入实例登记（原子替换）。pid 缺省为当前进程。"""
    if instance_file is None:
        instance_file = WEBUI_INSTANCE_FILE
    payload = {
        "pid": pid if pid is not None else os.getpid(),
        "backend_port": int(backend_port),
        "frontend_port": int(frontend_port),
        "started_at": time.time(),
    }
    path = Path(instance_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)
    return payload


def remove_instance(only_pid=None, instance_file=None):
    """清除实例登记。

    only_pid 给定时，仅当登记里的 pid 与之一致才清除（避免清掉他人
    后来覆盖写入的新登记）；不一致时不动。
    """
    if instance_file is None:
        instance_file = WEBUI_INSTANCE_FILE
    path = Path(instance_file)
    if only_pid is None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return
    inst = read_instance(path)
    if inst and inst["pid"] == only_pid:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


# ── 存活探测与复用 ──────────────────────────────────────────────────

def _pid_alive(pid):
    """pid 是否有存活进程（无权限视为存活，交给端口探测裁决）。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _probe_http_ok(port, path="/", host="127.0.0.1",
                   timeout=PROBE_TIMEOUT_S):
    """GET http://host:port/path，返回是否 2xx/3xx。"""
    url = f"http://{host}:{int(port)}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except Exception:
        return False


# 公开别名：launcher 等跨模块复用 HTTP 探测（issue #134）
probe_http_ok = _probe_http_ok


def find_live_instance(instance_file=None):
    """找存活的 Web UI 实例，返回登记 dict；没有（或已失效）返回 None。

    判定链：登记存在 → pid 存活 → 后端 ``/docs``（FastAPI 自带，必存在）
    与前端 ``/``（Vite/静态托管）探测均通。失效时清掉陈旧登记。
    """
    if instance_file is None:
        instance_file = WEBUI_INSTANCE_FILE
    inst = read_instance(instance_file)
    if inst is None:
        return None
    if not _pid_alive(inst["pid"]):
        remove_instance(inst["pid"], instance_file)
        return None
    if not (_probe_http_ok(inst["backend_port"], "/docs")
            and _probe_http_ok(inst["frontend_port"], "/")):
        remove_instance(inst["pid"], instance_file)
        return None
    return inst


# ── 车进程 PID 文件与清理 ───────────────────────────────────────────

def read_drive_pids(pid_file=None):
    """读取上次记录的进程 PID 列表。"""
    if pid_file is None:
        pid_file = DRIVE_PID_FILE
    try:
        text = Path(pid_file).read_text(encoding="utf-8")
    except OSError:
        return []
    pids = []
    for line in text.splitlines():
        line = line.strip()
        try:
            pids.append(int(line))
        except ValueError:
            continue
    return pids


def write_drive_pids(pids, pid_file=None):
    """将进程 PID 列表写入记录文件。"""
    if pid_file is None:
        pid_file = DRIVE_PID_FILE
    path = Path(pid_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{int(p)}\n" for p in pids), encoding="utf-8",
    )


def remove_drive_pid_file(pid_file=None):
    """删除 PID 记录文件。"""
    if pid_file is None:
        pid_file = DRIVE_PID_FILE
    try:
        Path(pid_file).unlink(missing_ok=True)
    except OSError:
        pass


def _process_cmdline(pid):
    """读进程 cmdline（NUL 分隔）；非 Linux 或进程不存在返回 None。"""
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as f:
            raw = f.read()
    except OSError:
        return None
    return [part.decode("utf-8", "replace")
            for part in raw.split(b"\0") if part]


def _is_car_process(pid):
    """pid 的 cmdline 是否为 manage.py drive（车进程）。

    无法读取 cmdline（非 Linux 平台）时返回 None，表示无法判定，
    由调用方决定退化策略。
    """
    cmdline = _process_cmdline(pid)
    if cmdline is None:
        return None
    return "manage.py" in cmdline and "drive" in cmdline


def kill_previous_car_processes(pid_file=None):
    """杀掉上一次启动遗留的车进程（manage.py drive），释放摄像头等硬件。

    web 前后端进程不在清理之列（保留供复用）。非 Linux 平台无法按
    cmdline 区分时，退化为按 PID 文件全杀（与旧行为一致）。
    """
    if pid_file is None:
        pid_file = DRIVE_PID_FILE
    pids = read_drive_pids(pid_file)
    if not pids:
        return
    can_filter = hasattr(os, "kill") and Path("/proc").is_dir()
    targets = []
    for pid in pids:
        if can_filter:
            is_car = _is_car_process(pid)
            if is_car is False:
                continue  # web 进程，保留
        targets.append(pid)
    for pid in targets:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    threading.Event().wait(0.5)
    for pid in targets:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    remove_drive_pid_file(pid_file)
