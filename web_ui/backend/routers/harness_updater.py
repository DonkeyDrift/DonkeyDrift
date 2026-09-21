"""Harness 下载与一键更新路由（issue #404）。

在 Car Connector（CC）页面提供「Harness 选择与下载 + 一键更新」板块的后端：

1. Harness 目录（4 项：Codex / Claude / DeepSeek Harness / Z-Code），每项
   含 CLI + 桌面端配对（DeepSeek Harness 仅 CLI）、官方下载来源与检测规则
   （PATH 命令、常见安装目录、Windows 注册表尽力而为），返回已装/未装与
   版本检测结果（对标 CC Switch：合并 PATH / 注册表 / 安装器目录等途径探测）。
2. 下载 + 安装：下载到本地-only 目录（~/.donkeycar/downloads，绝不进仓库）；
   npm CLI 走「npm pack」落盘 +「npm install -g」安装；桌面端按官方安装器
   策略尽力实现（Linux .deb 优先，macOS/Windows 结构支持、未实测平台见注释）。
3. 一键更新检查：Harness 版本、DonkeyDrift 本体（对比 GitHub 最新 release/tag）、
   donkeycar 组件（PyPI）、OTA 固件（Firmware 仓库最新 release 的 .bin asset，
   下载到本地-only 目录）；执行安装/OTA 的接口（OTA 复用 Web Console 的
   HTTP /update，及 ArduinoOTA :3232 提示路径）。
4. 后台定期自动检查：asyncio 周期任务（启动后延迟 + 每隔可配置间隔），状态
   持久化到 ~/.donkeycar/harness_updater.json，前端打开即可见「已就绪/已是最新」。
5. 所有网络请求带超时与失败容错，返回友好错误而非 500。

所有检测与网络请求均为 best-effort：失败返回降级结果，不抛 500。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

# ─────────────────────────────────────────────────────────────────────────
# 本地-only 目录与状态持久化
# ─────────────────────────────────────────────────────────────────────────

# 下载落地目录：绝不进仓库（与凭据同级，运行时目录）。
DOWNLOAD_DIR = Path.home() / ".donkeycar" / "downloads"
# 后台检查与最近一次结果的持久化文件（本地-only，不含任何凭据）。
STATE_PATH = Path.home() / ".donkeycar" / "harness_updater.json"

# 网络请求统一超时（秒）。
NETWORK_TIMEOUT_S = 15.0
# 子进程（版本探测 / npm / 安装器）统一超时（秒）。
SUBPROCESS_TIMEOUT_S = 60.0
# 后台周期检查：启动后延迟首检 + 每隔 24h 再查（可被 env 覆盖，便于测试）。
FIRST_CHECK_DELAY_S = float(os.environ.get("HARNESS_FIRST_CHECK_DELAY_S", "30"))
CHECK_INTERVAL_S = float(os.environ.get("HARNESS_CHECK_INTERVAL_S", str(24 * 3600)))

# 状态里需要被 mask 的敏感 key 子串（本地持久化前统一打码，防止误写凭据）。
_SENSITIVE_KEY_MARKERS = ("token", "key", "secret", "password", "credential")


# ─────────────────────────────────────────────────────────────────────────
# Harness 目录（4 项，每项 CLI + 桌面端配对）
# ─────────────────────────────────────────────────────────────────────────
# install.type 语义：
#   "npm"  —— npm 全局包：download=「npm pack」落盘 .tgz，install=「npm i -g」。
#   "url"  —— 安装器 URL：download=下载到本地-only 目录，install=按平台运行安装器。
#            download_url 为空表示无稳定直链，仅能「打开官网下载」（前端新开标签页）。
# 桌面端检测与安装均跨平台尽力而为；macOS/Windows 路径为官方默认位置，
# 未在本机实测，代码结构支持，真实行为以运行时探测为准。

HARNESS_CATALOG: list[dict] = [
    {
        "id": "codex",
        "name": "Codex",
        "vendor": "OpenAI",
        "remote_default": None,
        "components": [
            {
                "id": "codex-cli",
                "kind": "cli",
                "name": "Codex CLI",
                "detect_commands": ["codex"],
                "detect_paths": [],
                "detect_win_registry": [],
                "version_args": ["--version"],
                "install": {
                    "type": "npm",
                    "package": "@openai/codex",
                    "download_url": None,
                    "linux_deb": None,
                    "doc_url": "https://developers.openai.com/codex/cli",
                },
            },
            {
                "id": "chatgpt-desktop",
                "kind": "desktop",
                "name": "ChatGPT Desktop",
                "detect_commands": [],
                "detect_paths": [
                    "/Applications/ChatGPT.app",          # macOS 官方默认位置
                    "~/Applications/ChatGPT.app",
                    "~/.local/bin/ChatGPT",               # Linux best-effort
                ],
                "detect_win_registry": [],
                "version_args": [],
                "install": {
                    "type": "url",
                    "package": None,
                    # OpenAI 官方下载页（无稳定直链，前端「打开官网」）。
                    "download_url": None,
                    "linux_deb": None,
                    "doc_url": "https://openai.com/chatgpt/download/",
                },
            },
        ],
    },
    {
        "id": "claude",
        "name": "Claude",
        "vendor": "Anthropic",
        "remote_default": None,
        "components": [
            {
                "id": "claude-cli",
                "kind": "cli",
                "name": "Claude Code",
                "detect_commands": ["claude"],
                "detect_paths": [],
                "detect_win_registry": [],
                "version_args": ["--version"],
                "install": {
                    "type": "npm",
                    "package": "@anthropic-ai/claude-code",
                    "download_url": None,
                    "linux_deb": None,
                    "doc_url": "https://claude.com/claude-code",
                },
            },
            {
                "id": "claude-desktop",
                "kind": "desktop",
                "name": "Claude Desktop",
                "detect_commands": [],
                "detect_paths": [
                    "/Applications/Claude.app",           # macOS 官方默认位置
                    "~/Applications/Claude.app",
                    "~/.config/Claude",                   # Linux 配置目录（已装即存在）
                ],
                "detect_win_registry": [
                    # Windows：安装器在卸载表注册（best-effort）。
                    r'reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall" /s /f "Claude"',
                ],
                "version_args": [],
                "install": {
                    "type": "url",
                    "package": None,
                    # 官方下载页；linux_deb 为 Anthropic 官方 Linux .deb（best-effort，
                    # 直链可能随版本更新变化，失败回退到 doc_url 打开官网）。
                    "download_url": "https://claude.com/download",
                    "linux_deb": "https://storage.googleapis.com/osprey-downloads-c02f6a0d-347c-492b-a752-3e0651722e97/nest/Claude-linux-x86_64.deb",
                    "doc_url": "https://claude.com/download",
                },
            },
        ],
    },
    {
        "id": "deepseek",
        "name": "DeepSeek Harness",
        "vendor": "DeepSeek",
        "remote_default": None,
        "components": [
            {
                "id": "dsh-cli",
                "kind": "cli",
                "name": "DeepSeek Harness (dsh)",
                # dsh 可执行文件：PATH 优先，回退到当前 Python 解释器同目录
                # （conda env bin，与 launcher dsh_web.py 的 _resolve_dsh_binary 同款）。
                "detect_commands": ["dsh"],
                "detect_paths": [],
                "detect_win_registry": [],
                "version_args": ["--version"],
                "install": {
                    "type": "npm",
                    "package": "@deepseek-ai/dsh",
                    "download_url": None,
                    "linux_deb": None,
                    "doc_url": "https://github.com/deepseek-ai/deepseek",
                },
            },
        ],
    },
    {
        "id": "zcode",
        "name": "Z-Code",
        "vendor": "z.ai",
        # 项目已集成其 remote 入口（zcode_remote.py 同款默认值）。
        "remote_default": "https://zcode.z.ai/remote/v4",
        "components": [
            {
                "id": "zcode-cli",
                "kind": "cli",
                "name": "Z Code CLI (TUI)",
                "detect_commands": ["zcode"],
                "detect_paths": [],
                "detect_win_registry": [],
                "version_args": ["--version"],
                "install": {
                    "type": "url",
                    "package": None,
                    # z.ai 官网（无稳定直链，前端「打开官网」）。
                    "download_url": None,
                    "linux_deb": None,
                    "doc_url": "https://z.ai/",
                },
            },
            {
                "id": "zcode-desktop",
                "kind": "desktop",
                "name": "Z Code Desktop",
                "detect_commands": [],
                # 与 zcode_remote.py 的 ZCODE_APP_BIN 一致的安装位置。
                "detect_paths": ["~/.zcode-app/zcode"],
                "detect_win_registry": [],
                "version_args": [],
                "install": {
                    "type": "url",
                    "package": None,
                    "download_url": None,
                    "linux_deb": None,
                    "doc_url": "https://z.ai/",
                },
            },
        ],
    },
]


# 依赖的「项目本体 / 组件 / 固件」更新来源常量。
DONKEYDRIFT_REPO = "DonkeyDrift/DonkeyDrift"
DONKEYCAR_PYPI = "donkeycar"
FIRMWARE_REPO = "DonkeyDrift/Firmware"
# 车辆 Web Console 的 HTTP OTA 端点与鉴权（auth 空即一次性鉴权，DEV 模式免鉴权）。
FIRMWARE_OTA_PATH = "/update"
FIRMWARE_OTA_AUTH = ""
# ArduinoOTA 备用通道提示（未直接实现，见 _ota_flash 说明）。
ARDUINO_OTA_PORT = 3232


# ─────────────────────────────────────────────────────────────────────────
# 通用小工具
# ─────────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        logger.warning("持久化状态失败: %s", e)


def _expand(path: str) -> Path:
    return Path(os.path.expanduser(path))


def parse_version(raw: str | None) -> str | None:
    """从命令输出 / 标签里提取语义化版本号；失败返回 None。"""
    if not raw:
        return None
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(raw)).strip()
    m = re.search(r"(\d+\.\d+(?:\.\d+)?(?:[-.][0-9A-Za-z.-]+)?)", text)
    return m.group(1) if m else None


def is_newer(latest: str | None, installed: str | None) -> bool:
    """latest 是否严格高于 installed；无法比较返回 False（保守：不误报可更新）。"""
    if not latest or not installed:
        return False
    try:
        from packaging.version import Version
        return Version(str(latest)) > Version(str(installed))
    except Exception:
        return False


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _run_capture(argv: list[str], timeout: float = SUBPROCESS_TIMEOUT_S) -> tuple[int, str]:
    """运行子进程并返回 (returncode, 去 ANSI 的 stdout+stderr)。失败返回非零 + 空。"""
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        out = re.sub(r"\x1b\[[0-9;]*m", "", out)
        return proc.returncode, out
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


# ─────────────────────────────────────────────────────────────────────────
# 检测：PATH 命令 / 常见安装目录 / Windows 注册表
# ─────────────────────────────────────────────────────────────────────────

def detect_component(component: dict) -> dict:
    """返回 {installed, version, path}；best-effort，任何失败降级为未装。"""
    found_path: str | None = None
    version: str | None = None

    # 1) PATH 命令（CLI 主途径）
    for cmd in component.get("detect_commands") or []:
        p = _which(cmd)
        if p:
            found_path = p
            break

    # 2) 常见安装目录
    if not found_path:
        for raw in component.get("detect_paths") or []:
            p = _expand(raw)
            if p.exists():
                found_path = str(p)
                break

    # 3) Windows 注册表（best-effort，仅 Windows 上执行）
    if not found_path and platform.system() == "Windows":
        for query in component.get("detect_win_registry") or []:
            code, out = _run_capture(["reg", "query"] + _split_reg_query(query), 5.0)
            if code == 0 and out.strip():
                found_path = "registry"
                break

    # 版本探测：对 PATH 里的命令跑 version_args
    version_args = component.get("version_args") or []
    if found_path and version_args and found_path not in ("registry",):
        base = component.get("detect_commands") or []
        if base:
            argv = [base[0]] + list(version_args)
            code, out = _run_capture(argv, 15.0)
            if code == 0:
                version = parse_version(out)
        # 桌面端按安装目录里的可执行文件探测（尽力而为）
        elif component.get("kind") == "desktop":
            exe = _expand(found_path)
            if exe.is_file() and os.access(exe, os.X_OK):
                code, out = _run_capture([str(exe)] + list(version_args), 15.0)
                if code == 0:
                    version = parse_version(out)

    return {"installed": found_path is not None, "version": version, "path": found_path}


def _split_reg_query(query: str) -> list[str]:
    """把注册表查询模板拆成 argv（去掉外层引号，其余按空格拆）。"""
    return [part.strip('"') for part in query.split(" ") if part.strip()]


def _catalog_status() -> list[dict]:
    """逐项检测，返回前端可直接渲染的目录状态。"""
    result = []
    for harness in HARNESS_CATALOG:
        components = []
        for component in harness["components"]:
            det = detect_component(component)
            components.append(
                {
                    "id": component["id"],
                    "kind": component["kind"],
                    "name": component["name"],
                    "installed": det["installed"],
                    "version": det["version"],
                    "path": det["path"],
                    "install": {
                        "type": component["install"]["type"],
                        "package": component["install"].get("package"),
                        "download_url": component["install"].get("download_url"),
                        "linux_deb": component["install"].get("linux_deb"),
                        "doc_url": component["install"].get("doc_url"),
                    },
                }
            )
        result.append(
            {
                "id": harness["id"],
                "name": harness["name"],
                "vendor": harness["vendor"],
                "remote_default": harness["remote_default"],
                "components": components,
            }
        )
    return result


# ─────────────────────────────────────────────────────────────────────────
# 最新版本来源（npm / PyPI / GitHub），全部带超时 + 失败容错
# ─────────────────────────────────────────────────────────────────────────

def _http_json(url: str, timeout: float = NETWORK_TIMEOUT_S) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DonkeyDrifter-harness-updater"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.info("请求 %s 失败: %s", url, e)
        return None


def npm_latest_version(package: str) -> str | None:
    data = _http_json(f"https://registry.npmjs.org/{urllib.parse.quote(package, safe='@')}/latest")
    return data.get("version") if data else None


def pypi_latest_version(package: str) -> str | None:
    data = _http_json(f"https://pypi.org/pypi/{urllib.parse.quote(package)}/json")
    if not data:
        return None
    info = data.get("info") or {}
    return info.get("version")


def github_latest_release(repo: str) -> dict | None:
    """返回 {tag, assets:[{name, browser_download_url}]}；无 release 返回 None。"""
    data = _http_json(f"https://api.github.com/repos/{repo}/releases/latest")
    if not data:
        return None
    assets = data.get("assets") or []
    return {
        "tag": data.get("tag_name") or data.get("name") or "",
        "assets": [
            {"name": a.get("name", ""), "browser_download_url": a.get("browser_download_url", "")}
            for a in assets
        ],
    }


def github_latest_tag(repo: str) -> str | None:
    """最新 tag（release 不存在时兜底）。"""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/tags?per_page=1",
            headers={"User-Agent": "DonkeyDrifter-harness-updater"},
        )
        with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, list) and data:
            return data[0].get("name")
    except Exception as e:
        logger.info("请求 %s tags 失败: %s", repo, e)
    return None


# ─────────────────────────────────────────────────────────────────────────
# 下载 + 安装
# ─────────────────────────────────────────────────────────────────────────

def _resolve_install_info(component: dict) -> dict:
    return component.get("install") or {}


def download_component(component: dict) -> dict:
    """把组件安装器下载到本地-only 目录，返回 {status, path|url, message}。"""
    info = _resolve_install_info(component)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    if info.get("type") == "npm" and info.get("package"):
        # npm 包：npm pack 落盘 .tgz 到本地-only 目录（真实安装由 install 走 npm i -g）。
        pkg = info["package"]
        argv = ["npm", "pack", pkg, "--pack-destination", str(DOWNLOAD_DIR)]
        code, out = _run_capture(argv, SUBPROCESS_TIMEOUT_S)
        if code != 0:
            return {"status": "error", "message": f"npm pack 失败: {out.strip()[:300]}"}
        tgz = _find_newest_tgz(DOWNLOAD_DIR, pkg)
        return {"status": "ok", "path": str(tgz), "message": "已下载到本地目录"}

    # url 类型：优先 Linux .deb 直链，否则官方下载页（无稳定直链 → 打开官网）。
    direct = info.get("linux_deb") if platform.system() == "Linux" else info.get("download_url")
    if not direct:
        return {
            "status": "open_url",
            "url": info.get("doc_url") or info.get("download_url"),
            "message": "无稳定直链，请前往官网下载",
        }
    return _download_url_to_dir(direct, info)


def _find_newest_tgz(directory: Path, package: str) -> Path:
    """在 downloads 目录里找 package 对应的最新 .tgz（按 mtime）。"""
    prefix = package.split("/")[-1]
    candidates = [p for p in directory.glob(f"{prefix}-*.tgz")]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else directory / f"{prefix}.tgz"


def _download_url_to_dir(url: str, info: dict) -> dict:
    """把 URL 下载到本地-only 目录（文件名从 URL/Content-Disposition 推导）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DonkeyDrifter-harness-updater"})
        with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT_S * 4) as resp:
            data = resp.read()
        filename = _filename_from_url(url, resp.headers.get("Content-Disposition", ""))
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        target = DOWNLOAD_DIR / filename
        target.write_bytes(data)
        return {"status": "ok", "path": str(target), "message": "已下载到本地目录"}
    except Exception as e:
        return {
            "status": "open_url",
            "url": info.get("doc_url") or url,
            "message": f"下载失败（{e}），请前往官网",
        }


def _filename_from_url(url: str, content_disposition: str) -> str:
    m = re.search(r'filename="?([^";]+)"?', content_disposition)
    if m:
        return m.group(1)
    path = urllib.parse.urlparse(url).path
    name = os.path.basename(path) or "installer"
    return name


def install_component(component: dict) -> dict:
    """安装组件（best-effort）。npm 走 npm i -g；url 类型按平台运行安装器。"""
    info = _resolve_install_info(component)
    if info.get("type") == "npm" and info.get("package"):
        argv = ["npm", "install", "-g", f"{info['package']}@latest"]
        code, out = _run_capture(argv, SUBPROCESS_TIMEOUT_S * 3)
        if code != 0:
            return {"status": "error", "message": f"npm install 失败: {out.strip()[:300]}"}
        return {"status": "ok", "message": f"已安装 {info['package']}"}

    # url 类型：定位本地已下载的安装器并运行（按扩展名 / 平台）。
    installer = _find_downloaded_installer(info)
    if not installer:
        return {
            "status": "open_url",
            "url": info.get("doc_url") or info.get("download_url"),
            "message": "未找到已下载的安装器，请先下载或前往官网",
        }
    return _run_installer(installer, info)


def _find_downloaded_installer(info: dict) -> Path | None:
    """在本地-only 目录找与 install 信息匹配的安装器（按扩展名，best-effort）。"""
    if not DOWNLOAD_DIR.is_dir():
        return None
    exts = (".deb", ".rpm", ".tar.gz", ".tgz", ".dmg", ".exe", ".AppImage", ".msi")
    candidates = sorted(
        (p for p in DOWNLOAD_DIR.iterdir() if p.is_file() and p.name.lower().endswith(exts)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _run_installer(installer: Path, info: dict) -> dict:
    """按平台/扩展名运行安装器。macOS/Windows 未实测：只拉起系统安装器并提示。"""
    system = platform.system()
    name = installer.name.lower()
    try:
        if system == "Linux":
            if name.endswith(".deb"):
                code, out = _run_capture(["sudo", "-n", "dpkg", "-i", str(installer)], SUBPROCESS_TIMEOUT_S * 3)
                if code != 0:
                    # sudo -n 无密码时会失败：退回提示手动安装。
                    return {"status": "manual", "path": str(installer), "message": "请手动运行: sudo dpkg -i"}
                return {"status": "ok", "message": "已安装 .deb"}
            if name.endswith(".rpm"):
                code, out = _run_capture(["sudo", "-n", "rpm", "-i", str(installer)], SUBPROCESS_TIMEOUT_S * 3)
                return {"status": "ok" if code == 0 else "manual", "path": str(installer), "message": "已安装 .rpm" if code == 0 else "请手动运行: sudo rpm -i"}
            if name.endswith((".tar.gz", ".tgz")):
                return {"status": "manual", "path": str(installer), "message": "请手动解压安装: tar xzf"}
            return {"status": "manual", "path": str(installer), "message": "请手动运行安装器"}
        if system == "Darwin":
            # macOS：挂载 dmg / 打开 pkg（未实测，结构支持）。
            subprocess.Popen(["open", str(installer)])
            return {"status": "opened", "path": str(installer), "message": "已交给系统安装器"}
        if system == "Windows":
            # Windows：os.startfile 打开安装器（未实测，结构支持）。
            os.startfile(str(installer))  # type: ignore[attr-defined]
            return {"status": "opened", "path": str(installer), "message": "已交给系统安装器"}
        return {"status": "manual", "path": str(installer), "message": "暂不支持该平台自动安装"}
    except Exception as e:
        return {"status": "manual", "path": str(installer), "message": f"自动安装失败（{e}），请手动运行安装器"}


# ─────────────────────────────────────────────────────────────────────────
# 一键更新检查
# ─────────────────────────────────────────────────────────────────────────

def _current_donkeydrifter_version() -> str | None:
    try:
        from donkeycar._version import __version__
        return __version__
    except Exception:
        return None


def _current_donkeycar_version() -> str | None:
    try:
        import importlib.metadata
        return importlib.metadata.version("donkeycar")
    except Exception:
        return None


def _firmware_vehicle_ip() -> str | None:
    """从连接器配置读车端 IP（用于 OTA 目标与当前固件版本查询，best-effort）。"""
    try:
        cfg = _read_json(Path.home() / ".donkeycar_web_connector.json")
        host = (cfg or {}).get("host")
        return host if isinstance(host, str) and host.strip() else None
    except Exception:
        return None


def _firmware_current_version(ip: str | None) -> str | None:
    """查询车辆 Web Console /api/status 的 version= 字段（best-effort）。"""
    if not ip:
        return None
    try:
        with urllib.request.urlopen(f"http://{ip}/api/status", timeout=5.0) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        m = re.search(r"version=([^\s]+)", text)
        return m.group(1) if m else None
    except Exception:
        return None


def check_harness_updates() -> list[dict]:
    """Harness 组件可更新项（已装且 latest > installed，或未装可下载）。"""
    updates = []
    for harness in HARNESS_CATALOG:
        for component in harness["components"]:
            det = detect_component(component)
            info = component["install"]
            latest = None
            if info.get("type") == "npm" and info.get("package"):
                latest = npm_latest_version(info["package"])
            item = {
                "kind": "harness",
                "harness_id": harness["id"],
                "component_id": component["id"],
                "name": component["name"],
                "installed": det["installed"],
                "installed_version": det["version"],
                "latest_version": latest,
                "updateable": det["installed"] and is_newer(latest, det["version"]),
                "install_type": info.get("type"),
                "package": info.get("package"),
                "doc_url": info.get("doc_url"),
            }
            updates.append(item)
    return updates


def check_project_update() -> dict | None:
    """DonkeyDrift 本体更新（对比 GitHub 最新 release/tag）。"""
    current = _current_donkeydrifter_version()
    latest = None
    release = github_latest_release(DONKEYDRIFT_REPO)
    if release and release["tag"]:
        latest = parse_version(release["tag"])
    else:
        tag = github_latest_tag(DONKEYDRIFT_REPO)
        latest = parse_version(tag) if tag else None
    if not latest and not current:
        return None
    return {
        "kind": "project",
        "id": "donkeydrift",
        "name": "DonkeyDrifter",
        "installed_version": current,
        "latest_version": latest,
        "updateable": is_newer(latest, current),
    }


def check_donkeycar_update() -> dict | None:
    """donkeycar 组件更新（PyPI 最新 vs 已装）。"""
    current = _current_donkeycar_version()
    latest = pypi_latest_version(DONKEYCAR_PYPI)
    if not current and not latest:
        return None
    return {
        "kind": "component",
        "id": "donkeycar",
        "name": "donkeycar",
        "installed_version": current,
        "latest_version": latest,
        "updateable": is_newer(latest, current),
    }


def check_firmware_update() -> dict | None:
    """OTA 固件更新（Firmware 仓库最新 release 的 .bin asset，下载到本地-only）。"""
    release = github_latest_release(FIRMWARE_REPO)
    if not release:
        return {
            "kind": "firmware",
            "id": "firmware",
            "name": "MUS4 固件",
            "installed_version": _firmware_current_version(_firmware_vehicle_ip()),
            "latest_version": None,
            "asset": None,
            "updateable": False,
            "note": "Firmware 仓库暂无 release 产物",
        }
    bin_asset = next(
        (a for a in release["assets"] if a["name"].lower().endswith((".bin", ".ino.bin"))),
        None,
    )
    asset_path = None
    if bin_asset and bin_asset["browser_download_url"]:
        asset_path = _download_firmware_asset(bin_asset)
    current = _firmware_current_version(_firmware_vehicle_ip())
    latest = parse_version(release["tag"])
    return {
        "kind": "firmware",
        "id": "firmware",
        "name": "MUS4 固件",
        "installed_version": current,
        "latest_version": latest,
        "asset": asset_path,
        "asset_name": bin_asset["name"] if bin_asset else None,
        "vehicle_ip": _firmware_vehicle_ip(),
        "updateable": bin_asset is not None and is_newer(latest, current),
        "note": None,
    }


def _download_firmware_asset(asset: dict) -> str | None:
    """下载固件 .bin 到本地-only 目录，返回本地路径；失败返回 None。"""
    try:
        url = asset["browser_download_url"]
        req = urllib.request.Request(url, headers={"User-Agent": "DonkeyDrifter-harness-updater"})
        with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT_S * 4) as resp:
            data = resp.read()
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        target = DOWNLOAD_DIR / (asset["name"] or "firmware.bin")
        target.write_bytes(data)
        return str(target)
    except Exception as e:
        logger.info("下载固件失败: %s", e)
        return None


def run_update_check() -> dict:
    """执行一次完整更新检查，返回各类可更新项与版本信息。"""
    updates = []
    errors = []

    try:
        updates.extend(check_harness_updates())
    except Exception as e:
        logger.exception("harness 更新检查失败")
        errors.append(f"harness: {e}")
    try:
        p = check_project_update()
        if p:
            updates.append(p)
    except Exception as e:
        logger.exception("project 更新检查失败")
        errors.append(f"project: {e}")
    try:
        c = check_donkeycar_update()
        if c:
            updates.append(c)
    except Exception as e:
        logger.exception("donkeycar 更新检查失败")
        errors.append(f"donkeycar: {e}")
    try:
        f = check_firmware_update()
        if f:
            updates.append(f)
    except Exception as e:
        logger.exception("firmware 更新检查失败")
        errors.append(f"firmware: {e}")

    return {
        "ok": not errors,
        "checked_at": _now_iso(),
        "updates": updates,
        "updateable_count": sum(1 for u in updates if u.get("updateable")),
        "errors": errors,
    }


# ─────────────────────────────────────────────────────────────────────────
# 安装 / OTA 执行
# ─────────────────────────────────────────────────────────────────────────

def _find_component(harness_id: str, component_id: str) -> dict | None:
    for harness in HARNESS_CATALOG:
        if harness["id"] != harness_id:
            continue
        for component in harness["components"]:
            if component["id"] == component_id:
                return component
    return None


def install_update(kind: str, target_id: str) -> dict:
    """按 kind/id 执行安装（harness 组件 / 项目 / 组件）。OTA 走单独接口。"""
    if kind == "harness":
        # target_id 形如 "<harness_id>/<component_id>"
        harness_id, _, component_id = target_id.partition("/")
        component = _find_component(harness_id, component_id)
        if not component:
            return {"status": "error", "message": "未知 Harness 组件"}
        return install_component(component)
    if kind == "project":
        return {
            "status": "manual",
            "message": "DonkeyDrift 项目更新请在新分支 git pull（Tony 分支），本接口不自动改写仓库",
        }
    if kind == "component":
        argv = ["pip", "install", "--upgrade", "donkeycar"]
        code, out = _run_capture(argv, SUBPROCESS_TIMEOUT_S * 3)
        if code != 0:
            return {"status": "error", "message": f"pip 更新失败: {out.strip()[:300]}"}
        return {"status": "ok", "message": "donkeycar 已更新"}
    return {"status": "error", "message": f"未知更新类型: {kind}"}


def _post_multipart_file(url: str, field: str, filename: str, data: bytes, timeout: float) -> tuple[int, bytes]:
    """手工构造 multipart/form-data 上传（复用 urllib，无额外依赖）。"""
    boundary = "----DonkeyDriftOta" + uuid4().hex
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            data,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def ota_flash(ip: str, asset_path: str | None = None) -> dict:
    """把固件 .bin 刷到车辆（HTTP /update 通道；ArduinoOTA :3232 为提示路径）。"""
    from routers.console import _validate_ip  # 复用私网 SSRF 校验

    try:
        _validate_ip(ip)
    except Exception as e:
        return {"status": "error", "message": f"非法车端地址: {e}"}

    if not asset_path:
        # 兜底：找本地-only 目录最新 .bin
        candidates = sorted(DOWNLOAD_DIR.glob("*.bin"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not candidates:
            return {"status": "error", "message": "本地无已下载固件，请先执行一键更新检查下载"}
        asset_path = str(candidates[0])

    path = Path(asset_path)
    if not path.is_file():
        return {"status": "error", "message": f"固件文件不存在: {asset_path}"}

    url = f"http://{ip}{FIRMWARE_OTA_PATH}?auth={FIRMWARE_OTA_AUTH}"
    try:
        status, body = _post_multipart_file(
            url, "update", path.name, path.read_bytes(), 300.0
        )
        text = body.decode("utf-8", errors="replace").strip()
        if status == 200 and "ACK:UPDATE_OK" in text:
            return {"status": "ok", "message": "OTA 成功，设备将自动重启"}
        return {
            "status": "manual",
            "message": f"HTTP OTA 返回异常（HTTP {status}: {text[:200]}），"
                       f"请用 ArduinoOTA（端口 {ARDUINO_OTA_PORT}）刷机",
        }
    except Exception as e:
        return {
            "status": "manual",
            "message": f"HTTP OTA 失败（{e}），请用 ArduinoOTA（端口 {ARDUINO_OTA_PORT}）刷机",
        }


# ─────────────────────────────────────────────────────────────────────────
# 状态持久化（mask 敏感字段）
# ─────────────────────────────────────────────────────────────────────────

def mask_sensitive(data: object) -> object:
    """递归把疑似敏感字段（token/key/secret/password/credential）打码。"""
    if isinstance(data, dict):
        return {
            k: "***" if any(m in str(k).lower() for m in _SENSITIVE_KEY_MARKERS) else mask_sensitive(v)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [mask_sensitive(v) for v in data]
    return data


def load_state() -> dict:
    return _read_json(STATE_PATH)


def save_state(state: dict) -> None:
    _write_json(STATE_PATH, mask_sensitive(state))


# ─────────────────────────────────────────────────────────────────────────
# 后台周期检查
# ─────────────────────────────────────────────────────────────────────────

_background_task: asyncio.Task | None = None
_state: dict = {"last_check_at": None, "last_check_ok": None, "updateable_count": None}


async def _periodic_check_loop() -> None:
    """后台周期检查：延迟首检 + 每隔 interval 查一次，结果持久化。"""
    await asyncio.sleep(FIRST_CHECK_DELAY_S)
    while True:
        try:
            result = await asyncio.to_thread(run_update_check)
            _state.update(
                {
                    "last_check_at": result.get("checked_at"),
                    "last_check_ok": result.get("ok"),
                    "updateable_count": result.get("updateable_count"),
                }
            )
            save_state(
                {
                    "last_check_at": result.get("checked_at"),
                    "last_check_ok": result.get("ok"),
                    "updateable_count": result.get("updateable_count"),
                    "updates": result.get("updates"),
                }
            )
        except Exception as e:
            logger.exception("后台更新检查失败: %s", e)
        await asyncio.sleep(CHECK_INTERVAL_S)


def start_background_check() -> None:
    """幂等启动后台周期检查任务（在应用 lifespan 里调用）。"""
    global _background_task
    if _background_task is None or _background_task.done():
        _background_task = asyncio.create_task(_periodic_check_loop())


async def stop_background_check() -> None:
    global _background_task
    if _background_task is not None:
        _background_task.cancel()
        try:
            await _background_task
        except (asyncio.CancelledError, Exception):
            pass
        _background_task = None


# ─────────────────────────────────────────────────────────────────────────
# 路由
# ─────────────────────────────────────────────────────────────────────────

class DownloadRequest(BaseModel):
    harness_id: str
    component_id: str


class InstallRequest(BaseModel):
    harness_id: str
    component_id: str


class InstallUpdateRequest(BaseModel):
    kind: str
    id: str


class OtaFlashRequest(BaseModel):
    ip: str
    asset_path: str | None = None


def _component_or_404(harness_id: str, component_id: str) -> dict:
    component = _find_component(harness_id, component_id)
    if not component:
        raise HTTPException(status_code=404, detail="未知 Harness 组件")
    return component


@router.get("/catalog")
async def get_catalog():
    """Harness 目录 + 已装/未装与版本检测结果。"""
    try:
        return {"ok": True, "harnesses": _catalog_status(), "checked_at": _now_iso()}
    except Exception as e:
        logger.exception("构建 harness 目录失败")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"目录构建失败: {e}"})


@router.post("/download")
async def download(request: DownloadRequest):
    """下载组件安装器到本地-only 目录。"""
    component = _component_or_404(request.harness_id, request.component_id)
    try:
        result = await asyncio.to_thread(download_component, component)
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"下载失败: {e}"})
    return result


@router.post("/install")
async def install(request: InstallRequest):
    """安装组件（npm 全局包或运行已下载安装器）。"""
    component = _component_or_404(request.harness_id, request.component_id)
    try:
        result = await asyncio.to_thread(install_component, component)
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"安装失败: {e}"})
    return result


@router.post("/check")
async def check():
    """一键更新检查（Harness / 项目 / 组件 / OTA 固件）。"""
    try:
        result = await asyncio.to_thread(run_update_check)
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": f"更新检查失败: {e}"})
    save_state(result)
    return result


@router.post("/install-update")
async def install_update_route(request: InstallUpdateRequest):
    """执行某个可更新项的安装（harness 组件 / donkeycar 组件 / 项目提示）。"""
    try:
        result = await asyncio.to_thread(install_update, request.kind, request.id)
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"安装失败: {e}"})
    return result


@router.post("/ota/flash")
async def ota_flash_route(request: OtaFlashRequest):
    """把本地-only 目录的固件刷到车辆（HTTP /update 通道）。"""
    try:
        result = await asyncio.to_thread(ota_flash, request.ip, request.asset_path)
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"OTA 失败: {e}"})
    return result


@router.get("/status")
async def status():
    """后台检查状态 + 最近一次检查结果。"""
    persisted = load_state()

    def _pick(key):
        # 明确区分「无值(None)」与「有值的假值(False/0)」，避免 0 被误判为无值。
        val = persisted.get(key)
        return _state.get(key) if val is None else val

    return {
        "background_enabled": _background_task is not None and not _background_task.done(),
        "interval_s": CHECK_INTERVAL_S,
        "last_check_at": _pick("last_check_at"),
        "last_check_ok": _pick("last_check_ok"),
        "updateable_count": _pick("updateable_count"),
        "updates": persisted.get("updates", []),
    }
