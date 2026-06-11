from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
from donkeycar import load_config
import logging
import tkinter as tk
from tkinter import filedialog
from starlette.concurrency import run_in_threadpool
import asyncio
import socket
import subprocess
import re

router = APIRouter()
logger = logging.getLogger(__name__)

TRAINING_CONFIG_KEYS = [
    'BATCH_SIZE',
    'TRAIN_TEST_SPLIT',
    'MAX_EPOCHS',
    'SHOW_PLOT',
    'USE_EARLY_STOP',
    'EARLY_STOP_PATIENCE',
    'LEARNING_RATE',
    'CREATE_TF_LITE',
    'PRUNE_VAL_LOSS_DEGRADATION_LIMIT',
]

SIMULATOR_CONFIG_KEYS = [
    'SIM_HOST',
    'DONKEY_GYM',
    'DONKEY_SIM_PATH',
    'DONKEY_GYM_ENV_NAME',
    'SIM_ARTIFICIAL_LATENCY',
]

class ConfigLoadRequest(BaseModel):
    path: str

class TrainingConfigSaveRequest(BaseModel):
    path: str
    enabled: bool
    config: dict

class SimulatorDiscoverRequest(BaseModel):
    car_path: str | None = None

class SimulatorSaveRequest(BaseModel):
    path: str
    config: dict

def _open_directory_dialog():
    try:
        root = tk.Tk()
        root.withdraw()
        # Try to bring the dialog to the front
        root.attributes('-topmost', True)
        directory = filedialog.askdirectory()
        root.destroy()
        return directory
    except Exception as e:
        logger.error(f"Error opening directory dialog: {e}")
        return None

@router.get("/select_directory")
async def select_directory():
    """
    Opens a native directory selection dialog and returns the selected path.
    This works when the backend is running on a machine with a GUI.
    """
    try:
        path = await run_in_threadpool(_open_directory_dialog)
        return {"path": path}
    except Exception as e:
        logger.error(f"Failed to select directory: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/browser")
async def list_directories(path: str = None):
    """
    List directories in the given path for web-based file browser.
    If path is None, return directories in the user home.
    """
    if not path:
        path = os.path.expanduser("~")
    
    path = os.path.abspath(path)
    if not os.path.exists(path) or not os.path.isdir(path):
        raise HTTPException(status_code=404, detail="Directory not found")
        
    try:
        dirs = []
        for d in os.listdir(path):
            try:
                d_path = os.path.join(path, d)
                if os.path.isdir(d_path) and not d.startswith('.'):
                    dirs.append(d)
            except PermissionError:
                continue
        dirs.sort()
        parent = os.path.dirname(path)
        return {
            "current": path,
            "parent": parent if parent != path else None,
            "directories": dirs
        }
    except Exception as e:
        logger.error(f"Failed to list directories: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/load")
async def load_config_route(request: ConfigLoadRequest):
    path = request.path
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Directory not found")
    
    config_path = os.path.join(path, 'config.py')
    if not os.path.exists(config_path):
        raise HTTPException(status_code=404, detail="config.py not found in directory")

    try:
        cfg = load_config(config_path)
        config_dict = {}
        for key in dir(cfg):
            if key.isupper():
                val = getattr(cfg, key)
                if isinstance(val, (str, int, float, bool, list, dict, tuple)) and not key.startswith('__'):
                    config_dict[key] = val

        return {
            "status": True,
            "message": f"Config loaded from {path}",
            "config": config_dict
        }
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/load_myconfig")
async def load_myconfig_route(request: ConfigLoadRequest):
    """Load only myconfig.py (without merging config.py defaults)."""
    path = request.path
    myconfig_path = os.path.join(path, 'myconfig.py')

    if not os.path.exists(myconfig_path):
        return {"status": True, "config": {}}

    try:
        from donkeycar.config import Config
        cfg = Config()
        cfg.from_pyfile(myconfig_path)

        config_dict = {}
        for key in dir(cfg):
            if key.isupper():
                val = getattr(cfg, key)
                if isinstance(val, (str, int, float, bool, list, dict, tuple)) and not key.startswith('__'):
                    config_dict[key] = val

        return {
            "status": True,
            "message": f"myconfig loaded from {path}",
            "config": config_dict
        }
    except Exception as e:
        logger.error(f"Failed to load myconfig: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save_training")
async def save_training_config(request: TrainingConfigSaveRequest):
    """Save or remove training-related config keys in myconfig.py."""
    path = request.path
    myconfig_path = os.path.join(path, 'myconfig.py')

    lines = []
    if os.path.exists(myconfig_path):
        with open(myconfig_path, 'r') as f:
            lines = f.read().splitlines()

    if request.enabled:
        for key in TRAINING_CONFIG_KEYS:
            if key not in request.config:
                continue
            val = request.config[key]
            if isinstance(val, str):
                val_str = f'"{val}"'
            else:
                val_str = str(val)

            new_line = f'{key} = {val_str}'
            found = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith(key) and '=' in stripped:
                    lines[i] = new_line
                    found = True
                    break
            if not found:
                lines.append(new_line)
    else:
        lines = [
            line for line in lines
            if not any(
                line.strip().startswith(k) and '=' in line.strip()
                for k in TRAINING_CONFIG_KEYS
            )
        ]

    with open(myconfig_path, 'w') as f:
        f.write('\n'.join(lines))
        if lines and not lines[-1].endswith('\n'):
            f.write('\n')

    return {"status": True, "message": f"Training config saved to {myconfig_path}"}


# ---------------------------------------------------------------------------
# Simulator discovery helpers
# ---------------------------------------------------------------------------

SIMULATOR_DEFAULT_PORT = 9091
DISCOVER_TIMEOUT = 0.4          # seconds per host
DISCOVER_MAX_CONCURRENT = 64    # concurrent connection attempts


async def _check_host_port(host: str, port: int, timeout: float = DISCOVER_TIMEOUT):
    """Try to open a TCP connection to host:port and return latency info."""
    try:
        loop = asyncio.get_event_loop()
        start = loop.time()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        latency = (loop.time() - start) * 1000
        return {"ip": host, "port": port, "latency_ms": round(latency, 1), "reachable": True}
    except Exception:
        return None


def _get_default_gateway():
    """Return the default gateway IP (WSL2 host or router)."""
    try:
        result = subprocess.run(
            ['ip', 'route', 'show'], capture_output=True, text=True
        )
        if result.returncode == 0:
            match = re.search(r'default via (\d+\.\d+\.\d+\.\d+)', result.stdout)
            if match:
                return match.group(1)
    except Exception:
        pass
    return None


def _get_local_subnet():
    """Return the LAN subnet prefix of the primary interface, if any."""
    # 1. Try psutil for any RFC1918 local subnet
    try:
        import psutil
        addrs = psutil.net_if_addrs()
        for iface, addr_list in addrs.items():
            for addr in addr_list:
                if addr.family == socket.AF_INET:
                    ip = addr.address
                    # Prefer 192.168.x.x, also accept 10.x.x.x or 172.16-31.x.x
                    if ip.startswith("192.168.") or ip.startswith("10."):
                        parts = ip.split('.')
                        return f"{parts[0]}.{parts[1]}.{parts[2]}"
                    if ip.startswith("172."):
                        second = int(ip.split('.')[1])
                        if 16 <= second <= 31:
                            parts = ip.split('.')
                            return f"{parts[0]}.{parts[1]}.{parts[2]}"
    except Exception:
        pass

    # 2. Fallback: parse 'ip route' for RFC1918 source addresses
    try:
        result = subprocess.run(
            ['ip', 'route', 'show'], capture_output=True, text=True
        )
        for line in result.stdout.splitlines():
            match = re.search(r'src\s+(\d+\.\d+\.\d+\.\d+)', line)
            if match:
                ip = match.group(1)
                if ip.startswith("192.168.") or ip.startswith("10."):
                    parts = ip.split('.')
                    return f"{parts[0]}.{parts[1]}.{parts[2]}"
                if ip.startswith("172."):
                    second = int(ip.split('.')[1])
                    if 16 <= second <= 31:
                        parts = ip.split('.')
                        return f"{parts[0]}.{parts[1]}.{parts[2]}"
    except Exception:
        pass

    # 3. WSL fallback: use ipconfig.exe to find Windows LAN subnet
    try:
        result = subprocess.run(['ipconfig.exe'], capture_output=True)
        if result.returncode == 0:
            output = result.stdout
            try:
                text = output.decode('gbk')
            except Exception:
                text = output.decode('utf-8', errors='ignore')
            for line in text.splitlines():
                if "IPv4" in line or "IP Address" in line:
                    match = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
                    if match:
                        ip = match.group(1)
                        if ip.startswith("192.168.") or ip.startswith("10."):
                            parts = ip.split('.')
                            return f"{parts[0]}.{parts[1]}.{parts[2]}"
                        if ip.startswith("172."):
                            second = int(ip.split('.')[1])
                            if 16 <= second <= 31:
                                parts = ip.split('.')
                                return f"{parts[0]}.{parts[1]}.{parts[2]}"
    except Exception:
        pass

    return None


def _get_wsl_host_ip():
    """Get the WSL2 Windows host IP from /etc/resolv.conf (nameserver)."""
    try:
        with open('/etc/resolv.conf', 'r') as f:
            content = f.read()
            match = re.search(r'nameserver\s+(\d+\.\d+\.\d+\.\d+)', content)
            if match:
                return match.group(1)
    except Exception:
        pass
    return None


async def _discover_simulator_hosts(port: int = SIMULATOR_DEFAULT_PORT):
    """Scan common addresses and the local /24 subnet for open simulator ports."""
    candidates = []

    # 1. Always check localhost first
    candidates.append("127.0.0.1")

    # 2. Check default gateway and its /24 subnet
    gw = _get_default_gateway()
    if gw and gw not in candidates:
        candidates.append(gw)
        # Also scan the gateway's /24 subnet (e.g. 172.21.48.x in WSL2)
        gw_parts = gw.split('.')
        if len(gw_parts) == 4:
            gw_subnet = f"{gw_parts[0]}.{gw_parts[1]}.{gw_parts[2]}"
            for i in range(1, 255):
                ip = f"{gw_subnet}.{i}"
                if ip not in candidates:
                    candidates.append(ip)

    # 3. WSL2 /etc/resolv.conf nameserver (another way to reach Windows host)
    wsl_host = _get_wsl_host_ip()
    if wsl_host and wsl_host not in candidates:
        candidates.append(wsl_host)

    # 4. If we have a LAN subnet, scan it
    subnet = _get_local_subnet()
    if subnet:
        for i in range(1, 255):
            ip = f"{subnet}.{i}"
            if ip not in candidates:
                candidates.append(ip)

    # 5. Fallback: scan common home router subnets when no LAN subnet found
    #    (e.g. WSL where ipconfig.exe is unavailable)
    if not subnet:
        common_subnets = ["192.168.0", "192.168.1", "192.168.3", "192.168.31", "192.168.50"]
        for cs in common_subnets:
            for i in range(1, 255):
                ip = f"{cs}.{i}"
                if ip not in candidates:
                    candidates.append(ip)
            if len(candidates) >= 500:
                break

    # 6. Cap total candidates to avoid excessive scanning
    if len(candidates) > 500:
        candidates = candidates[:500]

    semaphore = asyncio.Semaphore(DISCOVER_MAX_CONCURRENT)

    async def _probe(host):
        async with semaphore:
            return await _check_host_port(host, port)

    tasks = [_probe(host) for host in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    found = []
    for r in results:
        if isinstance(r, dict) and r.get("reachable"):
            found.append(r)

    # Sort by latency (fastest first)
    found.sort(key=lambda x: x["latency_ms"])
    return found, len(candidates)


@router.post("/discover_simulator")
async def discover_simulator(request: SimulatorDiscoverRequest):
    """Scan the local network for DonkeySim instances listening on port 9091."""
    try:
        found, scanned = await _discover_simulator_hosts()
        message = ""
        if not found:
            message = f"扫描了 {scanned} 个地址，未在局域网中发现 DonkeySim。请确认模拟器已启动（donkey sim --path <sim.exe>），并确保它监听所有网络接口（0.0.0.0:9091）。"
        else:
            message = f"扫描了 {scanned} 个地址，发现 {len(found)} 个可用模拟器。"
        return {"status": True, "found": found, "count": len(found), "scanned": scanned, "message": message}
    except Exception as e:
        logger.error(f"Simulator discovery failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save_simulator")
async def save_simulator_config(request: SimulatorSaveRequest):
    """Save simulator-related config keys in myconfig.py."""
    path = request.path
    myconfig_path = os.path.join(path, 'myconfig.py')

    lines = []
    if os.path.exists(myconfig_path):
        with open(myconfig_path, 'r') as f:
            lines = f.read().splitlines()

    for key in SIMULATOR_CONFIG_KEYS:
        if key not in request.config:
            continue
        val = request.config[key]
        if isinstance(val, str):
            val_str = f'"{val}"'
        else:
            val_str = str(val)

        new_line = f'{key} = {val_str}'
        found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(key) and '=' in stripped:
                lines[i] = new_line
                found = True
                break
        if not found:
            lines.append(new_line)

    with open(myconfig_path, 'w') as f:
        f.write('\n'.join(lines))
        if lines and not lines[-1].endswith('\n'):
            f.write('\n')

    return {"status": True, "message": f"Simulator config saved to {myconfig_path}"}
