"""ZCode 远控链接实时端点：POST /api/zcode-remote/link

点击 DC/DD 的「ZCode」按钮时，实时向本机 ZCode 桌面端取一条新鲜远控链接，
彻底替代"手工粘贴链接存 localStorage"的旧流程：

1. 桌面端在跑且带 CDP 调试口（:9222）时，直接向渲染进程取
   `getWebRemoteControlStatus().connectUrl`；远控未开启则代调
   `startWebRemoteControl` 开启（等同桌面端 UI 上的「开启远程控制」）。
2. 桌面端不在跑：后台拉起（带 CDP 口），等它就绪后取链接。
3. 兜底：从桌面端持久化凭证现拼链接——deviceSid 存
   `~/.zcode/v2/setting.json`（webRemoteControlExternalRelayDevice），
   passHash 存 `~/.zcode/v2/credentials.json`（aes-256-gcm，密钥由
   `zcode-credential-fallback:<platform>:<home>:<user>` 派生，与桌面端
   createCredentialCipherProvider 同构，可本地解密）。

链接里的 t（毫秒时间戳）每次现刷，z.ai 页面只认新鲜 t，因此每次点击
拿到的都是不过期的链接。桌面端保持运行是远程控制可用的前提（页面经
中继服务器连到桌面端进程）。
"""

import asyncio
import base64
import getpass
import glob
import hashlib
import json
import logging
import os
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# ZCode 桌面端安装与数据目录（AppImage 解包形态）
ZCODE_APP_DIR = Path.home() / ".zcode-app"
ZCODE_APP_BIN = ZCODE_APP_DIR / "zcode"
REMOTE_PAGE_BASE = "https://zcode.z.ai/remote/v4"
CDP_BASE_URL = "http://127.0.0.1:9222"
# 点击后整体等待桌面端就绪的上限（冷启动 + 中继注册）
ENSURE_TIMEOUT_S = 25.0

_PASS_HASH_KEY = "web-remote-control:external-relay:pass_hash"
_ENC_PREFIX = "enc:v1:"


def _v2_dir() -> Path:
    """桌面端数据目录：$ZCODE_DATA_BASE_DIR/.zcode/v2，缺省 ~/.zcode/v2。"""
    base = os.environ.get("ZCODE_DATA_BASE_DIR", "").strip() or str(Path.home())
    return Path(base) / ".zcode" / "v2"


def _read_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _derive_cipher_key() -> bytes:
    secret = os.environ.get("ZCODE_CREDENTIAL_SECRET", "").strip()
    if not secret:
        secret = (
            f"zcode-credential-fallback:linux:{Path.home()}:{getpass.getuser()}"
        )
    return hashlib.sha256(secret.encode()).digest()


def _decrypt_credential(value: str) -> str:
    """解密 credentials.json 条目（enc:v1:<b64u(iv)>.<b64u(tag)>.<b64u(ct)>）。"""
    if not value.startswith(_ENC_PREFIX):
        return value
    iv_s, tag_s, ct_s = value[len(_ENC_PREFIX):].split(".")
    iv, tag, ct = _b64u_decode(iv_s), _b64u_decode(tag_s), _b64u_decode(ct_s)
    return AESGCM(_derive_cipher_key()).decrypt(iv, ct + tag, None).decode()


def _refresh_t(url: str) -> str:
    """把链接里的 t 刷成当前毫秒时间戳。"""
    parts = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qs(parts.query)
    q["t"] = [str(int(time.time() * 1000))]
    query = urllib.parse.urlencode(
        [(k, v) for k, vs in q.items() for v in vs]
    )
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, query, "")
    )


def _app_version() -> str:
    """从 app.asar 头部读 /package.json 的 version（只读、best-effort）。"""
    asar = ZCODE_APP_DIR / "resources" / "app.asar"
    try:
        import struct

        with open(asar, "rb") as f:
            header_size = struct.unpack("<I", f.read(8)[4:8])[0]
            f.seek(12)
            json_len = struct.unpack("<I", f.read(4))[0]
            hdr = json.loads(f.read(json_len))
            pkg = hdr.get("files", {}).get("package.json")
            if pkg and "offset" in pkg:
                f.seek(8 + header_size + int(pkg["offset"]))
                return json.loads(f.read(int(pkg["size"]))).get("version", "")
    except Exception:
        pass
    return ""


def _mint_link_from_store() -> str | None:
    """用持久化凭证现拼链接（桌面端离线时的兜底）。"""
    settings = _read_json(_v2_dir() / "setting.json")
    sid = (
        settings.get("webRemoteControlExternalRelayDevice") or {}
    ).get("deviceSid", "").strip()
    creds = _read_json(_v2_dir() / "credentials.json")
    enc = creds.get(_PASS_HASH_KEY, "")
    if not sid or not enc:
        return None
    try:
        pass_hash = _decrypt_credential(enc)
    except Exception as e:
        logger.warning("ZCode 凭证解密失败: %s", e)
        return None
    q = {
        "sid": sid,
        "hash": pass_hash,
        "t": str(int(time.time() * 1000)),
    }
    mid = _read_json(_v2_dir() / "telemetry-state.json").get("deviceMid", "").strip()
    if mid:
        q["mid"] = mid
        q["name"] = socket.gethostname()
        version = _app_version()
        if version:
            q["app_version"] = version
    return f"{REMOTE_PAGE_BASE}?{urllib.parse.urlencode(q)}"


def _app_running() -> bool:
    try:
        return (
            subprocess.run(
                ["pgrep", "-f", "/.zcode-app/zcode"],
                capture_output=True,
                timeout=3,
            ).returncode
            == 0
        )
    except Exception:
        return False


def _launch_app() -> None:
    """后台拉起桌面端（图形会话环境 + CDP 调试口），detached 不阻塞。"""
    env = os.environ.copy()
    env.update(
        {
            "XDG_RUNTIME_DIR": "/run/user/1000",
            "WAYLAND_DISPLAY": "wayland-0",
            "DISPLAY": ":0",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
        }
    )
    xauth = sorted(glob.glob("/run/user/1000/.mutter-Xwaylandauth.*"))
    if xauth:
        env["XAUTHORITY"] = xauth[0]
    try:
        subprocess.Popen(
            [str(ZCODE_APP_BIN), "--no-sandbox", "--remote-debugging-port=9222"],
            cwd=str(ZCODE_APP_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("ZCode 桌面端已拉起（CDP :9222）")
    except OSError as e:
        logger.warning("拉起 ZCode 桌面端失败: %s", e)


def _http_json(url: str, timeout: float = 2.0):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def _cdp_eval(ws, expression: str):
    await ws.send(
        json.dumps(
            {
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": expression,
                    "awaitPromise": True,
                    "returnByValue": True,
                },
            }
        )
    )
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == 1:
            return (msg.get("result", {}).get("result") or {}).get("value")


async def _cdp_remote_url() -> str | None:
    """经 CDP 确保远控开启并返回 connectUrl；任何一步失败返回 None。"""
    import websockets

    try:
        targets = await asyncio.to_thread(_http_json, f"{CDP_BASE_URL}/json")
    except Exception:
        return None
    page = next(
        (
            t
            for t in targets
            if t.get("type") == "page" and "renderer/index.html" in t.get("url", "")
        ),
        None,
    )
    if not page:
        return None
    try:
        async with websockets.connect(
            page["webSocketDebuggerUrl"], open_timeout=3
        ) as ws:
            status = await _cdp_eval(
                ws,
                "window.zcode && window.zcode.getWebRemoteControlStatus"
                " ? window.zcode.getWebRemoteControlStatus() : null",
            )
            if not isinstance(status, dict):
                return None
            if status.get("status") != "running":
                workspace = (
                    _read_json(_v2_dir() / "setting.json").get(
                        "webRemoteControlLastEnabledContext"
                    )
                    or {}
                ).get("workspacePath") or str(_v2_dir().parent / "workspace" / "default")
                status = await _cdp_eval(
                    ws,
                    "window.zcode.startWebRemoteControl("
                    + json.dumps({"workspacePath": workspace})
                    + ")",
                )
            if isinstance(status, dict) and status.get("connectUrl"):
                return _refresh_t(status["connectUrl"])
    except Exception as e:
        logger.info("CDP 取 ZCode 远控链接失败: %s", e)
    return None


@router.post("/link")
async def zcode_remote_link():
    """返回一条新鲜 ZCode 远控链接，必要时先拉起/开启桌面端远控。"""
    try:
        url = await _cdp_remote_url()
        if not url and not _app_running():
            _launch_app()
            deadline = time.monotonic() + ENSURE_TIMEOUT_S
            while not url and time.monotonic() < deadline:
                await asyncio.sleep(0.5)
                url = await _cdp_remote_url()
        if not url:
            url = _mint_link_from_store()
        if not url:
            return JSONResponse(
                status_code=409,
                content={
                    "status": "error",
                    "error": "本机 ZCode 桌面端远控尚未开启过，且无可用凭证",
                },
            )
        return {"status": "ok", "url": url}
    except Exception as e:
        logger.error("生成 ZCode 远控链接失败: %s", e)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": f"生成远控链接失败: {e}"},
        )
