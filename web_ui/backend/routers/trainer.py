"""
Trainer API Router - exposes training configuration, job management, and SSE log streaming.
"""
import asyncio
import configparser
import json
import os
import re
import shutil
import socket
import subprocess
import threading
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from trainer_engine import job_manager
from mypc_history import load_known_hosts, save_known_host
from mypc_probe import probe_mypc_environment
router = APIRouter()

# ------------------------------------------------------------------
# Pydantic models
# ------------------------------------------------------------------
class TrainerConfig(BaseModel):
    host: str
    user: str
    remote_dir_base: str
    model_name: str
    python_path: str
    model_type: str = "linear"


class SSHCredentials(BaseModel):
    """SSH 连接凭据，仅在训练请求会话内传递，不落盘、不入库。"""
    host: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    key_filename: Optional[str] = None


class LocalTrainRequest(BaseModel):
    tub: str = "./data"
    model: str
    model_type: str = "linear"
    transfer: Optional[str] = None
    working_dir: Optional[str] = None


class OnlineTrainRequest(BaseModel):
    config_file: str = "train_online.conf"
    working_dir: Optional[str] = None
    ssh: Optional[SSHCredentials] = None
    tub: Optional[str] = None


class MyPcTrainRequest(BaseModel):
    config_file: str = "train_my_pc.conf"
    working_dir: Optional[str] = None
    ssh: Optional[SSHCredentials] = None
    tub: Optional[str] = None


class MyPcProbeRequest(BaseModel):
    host: str
    user: str
    password: str = ""
    port: int = 22
    remote_dir_base: str = "~/projects"
    python_path: str = ""
    key_path: str = ""


class MyPcInstallRequest(BaseModel):
    """一键安装训练依赖：需要 probe 探测到的 python 路径。"""
    host: str
    user: str
    password: str = ""
    port: int = 22
    python_path: str
    key_path: str = ""


class StopRequest(BaseModel):
    pass


class MyPcClientInfoRequest(BaseModel):
    """一键获取本机信息：密码仅用于 SSH 验证候选用户名。

    走 POST body 而非 GET query——query 会进访问日志，密码绝不能落日志。
    """
    password: str = ""


# ------------------------------------------------------------------
# Config endpoints
# ------------------------------------------------------------------
@router.get("/config")
async def get_trainer_config(config_file: str = "train_online.conf"):
    """Read train_online.conf and return as JSON."""
    path = os.path.abspath(config_file)
    if not os.path.exists(path):
        # Auto-create default config using OnlineTrainer logic
        from donkeycar.management.train_online import OnlineTrainer
        # Temporarily instantiate to trigger file creation
        _ = OnlineTrainer(config_file=path)

    config = configparser.ConfigParser()
    config.read(path)
    if "Remote" not in config.sections():
        raise HTTPException(status_code=500, detail="Invalid config file: missing [Remote] section")

    return {
        "path": path,
        "host": config["Remote"].get("host", ""),
        "user": config["Remote"].get("user", ""),
        # 密码不再返回给前端：凭据仅会话内传递，不落盘、不入库。
        "password": "",
        "remote_dir_base": config["Remote"].get("remote_dir_base", "~/projects"),
        "model_name": config["Remote"].get("model_name", "model"),
        "python_path": config["Remote"].get("python_path", "~/miniconda3/envs/donkey/bin/python"),
        "model_type": config["Remote"].get("model_type", "linear"),
    }


@router.post("/config")
async def set_trainer_config(cfg: TrainerConfig, config_file: str = "train_online.conf"):
    """Write train_online.conf from JSON payload."""
    path = os.path.abspath(config_file)
    config = configparser.ConfigParser()
    if os.path.exists(path):
        config.read(path)
    if "Remote" not in config.sections():
        config.add_section("Remote")

    config.set("Remote", "host", cfg.host)
    config.set("Remote", "user", cfg.user)
    config.set("Remote", "remote_dir_base", cfg.remote_dir_base)
    config.set("Remote", "model_name", cfg.model_name)
    config.set("Remote", "python_path", cfg.python_path)
    config.set("Remote", "model_type", cfg.model_type)

    with open(path, "w") as f:
        config.write(f)

    return {"status": True, "path": path}


@router.post("/mypc/probe")
async def probe_mypc(request: MyPcProbeRequest):
    """Pre-flight check for 'This Computer' (mypc) training.

    Connects to the user's computer over SSH and reports whether the target
    OS, Python interpreter, and donkeycar environment are ready, returning
    actionable fix hints for anything that is missing or misconfigured.
    Runs in a worker thread because Paramiko is blocking.
    """
    result = await asyncio.to_thread(
        probe_mypc_environment,
        host=request.host,
        user=request.user,
        password=request.password,
        remote_dir_base=request.remote_dir_base,
        python_path=request.python_path,
        port=request.port,
        key_path=request.key_path,
    )
    try:
        # SSH answered — remember this computer so the UI can pre-fill it.
        # 安全约束：只记 host/user/python_path/remote_dir_base，绝不记密码。
        if any(c.name == "ssh" and c.status == "ok" for c in result.checks):
            save_known_host(request.host, request.user, result.python_path,
                            request.remote_dir_base)
    except Exception:
        pass
    return {
        "ok": result.ok,
        "platform": result.platform,
        "shell": result.shell,
        "python_path": result.python_path,
        "checks": [
            {
                "name": c.name,
                "status": c.status,
                "message": c.message,
                "hint": c.hint,
            }
            for c in result.checks
        ],
        "suggestions": result.suggestions,
    }


@router.post("/mypc/install")
async def install_mypc(request: MyPcInstallRequest):
    """One-click dependency install for 'This Computer' (mypc) training.

    Requires a python path discovered by a prior /mypc/probe call; runs
    ``<python> -m pip install --upgrade "donkeydrifter[pc]"`` over SSH as a
    job whose logs stream through the shared /train/{job_id}/logs SSE
    endpoint (the job mode is 'mypc_install').
    """
    if not request.python_path or not request.python_path.strip():
        raise HTTPException(
            status_code=400,
            detail="缺少 Python 解释器路径，请先运行环境检测。",
        )

    job = job_manager.create_job("mypc_install")
    asyncio.create_task(
        job_manager.run_mypc_install(
            job,
            host=request.host,
            user=request.user,
            password=request.password,
            python_path=request.python_path,
            port=request.port,
            key_path=request.key_path,
        )
    )
    return {"job_id": job.id, "status": job.status}


# ------------------------------------------------------------------
# MyPC known hosts (history + SSH port reachability)
# ------------------------------------------------------------------
def _ssh_port_open(host: str, port: int = 22, timeout: float = 1.5) -> bool:
    """Best-effort TCP connect check for the SSH port. Never raises."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


@router.get("/mypc/known-hosts")
async def get_mypc_known_hosts():
    """Return remembered 'This Computer' hosts (most recently used first),
    each annotated with a `reachable` flag from a concurrent port-22 probe.
    Never fails: an empty/unreadable history just yields an empty list."""
    hosts = await asyncio.to_thread(load_known_hosts)
    flags = await asyncio.gather(
        *(asyncio.to_thread(_ssh_port_open, entry["host"]) for entry in hosts)
    )
    return {
        "hosts": [
            {**entry, "reachable": reachable}
            for entry, reachable in zip(hosts, flags)
        ]
    }


# ------------------------------------------------------------------
# MyPC client info (browser source) for host/user auto-fill
# ------------------------------------------------------------------
_DEVICE_WORDS = {
    "macbook", "mac", "imac", "mini", "pro", "air", "studio",
    "pc", "desktop", "laptop", "notebook", "windows", "win",
}


def _mdns_name_for_ip(ip: str, timeout: float = 2.5) -> str:
    """Resolve a LAN IP to a device name by browsing mDNS services.

    Browses common Bonjour service types (SSH, companion-link, SMB, ...)
    for `timeout` seconds, collecting (type, name) pairs only — the
    listener callbacks run on the zeroconf engine thread, so the blocking
    get_service_info calls happen afterwards on this thread instead.
    Returns the instance name (service suffix stripped) of the first
    service whose IPv4 addresses contain `ip`.
    zeroconf is imported lazily so the backend still starts without it.
    Never raises; returns "" on any failure.
    """
    try:
        from zeroconf import IPVersion, ServiceBrowser, ServiceListener, Zeroconf
    except Exception:
        return ""

    service_types = [
        "_ssh._tcp.local.",
        "_companion-link._tcp.local.",
        "_device-info._tcp.local.",
        "_smb._tcp.local.",
        "_afpovertcp._tcp.local.",
        "_airdrop._tcp.local.",
    ]

    found = []
    browse_done = threading.Event()

    class _Collector(ServiceListener):
        # Runs on the zeroconf engine thread: collect only, never block.
        def add_service(self, zc, type_, name):
            found.append((type_, name))

        def remove_service(self, zc, type_, name):
            pass

        def update_service(self, zc, type_, name):
            pass

    zc = None
    try:
        zc = Zeroconf()
        browser = ServiceBrowser(zc, service_types, _Collector())
        browse_done.wait(timeout)
        try:
            browser.cancel()
        except Exception:
            pass
        for type_, name in found:
            try:
                info = zc.get_service_info(type_, name, timeout=1000)
            except Exception:
                continue
            if not info:
                continue
            try:
                addrs = info.ip_addresses_by_version(IPVersion.V4Only)
            except Exception:
                continue
            if any(str(addr) == ip for addr in addrs):
                # "Daniel's MacBook Pro._ssh._tcp.local." -> "Daniel's MacBook Pro"
                return re.sub(
                    r"(\._[a-z0-9-]+\._(tcp|udp)\.local\.)+$",
                    "", name, flags=re.IGNORECASE,
                )
    except Exception:
        return ""
    finally:
        if zc is not None:
            try:
                zc.close()
            except Exception:
                pass
    return ""


def _reverse_resolve(ip: str) -> str:
    """Best-effort reverse resolution of a LAN IP to a hostname.

    Prefers mDNS service browsing via zeroconf (resolves Macs on the LAN
    even without avahi and where NSS mdns4_minimal cannot do reverse PTR
    for 192.0.2.x-style LAN addresses); falls back to avahi-resolve-address,
    then getent hosts. Blocking — must be run via asyncio.to_thread.
    Never raises; returns "" on any failure.
    """
    try:
        name = _mdns_name_for_ip(ip)
        if name:
            return name
        if shutil.which("avahi-resolve-address"):
            proc = subprocess.run(
                ["avahi-resolve-address", "-a", ip],
                capture_output=True, text=True, timeout=2,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                # Output: "<ip>\t<hostname>"
                return proc.stdout.splitlines()[0].split()[-1].strip()
        elif shutil.which("getent"):
            proc = subprocess.run(
                ["getent", "hosts", ip],
                capture_output=True, text=True, timeout=2,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                # Output: "<ip>  <hostname> [aliases...]"
                parts = proc.stdout.splitlines()[0].split()
                if len(parts) >= 2:
                    return parts[1].strip()
    except Exception:
        pass
    return ""


def _guess_username(hostname: str) -> str:
    """Guess a login username from a hostname like 'Daniels-MacBook-Pro'."""
    name = hostname.lower()
    if name.endswith(".local"):
        name = name[:-len(".local")]
    for token in re.split(r"[^a-z0-9]+", name):
        if not token or token in _DEVICE_WORDS:
            continue
        if token.endswith("s") and len(token) > 3:
            # macOS default naming uses the possessive ('Daniels-MacBook-Pro')
            token = token[:-1]
        return token
    return ""


def _username_candidates(hostname: str, guess: str) -> List[str]:
    """Build an ordered, de-duplicated list of candidate login usernames.

    `guess` (the possessive-stripped _guess_username result) comes first;
    `raw` is the first non-device token of the hostname (lowercased,
    split on non-alphanumerics, .local stripped) without possessive
    stripping. Empty entries are dropped.
    """
    raw = ""
    name = hostname.lower()
    if name.endswith(".local"):
        name = name[:-len(".local")]
    for token in re.split(r"[^a-z0-9]+", name):
        if token and token not in _DEVICE_WORDS:
            raw = token
            break
    candidates: List[str] = []
    for cand in (guess, raw):
        if cand and cand not in candidates:
            candidates.append(cand)
    return candidates


def _verify_username_via_ssh(ip: str, candidates: List[str], password: str) -> tuple:
    """Really SSH-login to `ip` with each candidate username + password.

    Returns (verified_username, ssh_status) where ssh_status is one of
    'ok' / 'auth_failed' / 'unreachable'. On success the authoritative
    username is the remote `whoami` output. Authentication failures try
    the next candidate; any connection-level error aborts immediately
    as 'unreachable'. Blocking — must be run via asyncio.to_thread.
    paramiko is imported lazily so the backend still starts without it.
    """
    import paramiko

    for cand in candidates[:3]:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                ip, port=22, username=cand, password=password,
                timeout=4, banner_timeout=4, auth_timeout=4,
                look_for_keys=False, allow_agent=False,
            )
            _, stdout, _ = client.exec_command("whoami", timeout=3)
            name = stdout.read().decode(errors="replace").strip()
            return (name or cand, "ok")
        except paramiko.AuthenticationException:
            continue
        except Exception:
            return ("", "unreachable")
        finally:
            try:
                client.close()
            except Exception:
                pass
    return ("", "auth_failed")


@router.post("/mypc/client-info")
async def get_mypc_client_info(request: Request, body: MyPcClientInfoRequest):
    """Return the browser client's IP, reverse-resolved hostname, and a
    best-effort username guess for the Trainer page 'This Computer' mode
    auto-fill. Never fails: resolution is capped at 6s overall and any
    error just yields empty strings.

    POST with a JSON body (not GET query) so the optional `password` never
    lands in access logs. When `password` is given (and the client is not
    loopback), candidate usernames are verified by real SSH login:
    `verified` is True only on success (username then comes from remote
    `whoami`), and `ssh` reports 'ok' / 'auth_failed' / 'unreachable'
    ('' when not attempted).
    """
    password = body.password
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    elif request.client:
        ip = request.client.host
    else:
        ip = ""

    is_loopback = ip in ("127.0.0.1", "::1", "localhost")

    hostname = ""
    if ip and not is_loopback:
        try:
            hostname = await asyncio.wait_for(
                asyncio.to_thread(_reverse_resolve, ip), timeout=6.0
            )
        except Exception:
            hostname = ""

    username = _guess_username(hostname) if hostname else ""
    verified = False
    ssh = ""

    candidates = _username_candidates(hostname, username) if hostname else []
    if password and ip and not is_loopback and candidates:
        try:
            verified_name, ssh = await asyncio.wait_for(
                asyncio.to_thread(_verify_username_via_ssh, ip, candidates, password),
                timeout=15.0,
            )
            if ssh == "ok" and verified_name:
                username = verified_name
                verified = True
        except Exception:
            verified = False
            ssh = ""

    return {
        "ip": ip,
        "is_loopback": is_loopback,
        "hostname": hostname,
        "username": username,
        "verified": verified,
        "ssh": ssh,
    }


# ------------------------------------------------------------------
# Model / Backup listing
# ------------------------------------------------------------------
def _get_dir_size(path: str) -> int:
    """Recursively calculate total size of a directory."""
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    return total


@router.get("/tubs")
async def list_tubs(working_dir: Optional[str] = None):
    """List candidate tub directories for local training.

    Scans <working_dir>/data itself plus every subdirectory of it that has a
    manifest.json (covers data/tub_xxx unpacked archives), and sibling
    <working_dir>/data* directories. Returns relative (./data style) and
    absolute paths plus the currently loaded tub path, so the Trainer page
    can pre-select the right tub automatically.
    """
    cwd = working_dir or os.getcwd()
    tubs: List[dict] = []

    def _add_tub(full_path: str):
        rel = os.path.relpath(full_path, cwd)
        display = "./" + rel if not rel.startswith(".") else rel
        tubs.append({
            "name": os.path.basename(full_path) or full_path,
            "relative_path": display,
            "absolute_path": os.path.abspath(full_path),
        })

    def _is_tub(path: str) -> bool:
        return os.path.isfile(os.path.join(path, "manifest.json"))

    candidates: List[str] = []
    data_dir = os.path.join(cwd, "data")
    if os.path.isdir(data_dir):
        candidates.append(data_dir)
        try:
            for name in sorted(os.listdir(data_dir)):
                sub = os.path.join(data_dir, name)
                if os.path.isdir(sub):
                    candidates.append(sub)
        except OSError:
            pass
    if os.path.isdir(cwd):
        try:
            for name in sorted(os.listdir(cwd)):
                full = os.path.join(cwd, name)
                if name != "data" and name.startswith("data") and os.path.isdir(full):
                    candidates.append(full)
        except OSError:
            pass

    seen = set()
    for path in candidates:
        if _is_tub(path):
            key = os.path.abspath(path)
            if key not in seen:
                seen.add(key)
                _add_tub(path)

    from routers.tub import current_tub_path

    return {
        "tubs": tubs,
        "current_tub_path": current_tub_path,
    }


@router.get("/models")
async def list_models(working_dir: Optional[str] = None):
    """List local .tflite models in ./models directory.

    Only .tflite files are shown. Training loss charts (.png) are hidden
    from the list but linked to their corresponding model via previewPath.
    """
    cwd = working_dir or os.getcwd()
    models_dir = os.path.join(cwd, "models")
    items: List[dict] = []
    if not os.path.isdir(models_dir):
        return {"models": items}

    # Build a set of existing .png files for quick lookup
    png_files = {
        n for n in os.listdir(models_dir)
        if n.endswith(".png") and os.path.isfile(os.path.join(models_dir, n))
    }

    for name in sorted(os.listdir(models_dir)):
        full = os.path.join(models_dir, name)
        # Only show .tflite model files
        if not (os.path.isfile(full) and name.endswith(".tflite")):
            continue

        stem = os.path.splitext(name)[0]
        preview_name = f"{stem}.png"
        preview_path = (
            os.path.abspath(os.path.join(models_dir, preview_name))
            if preview_name in png_files
            else None
        )

        # Read loss metadata if available
        meta_path = os.path.join(models_dir, f"{stem}_meta.json")
        loss_info = {}
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r") as f:
                    loss_info = json.load(f)
            except Exception:
                pass

        stat = os.stat(full)
        items.append({
            "name": name,
            "type": "file",
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "path": os.path.abspath(full),
            "previewPath": preview_path,
            "finalLoss": loss_info.get("final_loss"),
            "bestLoss": loss_info.get("best_loss"),
        })
    return {"models": items}


@router.get("/models/preview")
async def get_model_preview(path: str = Query(..., description="Absolute path to the .png preview image")):
    """Serve a model training loss chart (.png) for preview in the UI."""
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Preview file not found")
    if not path.lower().endswith(".png"):
        raise HTTPException(status_code=400, detail="Only .png previews are supported")
    return FileResponse(path, media_type="image/png")


@router.get("/models/download")
async def download_model(path: str = Query(..., description="Absolute path to the model file")):
    """Download a model file as attachment."""
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Model file not found")
    if not path.lower().endswith(".tflite"):
        raise HTTPException(status_code=400, detail="Only .tflite model files are supported")
    filename = os.path.basename(path)
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=filename,
    )


@router.delete("/models")
async def delete_model(path: str = Query(..., description="Absolute path to the model file")):
    """Delete a model file and its associated preview image and metadata."""
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Model file not found")
    if not path.lower().endswith(".tflite"):
        raise HTTPException(status_code=400, detail="Only .tflite model files are supported")

    # Remove the main model file
    os.remove(path)

    # Remove associated files (preview .png and _meta.json) if they exist
    stem = os.path.splitext(path)[0]
    for suffix in (".png", "_meta.json"):
        associated_path = f"{stem}{suffix}"
        if os.path.isfile(associated_path):
            try:
                os.remove(associated_path)
            except Exception:
                pass

    return {"status": True, "path": path}


@router.post("/models/import")
async def import_model(
    file: UploadFile = File(...),
    working_dir: Optional[str] = Form(None),
):
    """Import (upload) a .tflite model into <working_dir>/models.

    Mirrors list_models' working_dir resolution so the uploaded file lands in
    exactly the directory the Trainer page lists. Rejects non-.tflite files
    and duplicate names (no silent overwrite).
    """
    filename = os.path.basename(file.filename or "")
    if not filename:
        raise HTTPException(status_code=400, detail="No file selected")
    if not filename.lower().endswith(".tflite"):
        raise HTTPException(status_code=400, detail="Only .tflite model files are supported")

    cwd = working_dir or os.getcwd()
    models_dir = os.path.join(cwd, "models")
    os.makedirs(models_dir, exist_ok=True)

    dest = os.path.join(models_dir, filename)
    if os.path.exists(dest):
        raise HTTPException(status_code=409, detail=f"Model already exists: {filename}")

    size = 0
    with open(dest, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            size += len(chunk)

    return {
        "status": True,
        "name": filename,
        "path": os.path.abspath(dest),
        "size": size,
    }


@router.get("/backups")
async def list_backups(working_dir: Optional[str] = None):
    """List data backup archives in ./data_cache."""
    cwd = working_dir or os.getcwd()
    cache_dir = os.path.join(cwd, "data_cache")
    items: List[dict] = []
    if os.path.isdir(cache_dir):
        for name in sorted(os.listdir(cache_dir)):
            if name.endswith(".tar.gz"):
                full = os.path.join(cache_dir, name)
                stat = os.stat(full)
                items.append({
                    "name": name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "path": os.path.abspath(full),
                })
    return {"backups": items}


# ------------------------------------------------------------------
# Job management
# ------------------------------------------------------------------
@router.post("/train/local")
async def start_local_train(request: LocalTrainRequest):
    job = job_manager.create_job("local")
    asyncio.create_task(
        job_manager.run_local(
            job,
            tub=request.tub,
            model=request.model,
            model_type=request.model_type,
            transfer=request.transfer,
            working_dir=request.working_dir,
        )
    )
    return {"job_id": job.id, "status": job.status}


@router.post("/train/online")
async def start_online_train(request: OnlineTrainRequest):
    job = job_manager.create_job("online")
    asyncio.create_task(
        job_manager.run_online(
            job,
            config_file=request.config_file,
            working_dir=request.working_dir,
            ssh_credentials=request.ssh.model_dump() if request.ssh else None,
            tub=request.tub,
        )
    )
    return {"job_id": job.id, "status": job.status}


def _remember_mypc_host(request: MyPcTrainRequest) -> None:
    """开始/续训成功后记住这台电脑，供前端下次自动填充。

    python_path / remote_dir_base 从 conf 读（与 get_trainer_config 同一路径
    解析方式）；安全约束：只记 host/user/python_path/remote_dir_base，
    绝不记密码。任何失败都吞掉，绝不影响训练主流程。
    """
    try:
        if not request.ssh or not request.ssh.host:
            return
        python_path = ""
        remote_dir_base = ""
        conf_path = os.path.abspath(request.config_file)
        if os.path.exists(conf_path):
            conf = configparser.ConfigParser()
            conf.read(conf_path)
            if "Remote" in conf.sections():
                python_path = conf["Remote"].get("python_path", "")
                remote_dir_base = conf["Remote"].get("remote_dir_base", "")
        save_known_host(
            request.ssh.host,
            request.ssh.user or "",
            python_path,
            remote_dir_base,
        )
    except Exception:
        pass


@router.post("/train/mypc")
async def start_mypc_train(request: MyPcTrainRequest):
    """Train on the user's own computer via SSH callback (train_my_pc.conf)."""
    job = job_manager.create_job("mypc")
    asyncio.create_task(
        job_manager.run_mypc(
            job,
            config_file=request.config_file,
            working_dir=request.working_dir,
            ssh_credentials=request.ssh.model_dump() if request.ssh else None,
            tub=request.tub,
        )
    )
    _remember_mypc_host(request)
    return {"job_id": job.id, "status": job.status}


@router.post("/train/mypc/resume")
async def start_mypc_resume_train(request: MyPcTrainRequest):
    """mypc 断点续训：从上次训练留下的最优权重继续训练（train_my_pc.conf）。

    请求体与响应结构与 /train/mypc 完全一致；没有可续训的历史训练
    （或训练数据已变化）时自动回退为全新训练。
    """
    job = job_manager.create_job("mypc")
    asyncio.create_task(
        job_manager.run_mypc_resume(
            job,
            config_file=request.config_file,
            working_dir=request.working_dir,
            ssh_credentials=request.ssh.model_dump() if request.ssh else None,
            tub=request.tub,
        )
    )
    _remember_mypc_host(request)
    return {"job_id": job.id, "status": job.status}


@router.get("/train/{job_id}/status")
async def get_job_status(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job.id,
        "mode": job.mode,
        "status": job.status,
        "progress": {
            "currentEpoch": job.progress.current_epoch,
            "totalEpochs": job.progress.total_epochs,
            "currentStep": job.progress.current_step,
            "totalSteps": job.progress.total_steps,
            "loss": job.progress.loss,
            "globalPercent": job.progress.global_percent,
        },
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error_message,
    }


@router.post("/train/{job_id}/stop")
async def stop_train(job_id: str):
    job_manager.stop_job(job_id)
    return {"job_id": job_id, "status": "stopped"}


# ------------------------------------------------------------------
# SSE log streaming
# ------------------------------------------------------------------
async def _sse_event_generator(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        yield f"data: {json.dumps({'type': 'error', 'message': 'Job not found'})}\n\n"
        return

    # Yield initial status
    yield f"data: {json.dumps({'type': 'status', 'status': job.status})}\n\n"

    while True:
        try:
            msg = await asyncio.wait_for(job.log_queue.get(), timeout=1.0)
            yield f"data: {json.dumps(msg)}\n\n"
            if msg.get("type") == "status" and msg.get("status") in ("completed", "failed", "stopped"):
                break
        except asyncio.TimeoutError:
            # Send keep-alive heartbeat
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
            # If job finished while we were waiting, exit
            if job.status in ("completed", "failed", "stopped"):
                break


@router.get("/train/{job_id}/logs")
async def stream_logs(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return StreamingResponse(
        _sse_event_generator(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
