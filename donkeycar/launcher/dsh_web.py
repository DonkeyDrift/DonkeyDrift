#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""POST /api/launch/dsh 的实现：启动/复用 DeepSeek Harness（dsh）web。

dsh web 的局域网暴露（issue #164）有几处与 kimi web 不同的机制：

- dsh CLI 层面拒绝 ``--host 0.0.0.0``（安全理由），但 webserver 插件
  的配置 schema 接受 ``127.0.0.1 | 0.0.0.0``。因此用 ``--patch`` 覆盖
  ``webserver.host=0.0.0.0`` 让局域网浏览器可达；patch 里 ``port`` 不能
  省略（配置校验要求有值），用 ``!!js ctx.webStartup.port ?? 3080``
  表达式跟随 ``--port`` 参数。
- ``--port`` 绑固定专属端口 ``DSH_WEB_PORT``（58641；KCW 占 58640）：
  浏览器把 DSH 的会话手动排序（``dsh.workspace.view.v5`` 的
  sessionOrderByAccount，即用户感知的「置顶」）、当前会话
  （``dsh.sessions.current``）、草稿（``dsh.conversation.chat``）等
  偏好存 localStorage、按 origin（协议+host+端口）隔离；``--port 0``
  随机端口会让每次冷启动 origin 漂移、偏好全丢（issue #168 同款问题，
  KCW 已用固定端口根治，见 ``kimi_web.KIMI_WEB_PORT``）。
- ``/api`` 有浏览器信任栅栏：Host 非回环必须在 ``--trusted-host`` 里
  声明才放行（裸 host 匹配任意端口）。入口 URL 的 host 会被改写为
  mDNS 主机名优先（``TONY007.local``，见 ``_lan_url``），所以
  ``--trusted-host`` 同时传入本机局域网 IP 与 mDNS 主机名，否则浏览器
  以 mDNS 名访问时会被 403 拦下（issue #164）。
- 但 dsh-client-connection 还有一层 ``PRIVILEGED_METHODS``（settings.**/
  credentials.**/llm.discoverModels 等特权方法）硬编码空信任表=仅回环，
  ``--trusted-host`` 对其无效（rc.6/rc.7 同款设计，2026-08-18 确认）。
  局域网浏览器打开设置页/模型选择会 403（"正在加载"、"加载提供方目录
  失败"）。修法见 ``_patch_privileged_methods``：启动前对安装文件做
  幂等自愈补丁，把特权方法的信任表放宽为 trustedHosts。
- 仅放宽服务端还不够：dsh-client-ui-settings 前端的共享设置镜像与
  命名空间作用域按 ``isLoopback ? "host" : "memory"`` 选模式（上游
  假定 settings RPC 仅回环可达），局域网浏览器落 "memory" 后镜像恒
  unavailable、永不读 settings.describe，设置页/选模型仍报"加载提供方
  目录失败: settings are unavailable in this browser"（2026-09-06 rc.2
  重装后实测）。修法见 ``_patch_settings_mirror_gate``：把前端三目条件
  幂等强制为 host（镜像与作用域两处一并替换）。
- 局域网浏览器处于非安全上下文（``http://<局域网 IP>``，非 localhost），
  ``crypto.randomUUID`` 不可用；dsh-client-connection 铸造 RPC id 时抛
  ``TypeError``，连接永远到不了 connected、DSH 停在"选择工作区"不会
  自动进入 Projects。修法见 ``_patch_client_uuid_polyfill``：启动前对
  client.js 顶部插入 getRandomValues 版 UUID 兜底（幂等自愈）。
- web-all 聚合 client 里编译了 remote-web-ui 的通道逻辑：该插件卸载后
  聚合 client 仍会在读配对策略失败（/api/pair/status 404）时兜底假定
  "需要配对"，给非回环页面自装 fetch/WebSocket 劫持，把 /api 请求改写
  到已不存在的 /remote/* 通道——局域网浏览器全部 API 报 HTTP 405。
  修法见 ``_patch_remote_channel_client``：启动前对聚合 client.js 的
  remoteChannelRequired 强制恒 false（幂等自愈；目标在 web profile 的
  node_modules，非 dsh 安装树）。
- 就绪 banner 一行：``dsh web: http://127.0.0.1:<port>/?token=…``，
  抓第一个 URL（回环）后改写为局域网 IP（复用 kimi_web 的 _lan_url，
  issue #125 同款问题）。
- 新版 dsh（≥0.1.2-rc.1，2026-09-08 插件安装会话自动升级后）根页面有
  per-process token 鉴权：无 token ``GET /`` 返回 401（响应体是 dsh 专属
  文案 ``dsh web authentication required``），入口 URL 必须带启动 banner
  里那次性的 ``?token=``；有效 token 的 ``GET /`` 回 303 重定向并铸造
  会话 cookie（探测必须禁跳转看首响应，跟跳转会丢 cookie 二次 401）。
  旧版无此鉴权（``GET /`` 直接 200 + ``__DSH_BOOT__``），两时代并存。
- 复用三通道（dsh 没有类似 kimi 的实例登记目录）：① ``_SPAWNED``
  内存登记——本模块此前拉起且仍存活的子进程（``_probe_root`` 兼容
  200/401 两时代），复用登记时抓到的带 token 入口；② 固定端口特征探测
  ``_probe_dsh_fixed_port``——launcher 重启后 ① 即丢：旧版看 200 +
  ``__DSH_BOOT__``；新版看 401 专属文案 + ``~/.donkeycar/dsh_web_entry.json``
  登记的带 token 入口（``_probe_token_entry`` 验证 token 仍有效）；③
  冷启动失败后再探一次 ② 兜底（端口可能被登记滞后的存活实例占用）。
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

# 复用 kimi_web 的通用机制（同包内私有工具，见各引用处注释）
from donkeycar.launcher.kimi_web import (
    _ANY_URL_RE,
    _lan_ip,
    _mdns_hostname,
    _lan_url,
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
# 冷启动绑定的固定专属端口（origin 稳定，对齐 kimi_web 的 KIMI_WEB_PORT
# 做法）：浏览器 localStorage 按 origin（协议+host+端口）隔离，DSH 的
# 会话手动排序（dsh.workspace.view.v5 的 sessionOrderByAccount，即用户
# 感知的「置顶」）、当前会话（dsh.sessions.current）、草稿
# （dsh.conversation.chat）都存里面；--port 0 随机端口会让每次冷启动
# origin 漂移、偏好全丢。58640 是 KCW 专属端口，58641 给 dsh web 专属
DSH_WEB_PORT = 58641

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
#
# 同时在这块补丁里注入"新会话"清理逻辑：URL 带 ``?dsh_new_session=1``
# 时清除 ``localStorage["dsh.sessions.current"]``，使 DSH 前端不加载上次
# 会话、直接进入"New Session"空白视图（用户要求"点击之后直接重新开一个
# 新的 Session"，DSH 没有 REST API 创建会话，只能在前端侧清除当前会话
# 指针）。补丁运行时机：``dsh-client-connection`` 的 ``immediately:true``
# 插件加载阶段，早于 DSH 应用读取 localStorage。
_PATCH_UUID_OLD = (
    "\t\tObject.defineProperty(exports, Symbol.toStringTag, "
    "{ value: \"Module\" });\n"
    "\t\t//#region lib/types/client/connection.js\n"
)
# 旧版补丁（仅 UUID，无新会话清理）：用于迁移检测——已打过旧版的文件
# 不会被新版 idempotency 检测到（文本不同），需要单独识别后替换升级。
_PATCH_UUID_NEW_LEGACY = (
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
    "\t\t// [donkey-launcher] ?dsh_new_session=1: clear current session for fresh start\n"
    "\t\tif (globalThis.location && new URLSearchParams(globalThis.location.search).has(\"dsh_new_session\")) {\n"
    "\t\t\ttry { localStorage.removeItem(\"dsh.sessions.current\"); } catch (e) {}\n"
    "\t\t}\n"
    "\t\t//#region lib/types/client/connection.js\n"
)

# dsh-client-ui-settings/lib/client.js 的前端回环自锁：共享设置镜像
# （SettingsDescribeMirror）与命名空间作用域（SettingsScopeController）按
# ``connection.isLoopback ? "host" : "memory"`` 选持久化模式——上游这么做
# 是因为上游 settings RPC 仅回环可达；但 _patch_privileged_methods 已把
# 服务端栅栏对 --trusted-host 放行，局域网浏览器却被前端这个门锁在
# "memory"：mirror 初始即 unavailable、ensure() 空转、永不发起
# settings.describe，设置页/选模型报"加载提供方目录失败: settings are
# unavailable in this browser"（dsh-client-ui-settings-models 的 load()
# 在 mirrored.view 为 undefined 时抛错）。补丁把三目条件强制为 host
# （保留原结构、内联注释作幂等标记），文件里两处（mirror + scope）一次
# 替换完成。回环行为不变；非 trusted-host 仍被服务端栅栏 403，安全边界
# 不扩大。
_PATCH_GATE_OLD = 'connection.isLoopback ? "host" : "memory"'
_PATCH_GATE_NEW = ('(true) /* [donkey-launcher] trusted-host browsers reach '
                   'settings RPCs via the fence patch */ ? "host" : "memory"')

# web-all 聚合 client.js（web profile 的 node_modules 里，非 dsh 安装树）的
# remote-channel 判定：remote-web-ui 卸载后，其编译进聚合 client 的通道
# 逻辑仍会在"读配对策略失败"（/api/pair/status 404）时兜底假定"需要
# 配对"，主动给页面装 fetch/WebSocket 劫持，把所有 /api 请求改写到已
# 不存在的 /remote/* 通道——局域网浏览器全部 API 报 HTTP 405（2026-09-08
# 实测：/api/llm/listProviders 直连 200、/remote/ 前缀 405）。补丁把
# remoteChannelRequired 强制恒 false：永不走 /remote 通道，API 全部直连
# （安全边界回到 trusted-host 栅栏，与卸载该插件的决定一致）。
_PATCH_REMOTE_CHANNEL_OLD = (
    "\t\t\tif (snapshot.status === \"ready\") return "
    "(snapshot.value?.enabled ?? true) && "
    "(snapshot.value?.requirePairingForLan ?? true);\n"
    "\t\t\treturn hostPairingPolicy !== false;"
)
_PATCH_REMOTE_CHANNEL_NEW = (
    "\t\t\t/* [donkey-launcher] remote-web-ui host uninstalled: "
    "/api/pair/status 404 must not default to \"pairing required\" — "
    "never route /api through the gated /remote channel */\n"
    "\t\t\treturn false;"
)

# 补丁锁：launcher 多线程，防并发重打
_PATCH_LOCK = threading.Lock()

# 本模块拉起的 dsh web 子进程登记：[{proc, port}]，保住引用不被 GC，
# 生命周期同 launcher（杀掉这些子进程即关掉对应 web 服务）。只是
# launcher 进程内存、重启即丢——跨重启的复用靠 _probe_dsh_fixed_port
# 固定端口特征探测；那样复用到的实例不是本进程拉起的，没有 proc 可
# 登记（本 launcher 不掌握其生命周期）
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


def _ui_settings_client_path(binary: str):
    """从 dsh 可执行文件定位 dsh-client-ui-settings/lib/client.js。

    与 ``_connection_index_path`` 同布局，只是目标是 dsh-client-ui-settings
    包（设置镜像回环门补丁要改的文件）。找不到（如 pnpm 布局）返回
    None，调用方跳过补丁。
    """
    try:
        bin_real = Path(os.path.realpath(binary))
        pkg_root = bin_real.parent.parent  # <pkg>/lib/bin.js -> <pkg>
        candidate = (pkg_root / "node_modules" / "@deepseek-ai"
                     / "dsh-client-ui-settings" / "lib" / "client.js")
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

    同时注入"新会话"清理逻辑：URL 带 ``?dsh_new_session=1`` 时清除
    ``localStorage["dsh.sessions.current"]``，使 DSH 前端不加载上次会话、
    直接进入"New Session"空白视图。

    幂等/自愈语义与 ``_patch_privileged_methods`` 一致：已打过的跳过；
    旧版补丁（仅 UUID，无新会话清理）自动升级为新版；源码升级未命中旧
    锚点也跳过；任何失败只告警不抛——dsh 仍可启动，仅局域网自动进入
    Projects 可能失效。
    """
    target = _connection_client_path(binary)
    if target is None:
        logger.warning("dsh UUID 补丁：未找到 dsh-client-connection，跳过")
        return
    try:
        with _PATCH_LOCK:
            text = target.read_text(encoding="utf-8")
            if _PATCH_UUID_NEW in text:
                return  # 已打过新版（幂等）
            # 旧版补丁迁移：仅有 UUID polyfill、没有新会话清理逻辑
            if _PATCH_UUID_NEW_LEGACY in text:
                tmp = target.with_name(target.name + ".donkey-patch.tmp")
                tmp.write_text(
                    text.replace(_PATCH_UUID_NEW_LEGACY, _PATCH_UUID_NEW),
                    encoding="utf-8")
                os.replace(tmp, target)
                logger.info("dsh UUID 补丁：旧版升级为新版（+新会话清理）: %s",
                            target)
                return
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
            logger.info("dsh UUID 补丁：已为 client.js 注入 randomUUID + 新会话清理: %s",
                        target)
    except OSError as e:
        logger.warning(
            "dsh UUID 补丁失败（dsh 仍可启动，局域网自动进入 Projects 可能失效）: %s",
            e)


def _patch_settings_mirror_gate(binary: str):
    """对 dsh 安装里的设置镜像回环门做幂等自愈补丁（issue #164 后续）。

    dsh-client-ui-settings 前端的共享设置镜像（SettingsDescribeMirror）与
    命名空间作用域（SettingsScopeController）按 ``isLoopback ? "host" :
    "memory"`` 选模式：局域网浏览器落到 "memory" 后镜像恒 unavailable、
    永不发起 settings.describe，设置页/选模型报 "加载提供方目录失败:
    settings are unavailable in this browser"。服务端栅栏补丁
    （``_patch_privileged_methods``）已把 settings.* 对 --trusted-host
    放行，这里把前端三目条件强制为 "host"（文件内 mirror 与 scope 两处
    一并替换），让局域网浏览器真正用上服务端已放行的 RPC。

    幂等/自愈语义与 ``_patch_privileged_methods`` 一致：已打过（新代码段
    在）跳过；源码升级未命中旧片段也跳过；任何失败只告警不抛——dsh 仍
    可启动，仅局域网设置页/模型选择不可用。
    """
    target = _ui_settings_client_path(binary)
    if target is None:
        logger.warning("dsh 设置镜像门补丁：未找到 dsh-client-ui-settings，跳过")
        return
    try:
        with _PATCH_LOCK:
            text = target.read_text(encoding="utf-8")
            if _PATCH_GATE_NEW in text:
                return  # 已打过（幂等）
            if _PATCH_GATE_OLD not in text:
                logger.warning(
                    "dsh 设置镜像门补丁：目标代码段未命中（dsh 可能已升级改版），"
                    "跳过: %s", target)
                return
            tmp = target.with_name(target.name + ".donkey-patch.tmp")
            tmp.write_text(
                text.replace(_PATCH_GATE_OLD, _PATCH_GATE_NEW),
                encoding="utf-8")
            os.replace(tmp, target)
            logger.info("dsh 设置镜像门补丁：局域网镜像/作用域已切 host 模式: %s",
                        target)
    except OSError as e:
        logger.warning(
            "dsh 设置镜像门补丁失败（dsh 仍可启动，局域网设置页可能不可用）: %s",
            e)


def _web_all_client_path(profile_dir=None):
    """定位 web profile 里 @linxin666/dsh-web-all 的聚合 client.js。

    与其它三个补丁不同，目标不在 dsh 安装树里，而在 dsh 的 profile
    目录（``~/.dsh/profiles/<profile>/node_modules``）。profile 跟随
    ``DSH_PROFILE`` 环境变量（与 remote-web-ui 自己的默认一致），缺省
    ``web``。找不到（聚合包未安装）返回 None，调用方跳过补丁。
    """
    if profile_dir is None:
        profile = os.environ.get("DSH_PROFILE", "web")
        profile_dir = Path.home() / ".dsh" / "profiles" / profile
    candidate = (Path(profile_dir) / "node_modules" / "@linxin666"
                 / "dsh-web-all" / "lib" / "client.js")
    return candidate if candidate.is_file() else None


def _patch_remote_channel_client(profile_dir=None):
    """对 web-all 聚合 client.js 的 remote-channel 判定做幂等自愈补丁。

    remote-web-ui 卸载后（见 cordis.patch.yml 的 disabled 覆盖行），其
    编译进聚合 client 的通道逻辑仍会在非回环页面上自装 fetch/WebSocket
    劫持（读 /api/pair/status 拿 404 即兜底"需要配对"），把 /api 请求
    改写到已不存在的 /remote/* 通道，局域网浏览器全部 API 报 HTTP 405。
    补丁把 remoteChannelRequired 强制恒 false——API 全部直连。

    幂等/自愈语义与 ``_patch_settings_mirror_gate`` 一致：已打过（新代码
    段在，含手工热修的同款标记）跳过；聚合包升级后未命中旧代码段也跳过
    （下次启动若代码段仍在会自动重打）；任何失败只告警不抛——dsh 仍可
    启动，仅局域网浏览器可能复现 405。
    """
    target = _web_all_client_path(profile_dir)
    if target is None:
        logger.warning("dsh remote-channel 补丁：未找到 web-all 聚合 client，跳过")
        return
    try:
        with _PATCH_LOCK:
            text = target.read_text(encoding="utf-8")
            if _PATCH_REMOTE_CHANNEL_NEW in text:
                return  # 已打过（幂等，含手工热修的同款标记）
            if _PATCH_REMOTE_CHANNEL_OLD not in text:
                logger.warning(
                    "dsh remote-channel 补丁：目标代码段未命中（web-all 可能已"
                    "升级改版），跳过: %s", target)
                return
            tmp = target.with_name(target.name + ".donkey-patch.tmp")
            tmp.write_text(
                text.replace(_PATCH_REMOTE_CHANNEL_OLD,
                             _PATCH_REMOTE_CHANNEL_NEW),
                encoding="utf-8")
            os.replace(tmp, target)
            logger.info("dsh remote-channel 补丁：remoteChannelRequired 已强制"
                        "恒 false（API 直连，不走 /remote 通道）: %s", target)
    except OSError as e:
        logger.warning(
            "dsh remote-channel 补丁失败（dsh 仍可启动，局域网可能复现 405）: %s",
            e)


def _probe_root(host: str, port: int, timeout=PROBE_TIMEOUT_S) -> bool:
    """GET / 返回 200（旧版 dsh）或 401（新版 token 门）视为存活。

    新版 dsh（≥0.1.2-rc.1）根页面有 per-process token 鉴权，无 token 的
    GET / 返回 401——仍是 dsh web 在应答。探测目标端口是 dsh 专属固定
    端口或本模块自己拉起的子进程，401 不会与"其它服务占用"混淆。
    """
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(
                f"http://{host}:{port}/", timeout=timeout) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        return e.code == 401
    except (urllib.error.URLError, OSError):
        return False


def _entry_state_path() -> Path:
    """新版 dsh 入口登记文件路径（跨 launcher 重启复用的 token 来源）。"""
    return Path.home() / ".donkeycar" / "dsh_web_entry.json"


def _write_entry_state(url: str, port, pid) -> None:
    """把带 token 的入口 URL 原子落盘，供 launcher 重启后复用（见
    ``_probe_dsh_fixed_port``）。写失败只告警——本次启动已成功，仅影响
    下次 launcher 重启后的复用。"""
    path = _entry_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(
            {"url": url, "port": port, "pid": pid}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        logger.warning("dsh 入口登记写入失败（不影响本次入口）: %s", e)


def _read_entry_state():
    """读入口登记；缺失/坏 JSON/非对象一律返回 None（容忍升级残留）。"""
    try:
        data = json.loads(_entry_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _probe_token_entry(url: str, timeout=PROBE_TIMEOUT_S):
    """带 token 的入口探测：GET 首响应状态码；连接失败返回 None。

    必须禁用重定向：新版 dsh 对有效 token 的 GET / 回 303 到 ``/`` 并在
    响应里铸造会话 cookie，跟跳转的第二个请求没有 cookie 会 401，误判
    token 失效。因此用 http.client 直连取首响应：200（直出）或 303
    （铸造 cookie）都算 token 有效，401 算失效。
    """
    import http.client
    parts = urllib.parse.urlsplit(url)
    conn = None
    try:
        conn = http.client.HTTPConnection(
            parts.hostname, parts.port or 80, timeout=timeout)
        target = urllib.parse.urlunsplit(
            ("", "", parts.path or "/", parts.query, ""))
        conn.request("GET", target)
        resp = conn.getresponse()
        resp.read(65536)
        return resp.status
    except OSError:
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass


def _probe_dsh_fixed_port():
    """探测固定端口 ``DSH_WEB_PORT`` 上的存活 dsh web，命中返回入口 URL。

    跨 launcher 重启的复用通道：launcher 重启后 ``_SPAWNED`` 内存登记
    即丢，但此前拉起的 dsh web 可能还绑在固定端口上。两个时代两种判定：

    - 旧版（<0.1.2-rc.1）：GET / 返回 200 且响应体含 dsh 特征标记
      ``__DSH_BOOT__``（dsh web 根 HTML 里的 ``window.__DSH_BOOT__``），
      复用无鉴权裸入口（仅 200 可能是占用该端口的外部服务）。
    - 新版（≥0.1.2-rc.1）：无 token GET / 返回 401，响应体是 dsh 专属
      文案（无文案的 401 视为外部服务，不复用）。入口必须带 token——
      从 ``_entry_state_path`` 登记取上次启动 banner 抓到的 URL，改写为
      回环后用 ``_probe_token_entry`` 验证 token 仍有效（303/200），
      有效才复用（返回前 ``_lan_url`` 改写为当前局域网入口，token
      query 保留）；登记缺失/端口不符/token 失效一律返回 None 走冷启动。
    """
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{DSH_WEB_PORT}/",
                timeout=PROBE_TIMEOUT_S) as resp:
            if resp.status != 200:
                return None
            # 特征标记在根 HTML 头部，读前几十 KB 足够判定
            body = resp.read(65536)
    except urllib.error.HTTPError as e:
        if e.code != 401:
            return None
        try:
            body = e.read(65536)
        except OSError:
            body = b""
        # 401 但无 dsh 专属文案：端口被外部服务占用，不能当 dsh
        if b"dsh web authentication required" not in body:
            return None
        # 新版 token 门：登记的带 token 入口验证后复用
        state = _read_entry_state()
        url = state.get("url") if state else None
        if not isinstance(url, str) or _url_port(url) != DSH_WEB_PORT:
            return None
        parts = urllib.parse.urlsplit(url)
        loopback = urllib.parse.urlunsplit(
            ("http", f"127.0.0.1:{DSH_WEB_PORT}",
             parts.path or "/", parts.query, ""))
        if _probe_token_entry(loopback) not in (200, 303):
            return None  # token 已随旧进程失效
        return _lan_url(loopback)
    except (urllib.error.URLError, OSError):
        return None
    if b"__DSH_BOOT__" not in body:
        return None
    return _lan_url(f"http://127.0.0.1:{DSH_WEB_PORT}/")


def _live_spawned_url():
    """找可复用的存活 dsh web 实例，返回入口 URL；没有返回 None。

    先查 ``_SPAWNED`` 内存登记（本模块拉起且仍存活的子进程）；无存活
    条目（如 launcher 已重启、登记丢失）再直接探测固定端口
    （``_probe_dsh_fixed_port``），覆盖实例仍存活但登记已丢的场景。
    登记条目带 ``url``（启动 banner 抓到的带 token 入口，新版 dsh）时
    复用它，否则退回无鉴权裸入口（旧版 dsh 的旧式登记）。
    """
    for entry in list(_SPAWNED):
        proc = entry["proc"]
        if proc.poll() is not None:
            _SPAWNED.remove(entry)
            continue
        # dsh 固定绑 0.0.0.0，用回环探测（_probe_root 兼容 200/401 两
        # 时代），返回前改写为局域网 IP（token query 保留）
        if _probe_root("127.0.0.1", entry["port"]):
            url = entry.get("url") or f"http://127.0.0.1:{entry['port']}/"
            return _lan_url(url)
        # 进程活着但端口探不通（僵死），清掉并走冷启动
        _SPAWNED.remove(entry)
    return _probe_dsh_fixed_port()


# dsh web 就绪 banner 的行前缀（剥 ANSI 后按行匹配）：banner 行是权威
# 入口来源（新版必带 ?token=）。URL 行尾可能粘着的句读（与 kimi_web 的
# _URL_TRAILING_PUNCT 同款语义）
_DSH_BANNER_PREFIX = "dsh web:"
_DSH_URL_TRAILING_PUNCT = ".,;:!?"


def _extract_dsh_web_url(plain: str):
    """从（已剥 ANSI 的）dsh 输出提取就绪 banner 行里的入口 URL。

    只认 ``dsh web:`` 开头的 banner 行、取该行第一个 URL：新版 banner
    必带 ``?token=``（0.1.2-rc.1 实测），是唯一可用入口；插件可能更早
    打印自己的 URL（如 dsh-remote-web-ui 的 "reachable on LAN at
    http://…" 行），通用提取（kimi_web.extract_web_url 的"文本里第一个
    URL"兜底）会先到先得抓丢 token、甚至把垂死进程打印的任意 URL 误判
    为启动成功。找不到 banner 行返回 None——ready banner 没出现就当未
    就绪（超时/退出路径各自报现场），绝不退回通用兜底。
    """
    for line in plain.splitlines():
        stripped = line.strip()
        if not stripped.startswith(_DSH_BANNER_PREFIX):
            continue
        m = _ANY_URL_RE.search(stripped)
        if m:
            return m.group(0).rstrip(_DSH_URL_TRAILING_PUNCT)
    return None


def _spawn_and_capture(binary: str, cwd_str, trusted_hosts, deadline: float,
                       popen_fn=None):
    """拉起 ``dsh web``（0.0.0.0 + 固定专属端口 ``DSH_WEB_PORT`` + 可选
    trusted-host）并等 ready banner 里的 URL。

    ``trusted_hosts`` 是 /api 信任栅栏要放行的 authority 列表（裸 host
    匹配任意端口），逐项追加到 ``--trusted-host``。返回
    ``(proc, url, None)`` 或 ``(None, None, 错误原因)``；失败路径一律
    杀掉子进程，不留孤儿。
    """
    popen_fn = popen_fn or subprocess.Popen
    cmd = [binary, "web",
           "--patch", _write_patch_file(),
           "--port", str(DSH_WEB_PORT)]
    for host in trusted_hosts:
        cmd += ["--trusted-host", host]
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
        url = _extract_dsh_web_url(plain)
        if url:
            return proc, url, None
        if proc.poll() is not None:
            # 进程退出后管道里可能还有未读尽的残余输出，稍等补读再判定
            time.sleep(0.3)
            plain = _text()
            url = _extract_dsh_web_url(plain)
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


def _mark_new_session(url: str) -> str:
    """给 DSH 入口 URL 追加 ``?dsh_new_session=1``，触发前端清除当前会话。

    DSH 前端在 ``dsh-client-connection`` 插件加载阶段检测该参数，命中时
    清除 ``localStorage["dsh.sessions.current"]``，使 DSH 不加载上次会话、
    直接进入"New Session"空白视图——用户要求"点击之后直接重新开一个新的
    Session"。DSH 没有 REST API 创建会话，只能在前端侧清除当前会话指针。

    与 KCW 的 ``_ensure_session_url`` 不同：KCW 通过 REST API 创建新会话
    并返回 session 专属 URL；DSH 只能清除当前会话指针，让前端进入空白
    视图（用户发送第一条消息时 DSH 才真正创建会话）。
    """
    parts = urllib.parse.urlsplit(url)
    pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if not any(k == "dsh_new_session" for k, _ in pairs):
        pairs.append(("dsh_new_session", "1"))
    query = urllib.parse.urlencode(pairs)
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def launch_dsh_web(cwd=None, timeout_s=DEFAULT_TIMEOUT_S, *,
                   resolve_binary_fn=None, lan_ip_fn=None, mdns_fn=None,
                   popen_fn=None):
    """打开 DeepSeek Harness web：优先复用存活实例，否则拉起 ``dsh web``。

    复用分两路（见 ``_live_spawned_url``）：``_SPAWNED`` 内存登记 →
    固定端口特征探测（launcher 重启后登记丢失的兜底；新版 dsh token 门
    下靠 ``_write_entry_state`` 落盘的带 token 入口）；冷启动绑固定
    专属端口 ``DSH_WEB_PORT``，失败后再探一次固定端口兜底（端口可能
    被登记滞后的存活实例占用，对齐 ``kimi_web`` 的兜底语义）。

    无论复用还是冷启动，返回的 URL 都带 ``?dsh_new_session=1``——DSH
    前端检测到该参数时清除 ``localStorage["dsh.sessions.current"]``，
    进入"New Session"空白视图（用户要求"直接重新开一个新的 Session"）。

    Args:
        cwd: dsh 运行目录（绝对路径）；None 表示上位机用户主目录。
            目录不存在直接报错，绝不回退到其它目录。
        timeout_s: 整体超时（秒），默认 60。
        resolve_binary_fn / lan_ip_fn / mdns_fn / popen_fn: 测试钩子，默认
            ``_resolve_dsh_binary`` / ``_lan_ip`` / ``_mdns_hostname`` /
            ``subprocess.Popen``。

    Returns:
        成功 {"status": "ok", "url": <入口 URL>}；
        失败 {"status": "error", "error": <原因>}。
        URL 的回环 host 已改写为局域网可达入口（mDNS 主机名优先，其次
        局域网 IP）；成功拉起的子进程保持存活（杀它即关 web 服务；经
        固定端口探测复用到的实例非本进程拉起，不在此列）；失败路径杀净。
    """
    resolve_binary_fn = resolve_binary_fn or _resolve_dsh_binary
    lan_ip_fn = lan_ip_fn or _lan_ip
    mdns_fn = mdns_fn or _mdns_hostname

    cwd_str = None
    if cwd is not None:
        cwd_path = Path(cwd).expanduser()
        if not cwd_path.is_dir():
            return {
                "status": "error",
                "error": f"cwd 目录不存在或不是目录: {cwd}（不会回退到其它目录）",
            }
        cwd_str = str(cwd_path)

    # 快路径：复用存活实例（_SPAWNED 内存登记 → 固定端口特征探测）
    url = _live_spawned_url()
    if url:
        url = _mark_new_session(url)
        logger.info("复用已运行的 dsh web 实例（新会话）: %s", url)
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
    # client.js 注入 crypto.randomUUID 兜底 + ?dsh_new_session=1 清理逻辑
    # （幂等，失败只影响局域网自动进入 Projects 和新会话清理，不影响 dsh 启动）
    _patch_client_uuid_polyfill(binary)
    # 设置镜像回环门补丁：局域网浏览器切 host 模式（幂等，失败只影响
    # 局域网设置页/模型选择，不影响 dsh 启动）
    _patch_settings_mirror_gate(binary)
    # web-all remote-channel 补丁：remote-web-ui 卸载后防止聚合 client 自装
    # fetch 劫持把 /api 改写到已不存在的 /remote 通道（局域网 405）
    _patch_remote_channel_client()

    lan_ip = lan_ip_fn()
    mdns = mdns_fn()
    trusted_hosts = []
    if lan_ip:
        trusted_hosts.append(lan_ip)
    if mdns and mdns not in trusted_hosts:
        trusted_hosts.append(mdns)
    deadline = time.monotonic() + timeout_s
    proc, url, error = _spawn_and_capture(
        binary, cwd_str, trusted_hosts, deadline, popen_fn=popen_fn)
    if url:
        port = _url_port(url)
        lan_entry = _lan_url(url)
        # 登记 url（带 token）供复用：内存条目给本次 launcher 生命周期，
        # 落盘登记给 launcher 重启后的固定端口探测（新版 dsh token 门）
        _SPAWNED.append({"proc": proc, "port": port, "url": lan_entry})
        _write_entry_state(lan_entry, port, proc.pid)
        url = _mark_new_session(lan_entry)
        logger.info("dsh web 已启动（新会话）: pid=%s url=%s", proc.pid, url)
        return {"status": "ok", "url": url}

    # 冷启动失败兜底：固定端口可能被登记滞后的存活实例占用（如另一
    # launcher 此前拉起、本进程 _SPAWNED 没有登记的实例），再探一次复用
    url = _probe_dsh_fixed_port()
    if url:
        url = _mark_new_session(url)
        logger.info("冷启动未果，复用到固定端口上的存活 dsh 实例（新会话）: %s", url)
        return {"status": "ok", "url": url}
    # 端口被存活的 dsh 占用但复用不了（非 launcher 拉起、无 token 登记）：
    # 冷启动永远 EADDRINUSE，给用户可行动的提示而不是裸的退出码现场
    if _probe_root("127.0.0.1", DSH_WEB_PORT):
        error = (f"{error}；固定端口 {DSH_WEB_PORT} 已被一个存活的 dsh web "
                 "占用且其入口 token 未知（非 launcher 拉起或登记丢失），"
                 "请手动关闭该实例后重试")
    logger.warning("启动 dsh web 失败: %s", error)
    return {"status": "error", "error": error}


def _url_port(url: str):
    """从 URL 提取端口；解析失败返回 None（复用探测会跳过该条目）。"""
    from urllib.parse import urlsplit
    try:
        return urlsplit(url).port
    except ValueError:
        return None
