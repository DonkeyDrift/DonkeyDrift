import os
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

MODEL_TYPES = [
    "linear",
    "categorical",
    "tflite_linear",
    "tflite_categorical",
    "tensorrt_linear",
    "tensorrt_categorical",
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
        return {".h5", ".tflite", ".savedmodel", ".trt"}
    lower = model_type.lower()
    if "tflite" in lower:
        return {".tflite"}
    if "tensorrt" in lower:
        return {".trt", ".savedmodel"}
    return {".h5", ".savedmodel"}


def _format_for_path(path: str) -> str:
    suffix = os.path.splitext(path)[1].lstrip(".")
    return suffix or "savedmodel"


def load_car_config(config_path: Optional[str] = None):
    if not config_path:
        return None
    config_file = os.path.join(config_path, "config.py") if os.path.isdir(config_path) else config_path
    if not os.path.exists(config_file):
        raise HTTPException(status_code=404, detail="Config file not found")
    return load_config(config_file)


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
    prediction_cache[key] = pilot
    prediction_cache.move_to_end(key)
    pilot_id = key[0]
    pilot_keys = [cache_key for cache_key in prediction_cache if cache_key[0] == pilot_id]
    while len(pilot_keys) > PREDICTION_CACHE_LIMIT_PER_PILOT:
        key_to_delete = pilot_keys.pop(0)
        del prediction_cache[key_to_delete]


def _clear_prediction_cache(pilot_id: str) -> None:
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
    cached_pilot = prediction_cache.get(cache_key)
    if cached_pilot is not None:
        prediction_cache.move_to_end(cache_key)
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
        if not os.path.isfile(full_path):
            continue
        suffix = os.path.splitext(name)[1].lower()
        if suffix not in extensions:
            continue
        stat = os.stat(full_path)
        items.append({
            "name": name,
            "path": os.path.abspath(full_path),
            "format": _format_for_path(name),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "compatible": True,
        })
    return {"models": items}


@router.post("/pilots/load")
async def load_pilot(request: LoadPilotRequest):
    if not os.path.isfile(request.model_path):
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
async def unload_pilot(pilot_id: str):
    if pilot_id not in loaded_pilots:
        raise HTTPException(status_code=404, detail="Pilot not loaded")
    del loaded_pilots[pilot_id]
    _clear_prediction_cache(pilot_id)
    return {"status": True, "pilot_id": pilot_id}


@router.post("/pilots/{pilot_id}/predict")
async def predict_pilot(pilot_id: str, request: PredictRequest):
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
async def preview_pilot(
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
async def predict_pilot_records(pilot_id: str, request: PredictionsRequest):
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

    return {"status": True, "limit": request.limit, "points": points}
