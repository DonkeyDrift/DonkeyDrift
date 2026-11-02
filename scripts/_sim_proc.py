"""sim 进程生命周期助手(rl_smoke/rl_teleop/dualsim 共用)。

纪律红线(工作订单):严禁 pkill/pkill -f——停止只走两条精确路径:
a) 本脚本自己拉起的子进程:精确 SIGTERM 该 pid → 等退出 → SIGKILL 兜底;
b) 外部手动启动的 sim:``lsof -ti tcp:<port>`` 精确到监听该端口的进程。

sim 家族命令行(与 gym_donkeycar/envs/donkey_proc.py 同款拼装):
    <exe> --port <N> --host <H> [-batchmode [-nographics]] -logFile <file>
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from typing import Optional

__all__ = ["launch_sim", "stop_sim", "wait_for_port", "resolve_sim_exe"]


def resolve_sim_exe(app_path: str) -> str:
    """接受 .app bundle 或裸可执行文件,返回可直接 exec 的二进制路径。"""
    if os.path.isdir(app_path):
        for name in ("donkey_sim", "DonkeySim", "donkey-sim"):
            cand = os.path.join(app_path, "Contents", "MacOS", name)
            if os.path.exists(cand):
                return cand
        raise FileNotFoundError(f"{app_path} 是目录但未找到 Contents/MacOS 下的 sim 二进制")
    return app_path


def wait_for_port(port: int, timeout_s: float, host: str = "127.0.0.1") -> bool:
    """轮询 TCP 端口可连接;超时 False。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def launch_sim(
    app_path: str,
    port: int = 9091,
    host: str = "127.0.0.1",
    headless: bool = False,
    keep_graphics: bool = False,
    log_path: Optional[str] = None,
    wait_s: float = 60.0,
    extra_args: Optional[list] = None,
) -> subprocess.Popen:
    """拉起一个 sim 实例并等到端口就绪(超时抛 TimeoutError,不残留进程)。

    **端口被占即拒启**(2026-11-02 教训):异常退出留下的孤儿 sim 会占住
    端口,新实例起不来,客户端却连上僵尸——后续任何按端口清理都会跨进程
    误伤。先探端口,被占则报错并指出占用 pid,由调用方决策。

    **sdsim 构建事实(2026-11-02 lsof LISTEN 实测)**:单个 sim 实例同时
    监听 ``--port N`` 与 ``N+1`` 两个端口(9091+9092)。多实例部署必须
    **隔开 ≥2 个端口**(如 9091/9094);相邻端口撞上时 specific-vs-wildcard
    绑定可能侥幸共存(127.0.0.1:N vs *:N),内核按具体地址优先路由——
    脆弱且不可依赖,M2 前脚本已全部改为 +10 段隔离。
    """
    exe = resolve_sim_exe(app_path)
    if wait_for_port(port, 0.4):
        holders = subprocess.run(["lsof", "-ti", f"tcp:{port}"],
                                 capture_output=True, text=True, timeout=10).stdout.split()
        raise RuntimeError(
            f"端口 {port} 已被占用(pid={holders or '?'}),疑似孤儿 sim——"
            f"请先按端口精确清理(lsof -ti tcp:{port} | xargs kill),不要静默复用")
    args = [exe, "--port", str(port), "--host", host]
    if headless:
        args.append("-batchmode")
        if not keep_graphics:
            args.append("-nographics")
    if log_path:
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
        args += ["-logFile", log_path]
    if extra_args:
        args += list(extra_args)
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_for_port(port, wait_s):
            raise TimeoutError(f"sim {exe} 在 {wait_s:.0f}s 内未监听 :{port}")
    except Exception:
        stop_sim(proc=proc)
        raise
    return proc


def _is_sim_pid(pid: int) -> bool:
    """该 pid 是否为 sim 二进制进程。

    lsof 按端口会匹配到持有连接的客户端 socket——python 自己——必须过滤,
    否则 stop_sim 的端口释放循环(在 sim 收到 SIGTERM 但端口仍在接受的
    窗口期触发)会把自己杀掉。实测症状:脚本莫名 exit 143(2026-11-02)。
    """
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "comm="],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (subprocess.SubprocessError, ValueError):
        return False
    base = os.path.basename(out).lower()
    return "donkey_sim" in base or "donkeysim" in base


def _pids_listening_on(port: int) -> list:
    try:
        out = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True, timeout=10).stdout
        pids = []
        for x in out.split():
            if x.strip().isdigit():
                pid = int(x)
                if pid != os.getpid() and _is_sim_pid(pid):
                    pids.append(pid)
        return pids
    except (subprocess.SubprocessError, ValueError):
        return []


def _kill_pids(pids, timeout_s: float = 6.0) -> None:
    import signal as _sig
    for pid in pids:
        try:
            os.kill(pid, _sig.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        alive = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except ProcessLookupError:
                pass
        if not alive:
            return
        time.sleep(0.2)
    for pid in alive:  # SIGKILL 兜底
        try:
            os.kill(pid, _sig.SIGKILL)
        except ProcessLookupError:
            pass


def stop_sim(proc: Optional[subprocess.Popen] = None, port: Optional[int] = None,
             timeout_s: float = 6.0) -> dict:
    """按红线精确停 sim。两条互斥路径,**绝不交叉兜底**:

    a) ``proc`` 给定(自家子进程):精确 pid 的 SIGTERM→wait→SIGKILL。进程
       必死 ⇒ 其端口随之释放,**不做任何按端口扫描**。
    b) ``proc`` 为 None(外部手动启动的 sim):必须显式 ``port``,只杀该
       端口上 LISTEN 且命令名为 sim 的进程。

    2026-11-02 红线事故复盘:旧实现 ``port`` 默认 9091 且 a) 路径结束后仍跑
    「端口确认释放」兜底——eval-gate 停自己的 9095 sim 时,不传 port 走默认
    9091,兜底循环把 **训练 sim** 杀了(命令名校验也通过,它就是 sim)。
    这正是 sdsandbox「两次误杀训练」的教训原型;现在 a) 路径与端口彻底解耦,
    b) 路径强制显式端口,默认值已移除。
    """
    record = {"mode": None, "pids": [], "port": port}
    if proc is not None:
        record["mode"] = "child_pid"
        record["pids"] = [proc.pid]
        try:
            proc.terminate()  # SIGTERM
        except ProcessLookupError:
            return record
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()  # SIGKILL 兜底
                proc.wait(timeout=3.0)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
        return record  # 子进程路径到此为止:不按端口兜底

    if port is None:
        raise ValueError(
            "stop_sim: 无 proc 时必须显式传 port(禁止默认端口兜底——"
            "默认 9091 曾误杀训练 sim,见函数 docstring)")
    pids = _pids_listening_on(port)
    record["mode"] = "by_port"
    record["pids"] = pids
    if pids:
        _kill_pids(pids, timeout_s)
        # 仅针对本端口确认释放(同一组 pid 的 SIGKILL 兜底,不扫其他端口)
        deadline = time.time() + 5.0
        while time.time() < deadline and _pids_listening_on(port):
            _kill_pids(_pids_listening_on(port), 3.0)
    return record
