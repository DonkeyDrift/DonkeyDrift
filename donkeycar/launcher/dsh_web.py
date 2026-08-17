#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""POST /api/launch/dsh 的实现：启动/复用 DeepSeek Harness（dsh）web。

dsh web 的局域网暴露（issue #164）有几处与 kimi web 不同的机制：

- dsh CLI 层面拒绝 ``--host 0.0.0.0``（安全理由），但 webserver 插件
  的配置 schema 接受 ``127.0.0.1 | 0.0.0.0``。因此用 ``--patch`` 覆盖
  ``webserver.host=0.0.0.0`` 让局域网浏览器可达；patch 里 ``port`` 不能
  省略（配置校验要求有值），用 ``!!js ctx.webStartup.port ?? 3080``
  表达式跟随 ``--port`` 参数。
- ``--port 0`` 由 OS 分配空闲端口，避免与默认 3080 冲突。
- ``/api`` 有浏览器信任栅栏：Host 非回环必须在 ``--trusted-host`` 里
  声明才放行（裸 host 匹配任意端口）。传入本机局域网 IP，局域网
  浏览器才能正常调用 API。
- 就绪 banner 一行：``dsh web: http://127.0.0.1:<port> (LAN: ...)``，
  抓第一个 URL（回环）后改写为局域网 IP（复用 kimi_web 的 _lan_url，
  issue #125 同款问题）。
- 复用：dsh 没有类似 kimi 的实例登记文件，只复用本模块此前拉起且
  仍存活（HTTP GET / 返回 200）的子进程。
"""

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# 复用 kimi_web 的通用机制（同包内私有工具，见各引用处注释）
from donkeycar.launcher.kimi_web import (
    _lan_ip,
    _lan_url,
    extract_web_url,
    strip_ansi,
)

logger = logging.getLogger(__name__)

# 整体超时（秒）：dsh web 冷启动实测数秒，留足余量；
# 复用路径毫秒级返回
DEFAULT_TIMEOUT_S = 60.0
# 等 dsh web 子进程 ready banner 的最长时间（秒）
SPAWN_TIMEOUT_S = 45.0
# 轮询间隔（秒）
_POLL_S = 0.2
# 复用探测（GET /）的超时（秒）
PROBE_TIMEOUT_S = 3.0

# webserver 补丁层：host 置 0.0.0.0（局域网可达），port 表达式跟随
# --port 参数（省略会让配置校验报 "port missing required value"）
_PATCH_YAML = (
    "- id: webserver\n"
    "  config:\n"
    "    host: 0.0.0.0\n"
    "    port: !!js ctx.webStartup.port ?? 3080\n"
)

# 本模块拉起的 dsh web 子进程登记：[{proc, host, port}]，保住引用不被
# GC，生命周期同 launcher（杀掉子进程即关掉对应 web 服务）
_SPAWNED = []


def _resolve_dsh_binary():
    """dsh 可执行文件路径；找不到返回 None。

    优先 PATH 查找；launcher 以 systemd 服务运行时 PATH 是干净环境，
    回退到当前 Python 解释器同目录（conda env bin，dsh 与 launcher
    同装在该 env 里）。
    """
    binary = shutil.which("dsh")
    if binary:
        return binary
    sibling = Path(sys.executable).parent / "dsh"
    if os.access(sibling, os.X_OK):
        return str(sibling)
    return None


def _write_patch_file():
    """把 webserver 补丁层写进临时目录，返回路径（幂等，内容固定）。"""
    path = Path(tempfile.gettempdir()) / "donkey-launcher-dsh-lan.yml"
    path.write_text(_PATCH_YAML, encoding="utf-8")
    return str(path)


def _probe_root(host: str, port: int, timeout=PROBE_TIMEOUT_S) -> bool:
    """GET / 返回 200 视为 web 服务仍存活。"""
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(
                f"http://{host}:{port}/", timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _live_spawned_url():
    """找本模块拉起且仍存活的 dsh web 实例，返回入口 URL；没有返回 None。"""
    for entry in list(_SPAWNED):
        proc = entry["proc"]
        if proc.poll() is not None:
            _SPAWNED.remove(entry)
            continue
        # dsh 固定绑 0.0.0.0，用回环探测，返回前改写为局域网 IP
        if _probe_root("127.0.0.1", entry["port"]):
            return _lan_url(f"http://127.0.0.1:{entry['port']}/")
        # 进程活着但端口探不通（僵死），清掉并走冷启动
        _SPAWNED.remove(entry)
    return None


def _spawn_and_capture(binary: str, cwd_str, lan_ip, deadline: float,
                       popen_fn=None):
    """拉起 ``dsh web``（0.0.0.0 + 随机端口 + 可选 trusted-host）并等
    ready banner 里的 URL。

    返回 ``(proc, url, None)`` 或 ``(None, None, 错误原因)``；
    失败路径一律杀掉子进程，不留孤儿。
    """
    popen_fn = popen_fn or subprocess.Popen
    cmd = [binary, "web",
           "--patch", _write_patch_file(),
           "--port", "0"]
    if lan_ip:
        # /api 信任栅栏：局域网 Host 必须显式声明才放行（裸 host 匹配
        # 任意端口，适配 --port 0 的随机端口）
        cmd += ["--trusted-host", lan_ip]
    try:
        proc = popen_fn(
            cmd,
            cwd=cwd_str,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as e:
        return None, None, f"无法启动 dsh web 子进程: {e}"

    buf = []
    lock = threading.Lock()

    def _drain():
        # 持续读空 stdout：既供 URL 捕获，也防管道写满阻塞 dsh；
        # 抓到 URL 后线程继续挂着排水（dsh web 就绪后基本无输出）
        try:
            for line in proc.stdout:
                with lock:
                    buf.append(line)
        except ValueError:
            pass  # 管道已关闭

    threading.Thread(target=_drain, daemon=True).start()

    def _text() -> str:
        with lock:
            return strip_ansi("".join(buf))

    def _tail(plain: str, n: int = 3) -> str:
        lines = [ln.strip() for ln in plain.splitlines() if ln.strip()]
        return " | ".join(lines[-n:]) if lines else "(无输出)"

    wait_deadline = min(deadline, time.monotonic() + SPAWN_TIMEOUT_S)
    error = None
    while True:
        plain = _text()
        url = extract_web_url(plain)
        if url:
            return proc, url, None
        if proc.poll() is not None:
            # 进程退出后管道里可能还有未读尽的残余输出，稍等补读再判定
            time.sleep(0.3)
            plain = _text()
            url = extract_web_url(plain)
            if url:
                return proc, url, None
            error = (f"dsh web 进程提前退出（码 {proc.returncode}）；"
                     "现场: " + _tail(plain))
            break
        if time.monotonic() >= wait_deadline:
            error = (f"等待 dsh web 就绪超时（{int(SPAWN_TIMEOUT_S)}s）；"
                     "现场: " + _tail(plain))
            break
        time.sleep(_POLL_S)

    try:
        proc.kill()
    except OSError:
        pass
    return None, None, error


def launch_dsh_web(cwd=None, timeout_s=DEFAULT_TIMEOUT_S, *,
                   resolve_binary_fn=None, lan_ip_fn=None, popen_fn=None):
    """打开 DeepSeek Harness web：优先复用存活实例，否则拉起 ``dsh web``。

    Args:
        cwd: dsh 运行目录（绝对路径）；None 表示上位机用户主目录。
            目录不存在直接报错，绝不回退到其它目录。
        timeout_s: 整体超时（秒），默认 60。
        resolve_binary_fn / lan_ip_fn / popen_fn: 测试钩子，默认
            ``_resolve_dsh_binary`` / ``_lan_ip`` / ``subprocess.Popen``。

    Returns:
        成功 {"status": "ok", "url": <入口 URL>}；
        失败 {"status": "error", "error": <原因>}。
        URL 的回环 host 已改写为本机局域网 IP（远程浏览器可达）；
        成功拉起的子进程保持存活（杀它即关 web 服务）；失败路径杀净。
    """
    resolve_binary_fn = resolve_binary_fn or _resolve_dsh_binary
    lan_ip_fn = lan_ip_fn or _lan_ip

    cwd_str = None
    if cwd is not None:
        cwd_path = Path(cwd).expanduser()
        if not cwd_path.is_dir():
            return {
                "status": "error",
                "error": f"cwd 目录不存在或不是目录: {cwd}（不会回退到其它目录）",
            }
        cwd_str = str(cwd_path)

    # 快路径：本模块拉起的实例仍在跑
    url = _live_spawned_url()
    if url:
        logger.info("复用已运行的 dsh web 实例: %s", url)
        return {"status": "ok", "url": url}

    binary = resolve_binary_fn()
    if not binary:
        return {
            "status": "error",
            "error": "未找到 dsh 可执行文件（PATH 与当前 Python 环境的 "
                     "bin 目录均无），请确认 DeepSeek Harness 已安装",
        }

    lan_ip = lan_ip_fn()
    deadline = time.monotonic() + timeout_s
    proc, url, error = _spawn_and_capture(
        binary, cwd_str, lan_ip, deadline, popen_fn=popen_fn)
    if url:
        _SPAWNED.append({"proc": proc, "port": _url_port(url)})
        url = _lan_url(url)
        logger.info("dsh web 已启动: pid=%s url=%s", proc.pid, url)
        return {"status": "ok", "url": url}

    logger.warning("启动 dsh web 失败: %s", error)
    return {"status": "error", "error": error}


def _url_port(url: str):
    """从 URL 提取端口；解析失败返回 None（复用探测会跳过该条目）。"""
    from urllib.parse import urlsplit
    try:
        return urlsplit(url).port
    except ValueError:
        return None
