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

import atexit
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

# 实例登记文件与车进程 PID 文件（与 base.py / tui.py / launcher 既有约定一致）
WEBUI_INSTANCE_FILE = Path.home() / ".donkeycar" / "webui.json"
DRIVE_PID_FILE = Path.home() / ".donkeycar" / "drive.pid"
# 当前选定自动驾驶模型（issue #003）：web_ui 后端写入，launcher 每次
# 起车进程时读取并附加 --model/--type，选择跨重启保持。
DRIVE_MODEL_FILE = Path.home() / ".donkeycar" / "drive_model.json"

# 探测超时（秒）：仅本机回环探测，快速失败
PROBE_TIMEOUT_S = 2.0

# 硬杀信号：Windows 没有 SIGKILL（且 os.kill 对非 CTRL_*_EVENT 的任意 sig 都是
# TerminateProcess，SIGTERM 本身即强杀），故为 None 时跳过「SIGTERM 后再升级
# SIGKILL」的第二阶段——否则 signal.SIGKILL 取属性就 AttributeError。
_SIGKILL = getattr(signal, "SIGKILL", None)


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

def _pid_gone_error(exc):
    """异常是否表示「pid 已不存在」（Windows ``winerror=87``）。

    Windows 上 ``os.kill`` 面对不存在、或正处于退出过程中的 pid 会失败：
    前者抛原生 ``OSError``（``winerror=87`` ERROR_INVALID_PARAMETER），
    后者 CPython 偶发把它包成 ``SystemError``（``__cause__`` 才是那个
    ``OSError``），此时 ``except OSError`` 抓不住、会冒泡崩掉 TUI。
    """
    if isinstance(exc, SystemError):
        exc = exc.__cause__
    return isinstance(exc, OSError) and getattr(exc, "winerror", None) == 87


def _pid_alive_windows(pid):
    """Windows 探活：OpenProcess + GetExitCodeProcess，安全且无副作用。

    **绝不能**用 ``os.kill(pid, 0)``：Python 文档明示，Windows 上 os.kill 对
    CTRL_C_EVENT/CTRL_BREAK_EVENT 之外的任意 sig（含 0）都会走
    ``TerminateProcess``——即「探活」会把目标进程杀掉。曾因此在 TUI/launcher
    每次复用探测时杀掉正在跑的 Web UI（uvicorn 变孤儿、实例登记被判陈旧），
    于是又新起一个后端 → 双后端并存、页面连不到车端（表现为「没有画面」）。
    """
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ERROR_ACCESS_DENIED = 5
    STILL_ACTIVE = 259

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                            ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False,
                                  int(pid))
    if not handle:
        # 打不开：进程不存在 -> ERROR_INVALID_PARAMETER(87) 判死；
        # 拒绝访问(5) 说明进程在、只是没权限 -> 视为存活交端口探测裁决。
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid):
    """pid 是否有存活进程（无权限视为存活，交给端口探测裁决）。

    Windows 走 ``_pid_alive_windows``（OpenProcess），**不得**用
    ``os.kill(pid, 0)``——Windows 上那是 TerminateProcess，会把目标进程杀掉
    （见 ``_pid_alive_windows`` docstring）。POSIX 才用 ``os.kill(pid, 0)``，
    其中不存在抛 ``ProcessLookupError``、无权限抛 ``PermissionError``。
    """
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        return not _pid_gone_error(exc)
    except SystemError as exc:
        return not _pid_gone_error(exc)
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


# ── drive 单实例守护（防多车端进程互踢，2026-09-25）──────────────────

# drive 实例登记：所有启动链路（终端直跑 / donkey web / launcher）统一
# 在 drive() 开头登记自己、退出时清除；后来者发现存活实例即拒绝启动，
# 避免多个 manage.py drive 互相抢占后端唯一 car 槽位（连接风暴、无画面）。
DRIVE_INSTANCE_FILE = Path.home() / ".donkeycar" / "drive_instance.json"


class DriveAlreadyRunning(RuntimeError):
    """已有存活的 drive 进程，本次启动被拒绝。"""


def _proc_start_time(pid):
    """读 /proc/<pid>/stat 的进程启动时钟（第 22 字段）；失败返回 None。"""
    try:
        with open(f"/proc/{int(pid)}/stat", "rb") as f:
            stat = f.read().decode("utf-8", "replace")
        # comm 可能含空格/括号，从最右 ")" 之后切分再取第 20 个字段
        #（切掉 pid/comm 后，原第 22 字段成为第 20 个）
        return stat.rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError, ValueError):
        return None


def _drive_instance_alive(entry):
    """登记的 drive 实例是否仍存活（pid 存活 + 启动时钟一致防 PID 复用）。"""
    if not isinstance(entry, dict) or not isinstance(entry.get("pid"), int):
        return False
    if not _pid_alive(entry["pid"]):
        return False
    started_at = entry.get("started_at")
    current = _proc_start_time(entry["pid"])
    if current is None or started_at is None:
        # 非 Linux 无 /proc：退化为仅 pid 存活判定
        return True
    return str(started_at) == str(current)


def acquire_drive_instance_lock(instance_file=None):
    """drive 启动前调用：已有存活实例则抛 ``DriveAlreadyRunning``。

    无冲突时登记自己（pid + /proc 启动时钟，防 PID 复用误判）并注册
    atexit 清理；异常退出留下的陈旧登记会在下次启动时因 pid 已死被覆盖。
    同进程重复调用幂等。返回本次登记 dict。
    """
    if instance_file is None:
        instance_file = DRIVE_INSTANCE_FILE
    path = Path(instance_file)
    pid = os.getpid()
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        entry = None
    if isinstance(entry, dict) and entry.get("pid") == pid:
        return entry
    if _drive_instance_alive(entry):
        raise DriveAlreadyRunning(
            f"检测到已运行的 drive 进程（pid={entry['pid']}）。"
            "多个 manage.py drive 会互相抢占车端连接，导致连接风暴、"
            f"页面无画面；请先停止旧进程（kill {entry['pid']}）再启动。"
            f"若确认是陈旧登记，删除 {path} 后重试。"
        )
    record = {"pid": pid, "started_at": _proc_start_time(pid)}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    os.replace(tmp, path)
    atexit.register(release_drive_instance_lock, instance_file)
    return record


def release_drive_instance_lock(instance_file=None):
    """清除本进程的 drive 实例登记（仅当登记仍属于本进程）。"""
    if instance_file is None:
        instance_file = DRIVE_INSTANCE_FILE
    path = Path(instance_file)
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(entry, dict) and entry.get("pid") == os.getpid():
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


# ── 选定模型持久化（issue #003）─────────────────────────────────────

def read_drive_model(model_file=None):
    """读选定模型记录；文件缺失/损坏/字段非法返回 None。

    记录格式：``{"model": 绝对路径, "model_type": str|None, "selected_at": ...}``
    """
    if model_file is None:
        model_file = DRIVE_MODEL_FILE
    try:
        data = json.loads(Path(model_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("model"), str) \
            and data["model"].strip():
        return data
    return None


def write_drive_model(model_path, model_type=None, model_file=None):
    """写入选定模型记录（原子替换）。"""
    if model_file is None:
        model_file = DRIVE_MODEL_FILE
    payload = {
        "model": str(model_path),
        "model_type": model_type if model_type else None,
        "selected_at": time.time(),
    }
    path = Path(model_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)
    return payload


def remove_drive_model(model_file=None):
    """删除选定模型记录（选「无模型」时调用）。"""
    if model_file is None:
        model_file = DRIVE_MODEL_FILE
    try:
        Path(model_file).unlink(missing_ok=True)
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


def _is_python_proc(command):
    """ps 快照的命令行是否为 python 进程（首词 basename 以 python 开头）。

    ps 快照把 argv 以空格 join 成字符串做子串判定，会误命中 ``bash -c
    "...manage.py drive..."`` 这类**命令文本里恰好含特征词**的包装器——
    排查命令里带 grep/pgrep 特征词时甚至扫到并杀掉执行清扫的 shell 自己
    （Linux /proc 路径按 cmdline 列表判定不存在此问题，本函数补齐语义）。
    车端/uvicorn 都由 python 解释器启动，首词必须是 python 才参与匹配。
    """
    first = command.split(None, 1)[0] if command else ""
    return os.path.basename(first).startswith("python")


def find_car_processes(exclude_pids=None, proc_dir="/proc"):
    """扫描在跑的车进程（manage.py drive），返回 pid 列表。

    Linux 走 /proc 逐个读 cmdline；其余 POSIX（macOS 无 /proc）退化为
    ``ps -axww`` 全量快照匹配（python 打头 + manage.py drive，见
    ``_is_python_proc``）。Windows 两路都不可用，返回 []。
    排除当前进程与 exclude_pids。
    """
    exclude = set(exclude_pids or ())
    pids = []
    try:
        entries = os.listdir(proc_dir)
    except OSError:
        entries = None
    if entries is not None:
        for entry in entries:
            if not entry.isdigit():
                continue
            pid = int(entry)
            if pid == os.getpid() or pid in exclude:
                continue
            if _is_car_process(pid):
                pids.append(pid)
        return pids
    # macOS 等 POSIX：ps 快照匹配（要求 python 打头，见 _is_python_proc）
    for proc in _run_ps_snapshot():
        pid = proc["pid"]
        if pid == os.getpid() or pid in exclude:
            continue
        cmd = proc["command"]
        if _is_python_proc(cmd) and "manage.py" in cmd and "drive" in cmd:
            pids.append(pid)
    return pids


def _kill_process_tree(pid):
    """Windows：``taskkill /T /F`` 终止 pid 及其所有子进程。

    **只按 pid 杀不够**：uv 建的 venv ``python.exe`` 只是 shim，真正跑
    ``manage.py`` 的是它 re-exec 出来的子进程（Popen 拿到的 pid 是 shim 的）。
    旧实现只杀 shim → 留下孤儿车进程，随后被 drive 单实例守护判为「已在运行」
    而拒绝新进程（表现为车端离线、报「检测到已运行的 drive 进程（pid=...）」）。
    """
    try:
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                       capture_output=True, check=False)
    except Exception:
        pass


def _terminate_processes(pids, grace_s):
    """尽力终止 pids（吞掉「已不存在/无权限」类错误）。

    Windows：``taskkill /T /F`` 一次连带子进程杀净（无 SIGKILL，os.kill 的
    SIGTERM 本身即 TerminateProcess）；POSIX：先 SIGTERM，宽限 ``grace_s``
    秒后对尚存者补 SIGKILL（Windows 无 ``signal.SIGKILL``）。
    """
    if not pids:
        return
    if os.name == "nt":
        for pid in pids:
            _kill_process_tree(pid)
        return
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, SystemError):
            pass
    if _SIGKILL is not None:
        threading.Event().wait(grace_s)
        for pid in pids:
            try:
                os.kill(pid, _SIGKILL)
            except (OSError, SystemError):
                pass


def takeover_car_processes(exclude_pids=None):
    """接管模式：杀掉所有在跑的车进程（含非本链路启动的），供新 drive 启动。

    与 kill_previous_car_processes 只按 PID 文件清理不同，本函数按 cmdline
    全量扫描在跑的 manage.py drive 一并终止，确保新 drive 不会被单实例守护
    （DriveAlreadyRunning）拒绝、抢占车端连接。web 前后端与 launcher 进程
    不在清理之列。返回本次杀掉的 pid 列表。
    """
    pids = find_car_processes(exclude_pids=exclude_pids)
    # 给被杀进程的父进程（TUI monitor 循环）留出回收时间，避免僵尸 pid
    # 被 drive 实例登记误判为存活
    _terminate_processes(pids, grace_s=1.0)
    return pids


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
    _terminate_processes(targets, grace_s=0.5)
    remove_drive_pid_file(pid_file)


# ── 孤儿栈进程清扫（drive 启动前统一入口，2026-11-09 macOS 实战）────

def _run_ps_snapshot():
    """POSIX 全量进程快照（macOS 无 /proc，识别孤儿统一走 ps）。

    返回 [{"pid", "ppid", "command"}]；非 POSIX / ps 失败返回 []。
    ``-axww``：全量进程 + 宽输出不截断命令行（BSD ps 与 procps 均支持）。
    """
    if os.name != "posix":
        return []
    try:
        out = subprocess.run(
            ["ps", "-axww", "-o", "pid=,ppid=,command="],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    snapshot = []
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        try:
            snapshot.append({
                "pid": int(parts[0]),
                "ppid": int(parts[1]),
                "command": parts[2],
            })
        except ValueError:
            continue
    return snapshot


def _process_cwd(pid):
    """读进程 cwd：Linux 走 /proc symlink；其余 POSIX 走 lsof。失败返回 None。"""
    if os.name == "posix":
        try:
            return os.readlink(f"/proc/{int(pid)}/cwd")
        except OSError:
            pass
        try:
            out = subprocess.run(
                ["lsof", "-a", "-p", str(int(pid)), "-d", "cwd", "-Fn"],
                capture_output=True, text=True, timeout=5,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        for line in out.splitlines():
            # lsof -F 输出格式：字段标识前缀 + 值，路径行以 n 开头
            if line.startswith("n"):
                return line[1:]
    return None


def _is_webui_backend_cmdline(command):
    """命令行是否为 web_ui 后端 uvicorn（python -m uvicorn main:app ...）。"""
    return "uvicorn" in command and "main:app" in command


def _is_webui_backend_cwd(cwd):
    """cwd 是否为某个仓库的 web_ui/backend（donkey web 起后端固定在此目录，
    手工裸起按文档也在此目录——以此把别的 FastAPI 项目的 uvicorn 排除掉）。"""
    if not cwd:
        return False
    parts = os.path.normpath(cwd).replace("\\", "/").rstrip("/").split("/")
    return len(parts) >= 2 and parts[-2:] == ["web_ui", "backend"]


def _descendant_pids(root_pid, snapshot):
    """快照里 root_pid 的全部后代 pid（含间接，不含自身）。"""
    children = {}
    for proc in snapshot:
        children.setdefault(proc["ppid"], []).append(proc["pid"])
    seen, stack = [], [root_pid]
    while stack:
        pid = stack.pop()
        for child in children.get(pid, ()):
            if child not in seen:
                seen.append(child)
                stack.append(child)
    return seen


def find_webui_backend_processes(protected_pids=None):
    """扫描在跑的 web_ui 后端（python 打头的 uvicorn main:app，且 cwd 为
    */web_ui/backend）。

    protected_pids：存活登记实例的进程树（复用场景绝不能杀，见 sweep）。
    cwd 无法判定（lsof 失败/进程竞态退出）时不计入——误杀别的 FastAPI
    项目的代价远大于漏杀孤儿。返回 pid 列表。
    """
    protected = set(protected_pids or ())
    pids = []
    for proc in _run_ps_snapshot():
        pid = proc["pid"]
        if pid == os.getpid() or pid in protected:
            continue
        if not _is_python_proc(proc["command"]):
            continue
        if not _is_webui_backend_cmdline(proc["command"]):
            continue
        if _is_webui_backend_cwd(_process_cwd(pid)):
            pids.append(pid)
    return pids


def sweep_orphan_processes():
    """drive 启动前清扫孤儿栈进程，返回 {"car_pids", "backend_pids"}。

    孤儿从哪来：手工 nohup / 终端裸起的 manage.py drive、uvicorn 不在
    drive.pid 与 webui.json 任何登记里，既有清理（kill_previous_car_processes
    按 PID 文件、find_live_instance 按登记）均触及不到：
    - 无登记 uvicorn → find_live_instance 判「无实例」→ 再起一套 → 双后端，
      页面停在旧后端时表现为无画面、摇杆指令无效（2026-11-09 线上复现）
    - 无登记车端 → drive 单实例守护拒绝启动（「检测到已运行的 drive 进程」）
    - SIGTERM 卡在优雅关闭的 uvicorn（aiortc 协程残留）→ 两段式补 SIGKILL
    处理：
    - 车端：takeover_car_processes 全量接管（macOS 经 ps 快照，Linux /proc）
    - uvicorn：有存活登记实例 → 只杀登记进程树之外的（顺带修复双后端）；
      无登记 → 全部视为孤儿杀掉。
    web 前端（vite/bundled 静态托管）与模拟器（DonkeySim）不在清理之列。
    """
    report = {"car_pids": [], "backend_pids": []}
    inst = find_live_instance()
    report["car_pids"] = takeover_car_processes()
    protected = []
    if inst:
        snapshot = _run_ps_snapshot()
        protected = [inst["pid"]] + _descendant_pids(inst["pid"], snapshot)
    backend_pids = find_webui_backend_processes(protected_pids=protected)
    if backend_pids:
        _terminate_processes(backend_pids, grace_s=1.0)
        report["backend_pids"] = backend_pids
    return report


# ── NPU 相关进程解释器选择 ──────────────────────────────────────────

def _venv_npu_python() -> str:
    """仓库 .venv-npu/bin/python 路径（aidlite 唯一所在，见 parts/npu_pilot.py）。"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, '.venv-npu', 'bin', 'python')


def _prefer_venv_npu() -> str:
    candidate = _venv_npu_python()
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return sys.executable


def select_car_python() -> str:
    """车进程解释器选择：NPU 环境 .venv-npu 优先，DONKEY_CAR_PYTHON 可覆盖。

    车端 NPU(.aidem)与无 TF 的 .tflite 推理都依赖 aidlite——只存在于系统
    python3.12（.venv-npu 挂系统站点包）。
    供 base.py（donkey drive）、tui.py、launcher 三条拉车链路共用，
    本模块仅依赖标准库，各链路均可安全导入。
    找不到 .venv-npu 时退回 sys.executable，保持原有行为。
    """
    override = os.environ.get('DONKEY_CAR_PYTHON', '').strip()
    if override:
        return override
    return _prefer_venv_npu()


def select_backend_python() -> str:
    """web 后端（uvicorn）进程解释器选择：.venv-npu 优先，可被
    DONKEY_BACKEND_PYTHON / DONKEY_CAR_PYTHON 覆盖。

    Pilot Arena 的 pilot 加载与推理（routers/arena.py →
    get_model_by_type('aidlite_linear') → parts/npu_pilot.py）跑在 uvicorn
    进程内，同样依赖 aidlite——后端"可以是任意 python"的原假设随 Arena 支持
    .aidem 失效。候选解释器能否跑后端（fastapi/uvicorn/multipart/websockets
    是否齐全）由调用方探测，本函数只做路径选择。
    """
    for var in ('DONKEY_BACKEND_PYTHON', 'DONKEY_CAR_PYTHON'):
        override = os.environ.get(var, '').strip()
        if override:
            return override
    return _prefer_venv_npu()


def open_url_best_effort(url: str) -> bool:
    """尽力在本机拉起浏览器打开 URL（base.py --open 与 TUI 复用分支共用）。

    远程会话（SSH/ZCode 终端）没有 DISPLAY，``webbrowser.open`` 会**静默**
    返回 False——此前表现为「启动 drive 后网页毫无反应且无任何提示」。
    此时若本机存在桌面 X 会话（/tmp/.X11-unix/X0），回退用 ``DISPLAY=:0``
    的 xdg-open 在桌面上打开（与 launcher 拉起桌面应用的口径一致）。
    返回是否成功派发；失败由调用方打印可手动访问的地址。
    """
    try:
        if webbrowser.open(url):
            return True
    except Exception:
        pass
    if not os.environ.get('DISPLAY') and os.path.exists('/tmp/.X11-unix/X0'):
        try:
            env = dict(os.environ)
            env['DISPLAY'] = ':0'
            result = subprocess.run(
                ['xdg-open', url], env=env, timeout=10,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return result.returncode == 0
        except Exception:
            return False
    return False
