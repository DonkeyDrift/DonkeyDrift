"""AI 配置（issue #403）：集中管理多供应商 AI 模型配置，供各 AI 功能统一调用。

设计要点：
- 供应商预设（名称/图标/默认 base URL/是否支持 OAuth/默认模型）+ 自定义供应商；
- 每个供应商可配置多个账号（如多个 ChatGPT 账号），凭据本地-only 持久化；
- API Key / OAuth token 绝不通过 HTTP 接口原样返回（只返回 masked 与「是否已配置」）；
- 「当前启用」供应商一键切换，供 TE「AI 一键筛选」(#402) 与后续 AI 功能消费；
- Codex 走 ChatGPT 账号 OAuth 设备码登录（参考 cc-switch 的实现）。

凭据安全红线：本文件只会把凭据写进 ~/.donkeycar/ai_config.json（本机私有、绝不入库），
并且任何 GET/列表接口都只返回掩码后的凭据；真正的明文凭据只通过模块内
resolve_active_credentials() 供后端内部 AI 调用方读取，绝不进响应体。
"""
import base64
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 供应商预设表
# ---------------------------------------------------------------------------
# 每个预设含：name（显示名）/ icon（前端图标 key）/ base_url（默认）/ oauth（是否支持
# 账号登录）/ api_format（openai | anthropic，决定 chat 请求格式）/ default_models。
# 注意：这里只是「默认值」与元数据，用户保存的覆盖值（base_url / 模型 / 凭据）持久化在
# ~/.donkeycar/ai_config.json，绝不写回仓库。
PROVIDER_PRESETS: Dict[str, Dict[str, Any]] = {
    "zhipu": {
        "name": "智谱 AI (GLM)",
        "icon": "sparkles",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "oauth": False,
        "api_format": "openai",
        "default_models": ["glm-4-flash", "glm-4-air", "glm-4-plus"],
    },
    "codex": {
        "name": "OpenAI Codex",
        "icon": "bot",
        # 默认走 OpenAI 官方 API；ChatGPT 账号 OAuth 登录时实际请求走 chatgpt.com 后端。
        "base_url": "https://api.openai.com/v1",
        "oauth": True,
        "api_format": "openai",
        "default_models": ["gpt-4.1", "gpt-4o-mini"],
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "icon": "brain",
        "base_url": "https://api.anthropic.com/v1",
        "oauth": False,
        "api_format": "anthropic",
        "default_models": ["claude-sonnet-4-5", "claude-haiku-4-5"],
    },
    "moonshot": {
        "name": "Moonshot AI Kimi",
        "icon": "moon",
        "base_url": "https://api.moonshot.cn/v1",
        "oauth": False,
        "api_format": "openai",
        "default_models": ["moonshot-v1-8k", "kimi-k2"],
    },
    "qwen": {
        "name": "阿里通义千问 Qwen",
        "icon": "cloud",
        # 阿里云百炼 OpenAI 兼容模式。
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "oauth": False,
        "api_format": "openai",
        "default_models": ["qwen-plus", "qwen-turbo", "qwen-max"],
    },
    "deepseek": {
        "name": "DeepSeek",
        "icon": "search",
        "base_url": "https://api.deepseek.com/v1",
        "oauth": False,
        "api_format": "openai",
        "default_models": ["deepseek-chat", "deepseek-reasoner"],
    },
}

# 自定义供应商的图标 key（前端映射到 lucide 图标，缺省回退到通用图标）。
CUSTOM_PROVIDER_ICON = "puzzle"


# ---------------------------------------------------------------------------
# Codex / ChatGPT OAuth 设备码登录（参考 cc-switch 的实现，见其
# src-tauri/src/proxy/providers/codex_oauth_auth.rs）
# ---------------------------------------------------------------------------
# 公共 client_id 来自 cc-switch 公开源码（OpenAI 官方 Codex CLI 同款 OAuth 应用）。
# 若日后该公共 client_id 不可用，可通过环境变量 CODEX_OAUTH_CLIENT_ID 覆盖，
# 或在本机 ~/.donkeycar/ai_config.json 的 codex_client_id 字段覆盖（不入库）。
CODEX_CLIENT_ID_DEFAULT = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_DEVICE_CODE_URL = "https://auth.openai.com/api/accounts/deviceauth/usercode"
CODEX_DEVICE_TOKEN_URL = "https://auth.openai.com/api/accounts/deviceauth/token"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_VERIFICATION_URI = "https://auth.openai.com/codex/device"
CODEX_REDIRECT_URI = "https://auth.openai.com/deviceauth/callback"
CODEX_USER_AGENT = "donkeydrifter-cc-ai-config"
CODEX_OAUTH_HTTP_TIMEOUT = 30
CODEX_DEVICE_CODE_DEFAULT_EXPIRES_IN = 900


# ---------------------------------------------------------------------------
# 持久化：~/.donkeycar/ai_config.json（本地-only，目录不存在则创建，绝不写仓库目录）
# ---------------------------------------------------------------------------
def _config_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".donkeycar", "ai_config.json")


def _default_state() -> Dict[str, Any]:
    return {
        "active_provider": None,
        "active_account": None,
        "custom_providers": {},
        "accounts": {},
    }


def _load_state() -> Dict[str, Any]:
    path = _config_path()
    if not os.path.exists(path):
        return _default_state()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"AI 配置文件无效: {exc}") from exc
    state = _default_state()
    if isinstance(data, dict):
        for key in state:
            if key in data:
                state[key] = data[key]
    if not isinstance(state.get("custom_providers"), dict):
        state["custom_providers"] = {}
    if not isinstance(state.get("accounts"), dict):
        state["accounts"] = {}
    return state


def _save_state(state: Dict[str, Any]) -> None:
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _mask_secret(value: Optional[str]) -> Optional[str]:
    """掩码凭据：仅返回 sk-***last4 形式的展示串，绝不返回原文。"""
    if not value:
        return None
    if len(value) <= 8:
        return "***"
    return value[:3] + "***" + value[-4:]


def _provider_meta(provider_id: str, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """返回供应商元数据（预设或自定义），未知 id 返回 None。"""
    if provider_id in PROVIDER_PRESETS:
        preset = PROVIDER_PRESETS[provider_id]
        return {**preset, "id": provider_id, "custom": False}
    custom = state.get("custom_providers", {}).get(provider_id)
    if custom:
        return {
            "id": provider_id,
            "name": custom.get("name") or provider_id,
            "icon": CUSTOM_PROVIDER_ICON,
            "base_url": custom.get("base_url") or "",
            "oauth": False,
            "api_format": custom.get("api_format") or "openai",
            "custom": True,
            "default_models": custom.get("models") or [],
        }
    return None


def _account_view(account: Dict[str, Any]) -> Dict[str, Any]:
    """账号的对外视图：凭据一律掩码，绝不返回原文。"""
    return {
        "id": account.get("id"),
        "name": account.get("name") or "未命名账号",
        "api_key_masked": _mask_secret(account.get("api_key")),
        "has_api_key": bool(account.get("api_key")),
        "oauth_connected": bool(account.get("refresh_token")),
        "base_url": account.get("base_url"),
        "models": account.get("models"),
    }


def _provider_view(provider_id: str, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    meta = _provider_meta(provider_id, state)
    if meta is None:
        return None
    accounts = state.get("accounts", {}).get(provider_id, [])
    return {
        "id": provider_id,
        "name": meta["name"],
        "icon": meta["icon"],
        "base_url": meta["base_url"],
        "oauth": meta["oauth"],
        "api_format": meta["api_format"],
        "custom": meta["custom"],
        "default_models": meta.get("default_models") or [],
        "accounts": [_account_view(a) for a in accounts],
    }


def _all_provider_ids(state: Dict[str, Any]) -> List[str]:
    ids = list(PROVIDER_PRESETS.keys())
    ids += list(state.get("custom_providers", {}).keys())
    return ids


def _select_account(state: Dict[str, Any], provider_id: str, accounts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """按 active_account 选账号；未指定或失效时回退到第一个账号。"""
    if not accounts:
        return None
    active_account = state.get("active_account")
    if active_account:
        for acc in accounts:
            if acc.get("id") == active_account:
                return acc
    return accounts[0]


# ---------------------------------------------------------------------------
# 内部调用方：解析当前启用供应商的真实凭据（仅后端内部使用，绝不进 HTTP 响应）
# ---------------------------------------------------------------------------
def resolve_active_credentials() -> Optional[Dict[str, Any]]:
    """返回当前启用供应商可用于发起真实 AI 调用的凭据（含明文 key/token）。

    供 #402「AI 一键筛选」等后端 AI 调用方使用；不要把返回值原样返回给前端。
    返回 None 表示尚未配置可用供应商。
    """
    state = _load_state()
    provider_id = state.get("active_provider")
    if not provider_id:
        return None
    meta = _provider_meta(provider_id, state)
    if meta is None:
        return None
    accounts = state.get("accounts", {}).get(provider_id, [])
    account = _select_account(state, provider_id, accounts)
    if account is None:
        return None
    base_url = account.get("base_url") or meta.get("base_url") or ""
    models = account.get("models") or meta.get("default_models") or []
    return {
        "provider_id": provider_id,
        "name": meta.get("name"),
        "base_url": base_url,
        "api_format": meta.get("api_format", "openai"),
        "oauth": bool(meta.get("oauth")),
        "model": models[0] if models else None,
        "account_id": account.get("id"),
        "account_name": account.get("name"),
        "api_key": account.get("api_key"),
        "access_token": account.get("access_token"),
    }


# ---------------------------------------------------------------------------
# OAuth 设备码流程内存状态（单进程内有效；设备码有效期到后清理）
# ---------------------------------------------------------------------------
_pending_device_codes: Dict[str, Dict[str, Any]] = {}
_pending_lock = threading.Lock()


def _cleanup_pending_device_codes() -> None:
    now = time.time()
    with _pending_lock:
        expired = [k for k, v in _pending_device_codes.items() if v.get("expires_at", 0) <= now]
        for k in expired:
            _pending_device_codes.pop(k, None)


def _codex_client_id(state: Dict[str, Any]) -> str:
    env = os.environ.get("CODEX_OAUTH_CLIENT_ID", "").strip()
    if env:
        return env
    configured = state.get("codex_client_id")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return CODEX_CLIENT_ID_DEFAULT


def _http_json_post(url: str, data: Dict[str, Any], headers: Dict[str, str], timeout: int):
    """用 stdlib urllib 发 JSON POST，返回 (status_code, parsed_json)。"""
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if hasattr(exc, "read") else ""
        return exc.code, (json.loads(body) if body else {})


def _http_form_post(url: str, form: Dict[str, str], headers: Dict[str, str], timeout: int):
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(form).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace") if hasattr(exc, "read") else ""
        return exc.code, (json.loads(body) if body else {})


def _parse_interval(value: Any) -> int:
    if isinstance(value, bool):
        return 5
    if isinstance(value, (int, float)):
        return max(1, int(value))
    if isinstance(value, str):
        try:
            return max(1, int(value))
        except ValueError:
            return 5
    return 5


def _extract_account_id_from_tokens(tokens: Dict[str, Any]) -> str:
    """从 id_token 的 JWT payload 尽力提取 chatgpt_account_id，失败回退空串。"""
    id_token = tokens.get("id_token") or ""
    if not id_token:
        return ""
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8", "replace"))
        auth_claim = decoded.get("https://api.openai.com/auth") or {}
        if isinstance(auth_claim, dict) and auth_claim.get("chatgpt_account_id"):
            return str(auth_claim["chatgpt_account_id"])
        if decoded.get("chatgpt_account_id"):
            return str(decoded["chatgpt_account_id"])
        return decoded.get("sub") or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 请求体模型
# ---------------------------------------------------------------------------
class AccountUpsert(BaseModel):
    account_id: Optional[str] = None
    name: Optional[str] = None
    # api_key：提供非空值则保存/更新；传空串 "" 表示清空已保存的 key。None 表示不改动。
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    models: Optional[List[str]] = None


class SetActiveRequest(BaseModel):
    account_id: Optional[str] = None


class CustomProviderCreate(BaseModel):
    name: str
    base_url: str
    models: Optional[List[str]] = None
    api_format: str = "openai"
    provider_id: Optional[str] = None


class OAuthDeviceCodeRequest(BaseModel):
    provider_id: str = "codex"


class OAuthPollRequest(BaseModel):
    device_code: str
    user_code: Optional[str] = None


class TestRequest(BaseModel):
    provider_id: Optional[str] = None
    account_id: Optional[str] = None


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------
@router.get("/providers")
async def list_providers():
    """预设 + 用户配置合并后的供应商列表；凭据只返回掩码。"""
    state = _load_state()
    providers = []
    for provider_id in _all_provider_ids(state):
        view = _provider_view(provider_id, state)
        if view is not None:
            providers.append(view)
    return {
        "providers": providers,
        "active_provider": state.get("active_provider"),
        "active_account": state.get("active_account"),
    }


@router.get("/active")
async def get_active():
    """当前启用供应商的公开摘要（不含凭据）。

    即使尚未配置账号/凭据也返回选中的 provider id（configured=False），
    与 set_active 的返回保持一致，便于前端展示「已选中但未配置」状态。
    """
    state = _load_state()
    return get_active_summary(state)


@router.post("/providers/{provider_id}")
async def upsert_account(provider_id: str, request: AccountUpsert):
    """保存/更新某供应商下的一个账号（含 api_key 或清空）。多账号通过 account_id 区分。"""
    state = _load_state()
    if _provider_meta(provider_id, state) is None:
        raise HTTPException(status_code=404, detail=f"未知供应商: {provider_id}")
    accounts = state.setdefault("accounts", {}).setdefault(provider_id, [])

    account = None
    if request.account_id:
        for acc in accounts:
            if acc.get("id") == request.account_id:
                account = acc
                break
        if account is None:
            raise HTTPException(status_code=404, detail="账号不存在")

    if account is None:
        account = {
            "id": uuid.uuid4().hex,
            "name": request.name or "默认账号",
            "api_key": None,
            "oauth": False,
            "refresh_token": None,
            "access_token": None,
            "id_token": None,
            "base_url": None,
            "models": None,
        }
        accounts.append(account)

    if request.name is not None and request.name.strip():
        account["name"] = request.name.strip()
    if request.api_key is not None:
        if request.api_key.strip():
            account["api_key"] = request.api_key.strip()
            account["oauth"] = False
        else:
            account["api_key"] = None
    if request.base_url is not None:
        account["base_url"] = request.base_url.strip() or None
    if request.models is not None:
        account["models"] = [m for m in request.models if m and str(m).strip()]

    if state.get("active_provider") == provider_id and not state.get("active_account"):
        state["active_account"] = account["id"]

    _save_state(state)
    return {"status": True, "account": _account_view(account)}


@router.delete("/providers/{provider_id}/accounts/{account_id}")
async def delete_account(provider_id: str, account_id: str):
    state = _load_state()
    accounts = state.get("accounts", {}).get(provider_id, [])
    remaining = [a for a in accounts if a.get("id") != account_id]
    if len(remaining) == len(accounts):
        raise HTTPException(status_code=404, detail="账号不存在")
    state.setdefault("accounts", {})[provider_id] = remaining
    if state.get("active_account") == account_id:
        state["active_account"] = remaining[0]["id"] if remaining else None
    _save_state(state)
    return {"status": True}


@router.post("/providers/{provider_id}/active")
async def set_active(provider_id: str, request: SetActiveRequest):
    """一键切换「当前使用中」供应商（可指定账号）。"""
    state = _load_state()
    if _provider_meta(provider_id, state) is None:
        raise HTTPException(status_code=404, detail=f"未知供应商: {provider_id}")
    accounts = state.get("accounts", {}).get(provider_id, [])
    if request.account_id:
        if not any(a.get("id") == request.account_id for a in accounts):
            raise HTTPException(status_code=404, detail="账号不存在")
        state["active_account"] = request.account_id
    else:
        state["active_account"] = accounts[0]["id"] if accounts else None
    state["active_provider"] = provider_id
    _save_state(state)
    return get_active_summary(state)


def get_active_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    """从已加载的 state 生成 active 摘要（供 set_active 复用，避免二次读盘）。"""
    provider_id = state.get("active_provider")
    if not provider_id:
        return {"active_provider": None, "configured": False}
    meta = _provider_meta(provider_id, state)
    if meta is None:
        return {"active_provider": None, "configured": False}
    accounts = state.get("accounts", {}).get(provider_id, [])
    account = _select_account(state, provider_id, accounts)
    if account is None:
        return {"active_provider": provider_id, "configured": False}
    base_url = account.get("base_url") or meta.get("base_url") or ""
    models = account.get("models") or meta.get("default_models") or []
    has_secret = bool(account.get("api_key") or account.get("access_token"))
    return {
        "active_provider": provider_id,
        "name": meta["name"],
        "account_id": account.get("id"),
        "account_name": account.get("name"),
        "model": models[0] if models else None,
        "base_url": base_url,
        "oauth": bool(meta.get("oauth")),
        "configured": has_secret,
    }


@router.post("/custom")
async def create_custom_provider(request: CustomProviderCreate):
    """新建自定义供应商（自定义名称 + base URL + 模型列表）。"""
    state = _load_state()
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="名称不能为空")
    if not request.base_url.strip():
        raise HTTPException(status_code=400, detail="Base URL 不能为空")
    provider_id = request.provider_id or _slugify(name)
    if not provider_id:
        provider_id = "custom-" + uuid.uuid4().hex[:8]
    if provider_id in PROVIDER_PRESETS:
        raise HTTPException(status_code=400, detail="自定义供应商 id 与预设冲突")
    state.setdefault("custom_providers", {})[provider_id] = {
        "name": name,
        "base_url": request.base_url.strip(),
        "models": [m for m in (request.models or []) if m and str(m).strip()],
        "api_format": request.api_format if request.api_format in ("openai", "anthropic") else "openai",
    }
    _save_state(state)
    return {"status": True, "provider_id": provider_id}


@router.delete("/custom/{provider_id}")
async def delete_custom_provider(provider_id: str):
    state = _load_state()
    custom = state.get("custom_providers", {})
    if provider_id not in custom:
        raise HTTPException(status_code=404, detail="自定义供应商不存在")
    del custom[provider_id]
    state.get("accounts", {}).pop(provider_id, None)
    if state.get("active_provider") == provider_id:
        state["active_provider"] = None
        state["active_account"] = None
    _save_state(state)
    return {"status": True}


@router.post("/oauth/device-code")
async def start_oauth_device_code(request: OAuthDeviceCodeRequest):
    """发起 Codex/ChatGPT 账号 OAuth 设备码登录，返回 verification_uri + user_code。"""
    state = _load_state()
    meta = _provider_meta(request.provider_id, state)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"未知供应商: {request.provider_id}")
    if not meta.get("oauth"):
        raise HTTPException(status_code=400, detail="该供应商不支持账号登录（仅 Codex 支持）")

    client_id = _codex_client_id(state)
    status, payload = _http_json_post(
        CODEX_DEVICE_CODE_URL,
        {"client_id": client_id},
        {"User-Agent": CODEX_USER_AGENT},
        CODEX_OAUTH_HTTP_TIMEOUT,
    )
    if status != 200 or not payload.get("device_auth_id") or not payload.get("user_code"):
        raise HTTPException(status_code=502, detail=f"获取设备码失败: {status} {payload}")

    device_code = payload["device_auth_id"]
    user_code = payload["user_code"]
    expires_in = int(payload.get("expires_in") or CODEX_DEVICE_CODE_DEFAULT_EXPIRES_IN)
    interval = _parse_interval(payload.get("interval"))

    _cleanup_pending_device_codes()
    with _pending_lock:
        _pending_device_codes[device_code] = {
            "user_code": user_code,
            "expires_at": time.time() + expires_in,
        }

    return {
        "status": True,
        "device_code": device_code,
        "user_code": user_code,
        "verification_uri": CODEX_VERIFICATION_URI,
        "expires_in": expires_in,
        "interval": interval,
    }


@router.post("/oauth/poll")
async def poll_oauth_device_code(request: OAuthPollRequest):
    """轮询设备码授权状态；成功则换取 access/refresh token 并保存为 Codex 账号。"""
    device_code = request.device_code
    with _pending_lock:
        pending = _pending_device_codes.get(device_code)
    user_code = request.user_code or (pending or {}).get("user_code")
    if not user_code:
        raise HTTPException(status_code=404, detail="设备码已过期或不存在，请重新发起登录")

    status, payload = _http_json_post(
        CODEX_DEVICE_TOKEN_URL,
        {"device_auth_id": device_code, "user_code": user_code},
        {"User-Agent": CODEX_USER_AGENT},
        CODEX_OAUTH_HTTP_TIMEOUT,
    )
    if status in (403, 404):
        return {"status": "pending"}
    if status == 410:
        with _pending_lock:
            _pending_device_codes.pop(device_code, None)
        return {"status": "expired"}
    if status != 200 or not payload.get("authorization_code"):
        return {"status": "error", "detail": f"轮询失败: {status} {payload}"}

    authorization_code = payload["authorization_code"]
    code_verifier = payload.get("code_verifier", "")
    state = _load_state()
    client_id = _codex_client_id(state)

    token_status, tokens = _http_form_post(
        CODEX_OAUTH_TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": CODEX_REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": code_verifier,
        },
        {"User-Agent": CODEX_USER_AGENT},
        CODEX_OAUTH_HTTP_TIMEOUT,
    )
    if token_status != 200 or not tokens.get("access_token"):
        return {"status": "error", "detail": f"换取 token 失败: {token_status} {tokens}"}
    if not tokens.get("refresh_token"):
        return {"status": "error", "detail": "响应缺少 refresh_token，登录失败"}

    account_id = _extract_account_id_from_tokens(tokens) or ("chatgpt-" + uuid.uuid4().hex[:12])
    account = {
        "id": account_id,
        "name": "ChatGPT 账号",
        "api_key": None,
        "oauth": True,
        "refresh_token": tokens.get("refresh_token"),
        "access_token": tokens.get("access_token"),
        "id_token": tokens.get("id_token"),
        "base_url": None,
        "models": None,
    }
    accounts = state.setdefault("accounts", {}).setdefault("codex", [])
    accounts[:] = [a for a in accounts if a.get("id") != account_id]
    accounts.append(account)
    if not state.get("active_provider"):
        state["active_provider"] = "codex"
        state["active_account"] = account_id
    elif state.get("active_provider") == "codex" and not state.get("active_account"):
        state["active_account"] = account_id
    _save_state(state)

    with _pending_lock:
        _pending_device_codes.pop(device_code, None)

    return {"status": "success", "account": _account_view(account)}


@router.post("/test")
async def test_connection(request: TestRequest):
    """用当前（或指定）供应商发起一次最小 chat 请求测试连通（超时短，失败友好）。"""
    account = None
    meta = None
    if request.provider_id:
        state = _load_state()
        meta = _provider_meta(request.provider_id, state)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"未知供应商: {request.provider_id}")
        accounts = state.get("accounts", {}).get(request.provider_id, [])
        if request.account_id:
            account = next((a for a in accounts if a.get("id") == request.account_id), None)
        else:
            account = accounts[0] if accounts else None
    else:
        creds = resolve_active_credentials()
        if creds is None:
            return {"ok": False, "message": "尚未配置当前启用的 AI 供应商"}
        state = _load_state()
        meta = _provider_meta(creds["provider_id"], state)
        account = {
            "id": creds.get("account_id"),
            "api_key": creds.get("api_key"),
            "access_token": creds.get("access_token"),
            "base_url": creds.get("base_url"),
            "models": None,
        }

    if account is None:
        return {"ok": False, "message": "该供应商下还没有账号，请先添加账号或登录"}

    base_url = (account.get("base_url") or meta.get("base_url") or "").rstrip("/")
    if not base_url:
        return {"ok": False, "message": "未配置 Base URL"}

    api_key = account.get("api_key")
    access_token = account.get("access_token")
    api_format = meta.get("api_format", "openai")

    if meta.get("oauth") and not api_key:
        return {"ok": False, "message": "OAuth 账号测试暂不支持（请在 Codex 中验证该账号）"}

    models = account.get("models") or meta.get("default_models") or []
    model = models[0] if models else None
    if not model:
        return {"ok": False, "message": "未配置模型"}

    started = time.time()
    try:
        if api_format == "anthropic":
            url = base_url + "/messages"
            payload = {"model": model, "max_tokens": 1,
                       "messages": [{"role": "user", "content": "ping"}]}
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
            status, resp = _http_json_post(url, payload, headers, 8)
        else:
            url = base_url + "/chat/completions"
            payload = {"model": model, "max_tokens": 1,
                       "messages": [{"role": "user", "content": "ping"}]}
            headers = {"Authorization": "Bearer " + (api_key or access_token or "")}
            status, resp = _http_json_post(url, payload, headers, 8)
    except Exception as exc:  # noqa: BLE001 - 网络错误统一转友好提示
        return {"ok": False, "message": "连接失败: " + str(exc)}

    latency_ms = int((time.time() - started) * 1000)
    if 200 <= status < 300:
        return {"ok": True, "message": "连接成功", "status_code": status, "latency_ms": latency_ms}
    detail = ""
    if isinstance(resp, dict):
        err = resp.get("error")
        if isinstance(err, dict):
            detail = err.get("message") or ""
        elif isinstance(err, str):
            detail = err
    return {"ok": False, "message": "请求失败 (HTTP " + str(status) + ")", "status_code": status,
            "detail": detail, "latency_ms": latency_ms}


def _slugify(name: str) -> str:
    """把名称转成合法的自定义供应商 id（小写字母/数字/连字符）。"""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return slug[:40]

