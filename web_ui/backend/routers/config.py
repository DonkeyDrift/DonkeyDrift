from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os
from donkeycar import load_config
import logging
import tkinter as tk
from tkinter import filedialog
from starlette.concurrency import run_in_threadpool
from network_utils import discover_hosts

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
    else:
        path = os.path.expanduser(path)
    
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
    path = os.path.expanduser(request.path)
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
    path = os.path.expanduser(request.path)
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
    path = os.path.expanduser(request.path)
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


@router.post("/discover_simulator")
async def discover_simulator(request: SimulatorDiscoverRequest):
    """Scan the local network for DonkeySim instances listening on port 9091."""
    try:
        found, scanned = await discover_hosts(port=SIMULATOR_DEFAULT_PORT)
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
    path = os.path.expanduser(request.path)
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
