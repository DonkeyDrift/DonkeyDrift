from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import json
import os
from donkeycar import load_config
from donkeycar._version import __version__
import logging
import tkinter as tk
from tkinter import filedialog
from starlette.concurrency import run_in_threadpool
from network_utils import discover_hosts

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/version")
async def get_version():
    """Return the DonkeyDrifter version string."""
    return {"version": __version__}


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

# 自动发现 mycar 项目时跳过的目录名（隐藏目录另行按前缀排除）
PROJECT_SCAN_SKIP_DIRS = {'node_modules', 'venv', '.venv', '__pycache__', 'site-packages'}

# 从扫描根算起向下最多再探几层（root/Projects/mycar 为 2 层）
PROJECT_SCAN_MAX_DEPTH = 2


def find_car_projects(root, max_depth=PROJECT_SCAN_MAX_DEPTH):
    """广度优先扫描 root 下含 config.py 与 manage.py 的 mycar 项目目录。

    命中的目录不再继续下钻；隐藏目录与 node_modules 等跳过。
    """
    projects = []
    root = os.path.abspath(os.path.expanduser(root))
    current = [root]
    for _ in range(max_depth + 1):
        next_level = []
        for dir_path in current:
            if os.path.isfile(os.path.join(dir_path, 'config.py')) and \
                    os.path.isfile(os.path.join(dir_path, 'manage.py')):
                projects.append(dir_path)
                continue
            try:
                entries = os.listdir(dir_path)
            except OSError:
                continue
            for name in entries:
                if name.startswith('.') or name in PROJECT_SCAN_SKIP_DIRS:
                    continue
                sub = os.path.join(dir_path, name)
                if os.path.isdir(sub):
                    next_level.append(sub)
        current = next_level
        if not current:
            break
    projects.sort()
    return projects


# 记录“上次成功加载的 mycar 项目”的状态文件（跨浏览器/设备记忆，
# 命名惯例参考 connector 的 ~/.donkeycar_web_connector.json）
def _loader_state_path():
    return os.path.join(os.path.expanduser("~"), ".donkeycar_web_loader.json")


def _read_last_car_path():
    try:
        with open(_loader_state_path(), "r", encoding="utf-8") as f:
            value = json.load(f).get("last_car_path")
        return value if isinstance(value, str) else None
    except (OSError, ValueError):
        return None


def _write_last_car_path(path):
    try:
        with open(_loader_state_path(), "w", encoding="utf-8") as f:
            json.dump({"last_car_path": path}, f)
    except OSError as e:
        logger.warning(f"Failed to persist last car path: {e}")


@router.get("/discover_projects")
async def discover_projects(root: str = None):
    """扫描发现 mycar 项目（含 config.py 与 manage.py 的目录）。

    默认从用户 home 目录扫描；last_project 为上次成功加载且仍然有效的
    项目路径（供前端在多项目时自动选中上次用过的项目）。
    """
    scan_root = root if root else os.path.expanduser("~")
    try:
        projects = await run_in_threadpool(find_car_projects, scan_root)
        last = _read_last_car_path()
        if last and last not in projects and \
                os.path.isfile(os.path.join(last, "config.py")) and \
                os.path.isfile(os.path.join(last, "manage.py")):
            # 上次项目在扫描根之外但仍有效，一并返回供前端参考
            projects = sorted(projects + [last])
        return {
            "status": True,
            "root": os.path.abspath(os.path.expanduser(scan_root)),
            "projects": projects,
            "count": len(projects),
            "last_project": last,
        }
    except Exception as e:
        logger.error(f"Failed to discover car projects: {e}")
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

        # 加载成功即记住该项目（供下次自动 Browse 上次项目）
        _write_last_car_path(os.path.abspath(path))

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
