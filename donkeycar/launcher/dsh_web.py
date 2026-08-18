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
- 但 dsh-client-connection 还有一层 ``PRIVILEGED_METHODS``（settings.**/
  credentials.**/llm.discoverModels 等特权方法）硬编码空信任表=仅回环，
  ``--trusted-host`` 对其无效（rc.6/rc.7 同款设计，2026-08-18 确认）。
  局域网浏览器打开设置页/模型选择会 403（"正在加载"、"加载提供方目录
  失败"）。修法见 ``_patch_privileged_methods``：启动前对安装文件做
  幂等自愈补丁，把特权方法的信任表放宽为 trustedHosts。
- 局域网浏览器处于非安全上下文（``http://<局域网 IP>``，非 localhost），
  ``crypto.randomUUID`` 不可用；dsh-client-connection 铸造 RPC id 时抛
  ``TypeError``，连接永远到不了 connected、DSH 停在"选择工作区"不会
  自动进入 Projects。修法见 ``_patch_client_uuid_polyfill``：启动前对
  client.js 顶部插入 getRandomValues 版 UUID 兜底（幂等自愈）。
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

# dsh-client-connection 的 /api 栅栏源码（lib/index.js）里，特权方法
# （PRIVILEGED_METHODS：settings.**/credentials.**/llm.discoverModels 等）
# 用空信任表判定，只放行回环 Host——--trusted-host 对其无效。局域网
# 浏览器因此打不开设置页/模型选择（403）。补丁把这一处的信任表放宽
# 为同函数内已有的 trustedHosts（apply() 的局部变量，闭包可见），
# 让 --trusted-host 声明的局域网 authority 同样可用：
_PATCH_FENCE_OLD = ("PRIVILEGED_METHODS.has(method) && "
                    "!isTrustedApiRequest(request, [])")
_PATCH_FENCE_NEW = ("PRIVILEGED_METHODS.has(method) && "
                    "!isTrustedApiRequest(request, trustedHosts)")

# dsh-client-connection/lib/client.js 顶部（factory 作用域内）CommonJS 桩
# 的两行锚点。非安全上下文（局域网 http://，非 localhost）里
# ``crypto.randomUUID`` 为 undefined，mintRpcId() 抛 TypeError 导致连接
# 永不就绪、DSH 停在"选择工作区"。补丁在两行之间插入 getRandomValues
# 版 RFC4122 v4 UUID 兜底（幂等自愈，见 _patch_client_uuid_polyfill）。
_PATCH_UUID_OLD = (
    "\t\tObject.defineProperty(exports, Symbol.toStringTag, "
    "{ value: \"Module\" });\n"
    "\t\t//#region lib/types/client/connection.js\n"
)
_PATCH_UUID_NEW = (
    "\t\tObject.defineProperty(exports, Symbol.toStringTag, "
    "{ value: \"Module\" });\n"
    "\n"
    "\t\t// [donkey-launcher] crypto.randomUUID is unavailable in non-secure\n"
    "\t\t// contexts (LAN http://, not localhost); polyfill via getRandomValues.\n"
    "\t\tif (globalThis.crypto && typeof globalThis.crypto.randomUUID !== \"function\") {\n"
    "\t\t\tglobalThis.crypto.randomUUID = function randomUUID() {\n"
    "\t\t\t\tconst b = globalThis.crypto.getRandomValues(new Uint8Array(16));\n"
    "\t\t\t\tb[6] = (b[6] & 0x0f) | 0x40;\n"
    "\t\t\t\tb[8] = (b[8] & 0x3f) | 0x80;\n"
    "\t\t\t\tconst h = Array.from(b, (x) => x.toString(16).padStart(2, \"0\"));\n"
    "\t\t\t\treturn [h.slice(0, 4).join(\"\"), h.slice(4, 6).join(\"\"),\n"
    "\t\t\t\t\th.slice(6, 8).join(\"\"), h.slice(8, 10).join(\"\"),\n"
    "\t\t\t\t\th.slice(10).join(\"\")].join(\"-\");\n"
    "\t\t\t};\n"
    "\t\t}\n"
    "\t\t//#region lib/types/client/connection.js\n"
)

# 补丁锁：launcher 多线程，防并发重打
_PATCH_LOCK = threading.Lock()

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


def _connection_index_path(binary: str):
    """从 dsh 可执行文件定位 dsh-client-connection/lib/index.js。

    dsh bin 是指向 ``<dsh 包>/lib/bin.js`` 的符号链接（含相对链接），
    realpath 后取包根，再走 npm 安装布局
    ``<dsh 包>/node_modules/@deepseek-ai/dsh-client-connection/``；
    找不到（如 rc.7 起的 pnpm 布局）返回 None，调用方跳过补丁。
    """
    try:
        bin_real = Path(os.path.realpath(binary))
        pkg_root = bin_real.parent.parent  # <pkg>/lib/bin.js -> <pkg>
        candidate = (pkg_root / "node_modules" / "@deepseek-ai"
                     / "dsh-client-connection" / "lib" / "index.js")
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def _connection_client_path(binary: str):
    """从 dsh 可执行文件定位 dsh-client-connection/lib/client.js。

    与 ``_connection_index_path`` 同布局，只是目标是 client.js（UUID
    补丁要改的文件）。找不到（如 rc.7 起的 pnpm 布局）返回 None，调用方
    跳过补丁。
    """
    try:
        bin_real = Path(os.path.realpath(binary))
        pkg_root = bin_real.parent.parent  # <pkg>/lib/bin.js -> <pkg>
        candidate = (pkg_root / "node_modules" / "@deepseek-ai"
                     / "dsh-client-connection" / "lib" / "client.js")
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def _patch_privileged_methods(binary: str):
    """对 dsh 安装里的 /api 特权方法栅栏做幂等自愈补丁（issue #164）。

    特权方法（settings/credentials/llm.discoverModels）被上游硬编码为
    仅回环可访问，局域网浏览器打开设置页会 403。这里把栅栏源码中特权
    方法的空信任表 ``[]`` 替换为 ``trustedHosts``，与普通方法一致地
    接受 ``--trusted-host`` 声明的 authority。

    幂等：已打过的文件（新代码段在）直接返回；源码升级后未命中旧代码
    段也跳过（dsh 升级会还原文件，下次启动若代码段仍在会自动重打）。
    任何失败只告警不抛——dsh 本身仍可启动，仅设置页在局域网不可用。
    """
    target = _connection_index_path(binary)
    if target is None:
        logger.warning("dsh 栅栏补丁：未找到 dsh-client-connection，跳过")
        return
    try:
        with _PATCH_LOCK:
            text = target.read_text(encoding="utf-8")
            if _PATCH_FENCE_NEW in text:
                return  # 已打过（幂等）
            if _PATCH_FENCE_OLD not in text:
                logger.warning(
                    "dsh 栅栏补丁：目标代码段未命中（dsh 可能已升级改版），"
                    "跳过: %s", target)
                return
            tmp = target.with_name(target.name + ".donkey-patch.tmp")
            tmp.write_text(
                text.replace(_PATCH_FENCE_OLD, _PATCH_FENCE_NEW),
                encoding="utf-8")
            os.replace(tmp, target)
            logger.info("dsh 栅栏补丁：特权方法已放行 trusted-host 访问: %s",
                        target)
    except OSError as e:
        logger.warning(
            "dsh 栅栏补丁失败（dsh 仍可启动，局域网设置页可能 403）: %s", e)


def _patch_client_uuid_polyfill(binary: str):
    """对 dsh 安装里的 client.js 做 crypto.randomUUID 幂等自愈补丁（issue #164）。

    局域网浏览器（``http://<LAN IP>``）处于非安全上下文，
    ``crypto.randomUUID`` 为 undefined；dsh-client-connection 铸造 RPC id
    时抛 TypeError，连接永远到不了 connected、DSH 停在"选择工作区"。
    这里在 client.js 顶部 CommonJS 桩之后注入 getRandomValues 版
    RFC4122 v4 UUID 兜底。

    幂等/自愈语义与 ``_patch_privileged_methods`` 一致：已打过的跳过；
    源码升级未命中旧锚点也跳过；任何失败只告警不抛——dsh 仍可启动，仅
    局域网自动进入 Projects 可能失效。
    """
    target = _connection_client_path(binary)
    if target is None:
        logger.warning("dsh UUID 补丁：未找到 dsh-client-connection，跳过")
        return
    try:
        with _PATCH_LOCK:
            text = target.read_text(encoding="utf-8")
            if _PATCH_UUID_NEW in text:
                return  # 已打过（幂等）
            if _PATCH_UUID_OLD not in text:
                logger.warning(
                    "dsh UUID 补丁：目标代码段未命中（dsh 可能已升级改版），"
                    "跳过: %s", target)
                return
            tmp = target.with_name(target.name + ".donkey-patch.tmp")
            tmp.write_text(
                text.replace(_PATCH_UUID_OLD, _PATCH_UUID_NEW),
                encoding="utf-8")
            os.replace(tmp, target)
            logger.info("dsh UUID 补丁：已为 client.js 注入 randomUUID 兜底: %s",
                        target)
    except OSError as e:
        logger.warning(
            "dsh UUID 补丁失败（dsh 仍可启动，局域网自动进入 Projects 可能失效）: %s",
            e)


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

    # 冷启动前自愈补丁：放行特权方法的 trusted-host 访问（幂等，失败
    # 只影响局域网设置页，不影响 dsh 启动）
    _patch_privileged_methods(binary)
    # client.js 注入 crypto.randomUUID 兜底（幂等，失败只影响局域网自动
    # 进入 Projects，不影响 dsh 启动）
    _patch_client_uuid_polyfill(binary)

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
