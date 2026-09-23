import logging
import math
import os
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from typing import Any, List, Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from donkeycar import load_config
from donkeycar.utils import get_model_by_type

from routers import tub as tub_router

router = APIRouter()
logger = logging.getLogger(__name__)

MODEL_TYPES = [
    "linear",
    "categorical",
    "tflite_linear",
    "tflite_categorical",
    "tensorrt_linear",
    "tensorrt_categorical",
    # AIMO 云转 NPU 模型（*.ctx.bin.aidem）：需在后端解释器可 import aidlite
    # （本机 .venv-npu，aidlite 只装在系统 python3.12）时才能加载推理
    "aidlite_linear",
]

IMAGE_FIELD_CANDIDATES = [
    "cam/image_array",
    "cam/image",
    "image",
]


@dataclass
class LoadedPilot:
    id: str
    name: str
    model_path: str
    model_type: str
    pilot: Any
    loaded_at: str


class LoadPilotRequest(BaseModel):
    model_path: str
    model_type: str
    config_path: Optional[str] = None


class PredictRequest(BaseModel):
    record_index: int
    config_path: Optional[str] = None
    user_angle_field: str = "user/angle"
    user_throttle_field: str = "user/throttle"
    pilot_angle_field: str = "pilot/angle"
    pilot_throttle_field: str = "pilot/throttle"
    pre_transformations: List[str] = Field(default_factory=list)
    augmentations: List[str] = Field(default_factory=list)
    post_transformations: List[str] = Field(default_factory=list)
    brightness: Optional[float] = None
    blur: Optional[float] = None


class PredictionsRequest(BaseModel):
    config_path: Optional[str] = None
    tub_path: Optional[str] = None
    start: int = 0
    limit: int = 1000
    user_angle_field: str = "user/angle"
    user_throttle_field: str = "user/throttle"
    pre_transformations: List[str] = Field(default_factory=list)
    augmentations: List[str] = Field(default_factory=list)
    post_transformations: List[str] = Field(default_factory=list)
    brightness: Optional[float] = None
    blur: Optional[float] = None


loaded_pilots: dict[str, LoadedPilot] = {}
prediction_cache: OrderedDict[tuple[Any, ...], dict[str, float]] = OrderedDict()
PREDICTION_CACHE_LIMIT_PER_PILOT = 1500
# predict/preview/predictions 都是同步 def（Starlette 线程池执行，见各端点注释），
# 缓存的读-改-写会跨线程并发，必须加锁（move_to_end/迭代时另一线程插入会 RuntimeError）
_prediction_cache_lock = threading.Lock()

# Car config 按文件内容(mtime)缓存：推理热路径每帧调用 load_car_config，
# 而 load_config 每次都会重新编译执行整份 config.py + myconfig.py(实测约 75ms)。
# 只有当两个文件实际发生变化时才重载，避免每帧重复解析与日志刷屏。
_car_config_cache: dict[str, tuple[tuple[float, float], Any]] = {}
_car_config_lock = threading.Lock()


def _serialise_pilot(pilot: LoadedPilot) -> dict[str, Any]:
    return {
        "id": pilot.id,
        "name": pilot.name,
        "model_path": pilot.model_path,
        "model_type": pilot.model_type,
        "loaded_at": pilot.loaded_at,
    }


def _model_extensions(model_type: Optional[str]) -> set[str]:
    if not model_type:
        return {".h5", ".tflite", ".savedmodel", ".trt", ".aidem"}
    lower = model_type.lower()
    if "aidlite" in lower:
        return {".aidem"}
    if "tflite" in lower:
        return {".tflite"}
    if "tensorrt" in lower:
        return {".trt", ".savedmodel"}
    return {".h5", ".savedmodel"}


def _format_for_path(path: str) -> str:
    suffix = os.path.splitext(path)[1].lstrip(".")
    return suffix or "savedmodel"


def _config_stamp(config_file: str) -> tuple[float, float]:
    myconfig_file = os.path.join(os.path.dirname(config_file), "myconfig.py")
    myconfig_mtime = os.path.getmtime(myconfig_file) if os.path.exists(myconfig_file) else 0.0
    return os.path.getmtime(config_file), myconfig_mtime


def load_car_config(config_path: Optional[str] = None):
    if not config_path:
        return None
    config_file = os.path.join(config_path, "config.py") if os.path.isdir(config_path) else config_path
    if not os.path.exists(config_file):
        raise HTTPException(status_code=404, detail="Config file not found")

    stamp = _config_stamp(config_file)
    with _car_config_lock:
        cached = _car_config_cache.get(config_file)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        cfg = load_config(config_file)
        _car_config_cache[config_file] = (stamp, cfg)
        return cfg


def _get_record(record_index: int) -> dict[str, Any]:
    records = tub_router.current_records
    if not records:
        raise HTTPException(status_code=400, detail="No tub loaded")
    if record_index < 0 or record_index >= len(records):
        raise HTTPException(status_code=404, detail="Record not found")
    return records[record_index]


def _get_number(record: dict[str, Any], field: str) -> float:
    if field not in record:
        raise HTTPException(status_code=400, detail=f"Record field not found: {field}")
    return float(record[field])


def _get_image_name(record: dict[str, Any]) -> str:
    for field in IMAGE_FIELD_CANDIDATES:
        value = record.get(field)
        if isinstance(value, str):
            return value
    raise HTTPException(status_code=400, detail="Record image field not found")


def load_record_image(record: dict[str, Any]) -> np.ndarray:
    image_name = _get_image_name(record)
    clean_name = image_name.replace("images/", "").replace("images\\", "")
    candidates = [
        os.path.join(tub_router.current_tub_path, "images", clean_name),
        os.path.join(tub_router.current_tub_path, clean_name),
    ]
    image_path = next((path for path in candidates if os.path.exists(path)), None)
    if not image_path:
        raise HTTPException(status_code=404, detail=f"Image not found: {clean_name}")

    from PIL import Image

    return np.asarray(Image.open(image_path).convert("RGB"))


def _prediction_cache_key(pilot_id: str, request: PredictRequest) -> tuple[Any, ...]:
    return (
        pilot_id,
        request.record_index,
        request.config_path,
        request.user_angle_field,
        request.user_throttle_field,
        tuple(request.pre_transformations),
        tuple(request.augmentations),
        tuple(request.post_transformations),
        request.brightness,
        request.blur,
    )


def _cache_prediction(key: tuple[Any, ...], pilot: dict[str, float]) -> None:
    with _prediction_cache_lock:
        prediction_cache[key] = pilot
        prediction_cache.move_to_end(key)
        pilot_id = key[0]
        pilot_keys = [cache_key for cache_key in prediction_cache if cache_key[0] == pilot_id]
        while len(pilot_keys) > PREDICTION_CACHE_LIMIT_PER_PILOT:
            key_to_delete = pilot_keys.pop(0)
            del prediction_cache[key_to_delete]


def _clear_prediction_cache(pilot_id: str) -> None:
    with _prediction_cache_lock:
        for key in list(prediction_cache):
            if key[0] == pilot_id:
                del prediction_cache[key]


def _build_processing_config(base_cfg: Any, request: PredictRequest) -> Any:
    values = {}
    if base_cfg:
        values.update({key: getattr(base_cfg, key) for key in dir(base_cfg) if key.isupper()})

    values["TRANSFORMATIONS"] = list(request.pre_transformations)
    values["POST_TRANSFORMATIONS"] = list(request.post_transformations)
    values["AUGMENTATIONS"] = list(request.augmentations)

    if "CROP" in values["TRANSFORMATIONS"]:
        values.setdefault("ROI_CROP_LEFT", 0)
        values.setdefault("ROI_CROP_TOP", 0)
        values.setdefault("ROI_CROP_RIGHT", 0)
        values.setdefault("ROI_CROP_BOTTOM", 0)

    if request.brightness is not None and "BRIGHTNESS" not in values["AUGMENTATIONS"]:
        values["AUGMENTATIONS"].append("BRIGHTNESS")
    if request.blur is not None and "BLUR" not in values["AUGMENTATIONS"]:
        values["AUGMENTATIONS"].append("BLUR")
    if request.brightness is not None:
        values["AUG_BRIGHTNESS_RANGE"] = (request.brightness, request.brightness)
    if request.blur is not None:
        values["AUG_BLUR_RANGE"] = (request.blur, request.blur)

    return SimpleNamespace(**values)


def apply_image_processing(image: np.ndarray, base_cfg: Any, request: PredictRequest) -> np.ndarray:
    cfg = _build_processing_config(base_cfg, request)
    if request.pre_transformations:
        from donkeycar.parts.image_transformations import ImageTransformations
        image = ImageTransformations(cfg, "TRANSFORMATIONS").run(image)
    if request.augmentations or request.brightness is not None or request.blur is not None:
        from donkeycar.pipeline.augmentations import ImageAugmentation
        image = ImageAugmentation(cfg, "AUGMENTATIONS", prob=1.0).run(image)
    if request.post_transformations:
        from donkeycar.parts.image_transformations import ImageTransformations
        image = ImageTransformations(cfg, "POST_TRANSFORMATIONS").run(image)
    return image


def draw_control_line(angle: float, throttle: float, image: np.ndarray, color: tuple[int, int, int]) -> None:
    height, width = image.shape[:2]
    start_x = width // 2
    start_y = height - 1
    end_x = int(start_x + max(-1.0, min(1.0, angle)) * width * 0.4)
    end_y = int(start_y - max(-1.0, min(1.0, throttle)) * height * 0.6)

    steps = max(abs(end_x - start_x), abs(end_y - start_y), 1)
    for step in range(steps + 1):
        ratio = step / steps
        x = int(start_x + (end_x - start_x) * ratio)
        y = int(start_y + (end_y - start_y) * ratio)
        if 0 <= x < width and 0 <= y < height:
            image[y, x] = color


def _series_summary(errors: List[float]) -> Optional[dict[str, float]]:
    """单序列误差统计；errors 为空(无有限样本)返回 None。"""
    if not errors:
        return None
    count = len(errors)
    mae = sum(abs(error) for error in errors) / count
    rmse = math.sqrt(sum(error * error for error in errors) / count)
    bias = sum(errors) / count
    max_abs_error = max(abs(error) for error in errors)
    return {
        "count": count,
        "mae": mae,
        "rmse": rmse,
        "bias": bias,
        "max_abs_error": max_abs_error,
    }


def compute_prediction_metrics(points: List[dict[str, Any]]) -> dict[str, Any]:
    """批量预测点的模型贴合度摘要。

    误差口径：pilot − user（正偏差=模型输出大于人工操作）。
    非有限值(user 或 pilot 侧)所在帧不计入对应序列统计。
    """
    def errors(user_key: str, pilot_key: str) -> List[float]:
        return [
            point[pilot_key] - point[user_key]
            for point in points
            if math.isfinite(point[user_key]) and math.isfinite(point[pilot_key])
        ]

    return {
        "angle": _series_summary(errors("user_angle", "pilot_angle")),
        "throttle": _series_summary(errors("user_throttle", "pilot_throttle")),
    }


def _predict_loaded_pilot(pilot_id: str, request: PredictRequest) -> tuple[dict[str, float], dict[str, float]]:
    loaded = loaded_pilots.get(pilot_id)
    if not loaded:
        raise HTTPException(status_code=404, detail="Pilot not loaded")

    record = _get_record(request.record_index)
    user = {
        "angle": _get_number(record, request.user_angle_field),
        "throttle": _get_number(record, request.user_throttle_field),
    }
    cache_key = _prediction_cache_key(pilot_id, request)
    with _prediction_cache_lock:
        cached_pilot = prediction_cache.get(cache_key)
        if cached_pilot is not None:
            prediction_cache.move_to_end(cache_key)
    if cached_pilot is not None:
        return user, cached_pilot

    base_cfg = load_car_config(request.config_path) if request.config_path else None
    image = apply_image_processing(load_record_image(record), base_cfg, request)

    try:
        angle, throttle = loaded.pilot.run(image)
    except TypeError as exc:
        raise HTTPException(
            status_code=400,
            detail="This model type requires additional inputs and is not supported in Pilot Arena MVP",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    pilot = {"angle": float(angle), "throttle": float(throttle)}
    _cache_prediction(cache_key, pilot)
    return user, pilot


@router.get("/model-types")
async def list_model_types():
    return {"model_types": MODEL_TYPES, "default": "linear"}


@router.get("/models")
async def list_models(working_dir: Optional[str] = None, model_type: Optional[str] = None):
    cwd = working_dir or os.getcwd()
    models_dir = os.path.join(cwd, "models")
    extensions = _model_extensions(model_type)
    items: list[dict[str, Any]] = []

    if not os.path.isdir(models_dir):
        return {"models": items}

    for name in sorted(os.listdir(models_dir)):
        full_path = os.path.join(models_dir, name)
        suffix = os.path.splitext(name)[1].lower()
        if os.path.isfile(full_path):
            if suffix not in extensions:
                continue
            size = os.stat(full_path).st_size
        elif (
            os.path.isdir(full_path)
            and name.lower().endswith(".savedmodel")
            and ".savedmodel" in extensions
        ):
            size = sum(
                os.path.getsize(os.path.join(dirpath, f))
                for dirpath, _, filenames in os.walk(full_path)
                for f in filenames
            )
        else:
            continue
        stat = os.stat(full_path)
        items.append({
            "name": name,
            "path": os.path.abspath(full_path),
            "format": _format_for_path(name),
            "size": size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "compatible": True,
        })
    return {"models": items}


@router.post("/pilots/load")
def load_pilot(request: LoadPilotRequest):
    # 同步 def：模型加载含 NPU 解释器初始化（.aidem 实测 ~0.5s 阻塞），放线程池执行
    # SavedModel 是目录形式，文件与目录都允许
    if not os.path.exists(request.model_path):
        raise HTTPException(status_code=404, detail="Model file not found")

    cfg = load_car_config(request.config_path)
    try:
        pilot = get_model_by_type(request.model_type, cfg)
        pilot.load(request.model_path)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    pilot_id = uuid.uuid4().hex
    loaded = LoadedPilot(
        id=pilot_id,
        name=os.path.basename(request.model_path),
        model_path=os.path.abspath(request.model_path),
        model_type=request.model_type,
        pilot=pilot,
        loaded_at=datetime.now().isoformat(),
    )
    loaded_pilots[pilot_id] = loaded
    return {"status": True, "pilot": _serialise_pilot(loaded)}


@router.get("/pilots")
async def list_pilots():
    return {"pilots": [_serialise_pilot(pilot) for pilot in loaded_pilots.values()]}


@router.delete("/pilots/{pilot_id}")
def unload_pilot(pilot_id: str):
    # 同步 def：NPU 解释器 destroy 是阻塞调用（释放 Hexagon 上下文），放线程池执行，
    # 避免卸载时卡住事件循环（影响并发的取图/预测请求）。线程竞态由 AidLite._lock 兜底。
    if pilot_id not in loaded_pilots:
        raise HTTPException(status_code=404, detail="Pilot not loaded")
    loaded = loaded_pilots.pop(pilot_id)
    _clear_prediction_cache(pilot_id)
    # NPU 解释器（AidLite/QNN）持有硬件上下文，卸载时必须显式释放；
    # 其余 pilot 类型没有 shutdown，按有无该方法兼容处理
    shutdown = getattr(loaded.pilot, "shutdown", None)
    if callable(shutdown):
        try:
            shutdown()
        except Exception:
            logger.warning("释放 pilot %s 的解释器失败", pilot_id, exc_info=True)
    return {"status": True, "pilot_id": pilot_id}


@router.post("/pilots/{pilot_id}/predict")
def predict_pilot(pilot_id: str, request: PredictRequest):
    # 同步 def（非 async）：Starlette 线程池执行。逐帧推理包含 PIL 解码、cv 预处理与
    # NPU invoke（aidlite C 扩展会释放 GIL），async 会把这些阻塞全部压给事件循环——
    # 并发预测无法重叠（帧 N 的 Python 侧准备只能串行等帧 N-1 的 invoke），还会卡住
    # 并发的 60fps 取图流。同步 def 后多帧预测的 CPU 准备期与 NPU 执行期真正并行，
    # 事件循环只承担廉价的解析/序列化（同 routers/tub.py 取图端点的既定做法）。
    user, pilot = _predict_loaded_pilot(pilot_id, request)
    return {
        "status": True,
        "record_index": request.record_index,
        "user": user,
        "pilot": pilot,
        "fields": {
            "user_angle": request.user_angle_field,
            "user_throttle": request.user_throttle_field,
            "pilot_angle": request.pilot_angle_field,
            "pilot_throttle": request.pilot_throttle_field,
        },
    }


@router.get("/pilots/{pilot_id}/preview")
def preview_pilot(
    pilot_id: str,
    record_index: int = Query(...),
    config_path: Optional[str] = None,
    user_angle_field: str = "user/angle",
    user_throttle_field: str = "user/throttle",
    pre_transformations: str = "",
    augmentations: str = "",
    post_transformations: str = "",
    brightness: Optional[float] = None,
    blur: Optional[float] = None,
):
    # 同步 def：PNG 编码是阻塞重活，放线程池，理由同 predict_pilot
    request = PredictRequest(
        record_index=record_index,
        config_path=config_path,
        user_angle_field=user_angle_field,
        user_throttle_field=user_throttle_field,
        pre_transformations=[item for item in pre_transformations.split(",") if item],
        augmentations=[item for item in augmentations.split(",") if item],
        post_transformations=[item for item in post_transformations.split(",") if item],
        brightness=brightness,
        blur=blur,
    )
    record = _get_record(record_index)
    base_cfg = load_car_config(config_path) if config_path else None
    image = apply_image_processing(load_record_image(record).copy(), base_cfg, request)
    user, pilot = _predict_loaded_pilot(pilot_id, request)

    draw_control_line(user["angle"], user["throttle"], image, (0, 255, 0))
    draw_control_line(pilot["angle"], pilot["throttle"], image, (0, 0, 255))

    from PIL import Image

    buffer = BytesIO()
    Image.fromarray(image.astype(np.uint8)).save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


@router.post("/pilots/{pilot_id}/predictions")
def predict_pilot_records(pilot_id: str, request: PredictionsRequest):
    # 同步 def：批量循环逐帧推理+解码，整 tub 切片（可达数千帧）是秒级阻塞，
    # 绝不能在事件循环里跑；放线程池后与其他请求自然并行（预测缓存有锁保护）
    if pilot_id not in loaded_pilots:
        raise HTTPException(status_code=404, detail="Pilot not loaded")

    records = tub_router.current_records
    if not records:
        raise HTTPException(status_code=400, detail="No tub loaded")

    start = max(0, request.start)
    end = min(len(records), start + max(0, request.limit))
    points = []
    for record_index in range(start, end):
        predict_request = PredictRequest(
            record_index=record_index,
            config_path=request.config_path,
            user_angle_field=request.user_angle_field,
            user_throttle_field=request.user_throttle_field,
            pre_transformations=request.pre_transformations,
            augmentations=request.augmentations,
            post_transformations=request.post_transformations,
            brightness=request.brightness,
            blur=request.blur,
        )
        user, pilot = _predict_loaded_pilot(pilot_id, predict_request)
        points.append({
            "index": int(records[record_index].get("_index", record_index)),
            "user_angle": user["angle"],
            "user_throttle": user["throttle"],
            "pilot_angle": pilot["angle"],
            "pilot_throttle": pilot["throttle"],
        })

    return {"status": True, "limit": request.limit, "points": points,
            "summary": compute_prediction_metrics(points)}
