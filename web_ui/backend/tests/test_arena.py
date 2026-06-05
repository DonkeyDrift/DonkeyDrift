import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class FakePilot:
    last_image = None
    run_count = 0

    def __init__(self):
        self.loaded_path = None

    def load(self, path):
        self.loaded_path = path

    def run(self, image):
        FakePilot.last_image = image
        FakePilot.run_count += 1
        return 0.25, 0.5


def make_client(monkeypatch):
    arena = importlib.import_module("routers.arena")
    arena = importlib.reload(arena)
    FakePilot.last_image = None
    FakePilot.run_count = 0

    monkeypatch.setattr(arena, "get_model_by_type", lambda model_type, cfg: FakePilot())
    monkeypatch.setattr(arena, "load_car_config", lambda config_path=None: SimpleNamespace())
    monkeypatch.setattr(arena, "load_record_image", lambda record: np.zeros((120, 160, 3), dtype=np.uint8))
    monkeypatch.setattr(arena.tub_router, "current_records", [
        {
            "_index": 0,
            "cam/image_array": "0_cam_image_array_.jpg",
            "user/angle": 0.1,
            "user/throttle": 0.2,
        }
    ])
    monkeypatch.setattr(arena.tub_router, "current_tub_path", "/tmp/tub")

    app = FastAPI()
    app.include_router(arena.router, prefix="/api/arena")
    return TestClient(app), arena


def test_main_registers_arena_router():
    main = importlib.import_module("main")
    routes = {route.path for route in main.app.routes}
    assert "/api/arena/model-types" in routes


def test_list_models_includes_all_arena_model_formats(tmp_path):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    for name in ["pilot.h5", "pilot.tflite", "pilot.savedmodel", "pilot.trt", "loss.png"]:
        (models_dir / name).write_text("model")

    from routers import arena

    client = TestClient(FastAPI())
    client.app.include_router(arena.router, prefix="/api/arena")

    response = client.get("/api/arena/models", params={"working_dir": str(tmp_path)})

    assert response.status_code == 200
    names = {item["name"] for item in response.json()["models"]}
    assert names == {"pilot.h5", "pilot.tflite", "pilot.savedmodel", "pilot.trt"}


def test_load_car_config_merges_base_config_and_myconfig(tmp_path):
    (tmp_path / "config.py").write_text("IMAGE_H = 120\nIMAGE_W = 160\nIMAGE_DEPTH = 3\n")
    (tmp_path / "myconfig.py").write_text("IMAGE_H = 240\n")

    from routers import arena

    cfg = arena.load_car_config(str(tmp_path))

    assert cfg.IMAGE_H == 240
    assert cfg.IMAGE_W == 160
    assert cfg.IMAGE_DEPTH == 3


def test_load_and_unload_pilot(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch)
    model_path = tmp_path / "pilot.tflite"
    model_path.write_text("model")

    load_response = client.post(
        "/api/arena/pilots/load",
        json={
            "model_path": str(model_path),
            "model_type": "tflite_linear",
            "config_path": str(tmp_path),
        },
    )

    assert load_response.status_code == 200
    pilot = load_response.json()["pilot"]
    assert pilot["name"] == "pilot.tflite"
    assert pilot["model_type"] == "tflite_linear"

    list_response = client.get("/api/arena/pilots")
    assert [item["id"] for item in list_response.json()["pilots"]] == [pilot["id"]]

    delete_response = client.delete(f"/api/arena/pilots/{pilot['id']}")
    assert delete_response.status_code == 200
    assert client.get("/api/arena/pilots").json()["pilots"] == []


def test_predict_returns_user_and_pilot_values(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch)
    model_path = tmp_path / "pilot.tflite"
    model_path.write_text("model")

    load_response = client.post(
        "/api/arena/pilots/load",
        json={
            "model_path": str(model_path),
            "model_type": "tflite_linear",
            "config_path": str(tmp_path),
        },
    )
    pilot_id = load_response.json()["pilot"]["id"]

    response = client.post(
        f"/api/arena/pilots/{pilot_id}/predict",
        json={"record_index": 0, "config_path": str(tmp_path)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["record_index"] == 0
    assert payload["user"] == {"angle": 0.1, "throttle": 0.2}
    assert payload["pilot"] == {"angle": 0.25, "throttle": 0.5}


def test_predict_applies_image_processing(monkeypatch, tmp_path):
    client, arena = make_client(monkeypatch)
    model_path = tmp_path / "pilot.tflite"
    model_path.write_text("model")
    processed = np.ones((120, 160, 3), dtype=np.uint8)

    def apply_processing(image, cfg, request):
        assert request.pre_transformations == ["CROP"]
        assert request.post_transformations == ["RGB2GRAY"]
        assert request.brightness == 0.2
        return processed

    monkeypatch.setattr(arena, "apply_image_processing", apply_processing)

    load_response = client.post(
        "/api/arena/pilots/load",
        json={
            "model_path": str(model_path),
            "model_type": "tflite_linear",
            "config_path": str(tmp_path),
        },
    )
    pilot_id = load_response.json()["pilot"]["id"]

    response = client.post(
        f"/api/arena/pilots/{pilot_id}/predict",
        json={
            "record_index": 0,
            "config_path": str(tmp_path),
            "pre_transformations": ["CROP"],
            "post_transformations": ["RGB2GRAY"],
            "brightness": 0.2,
        },
    )

    assert response.status_code == 200
    assert FakePilot.last_image is processed


def test_preview_returns_image_response(monkeypatch, tmp_path):
    client, arena = make_client(monkeypatch)
    model_path = tmp_path / "pilot.tflite"
    model_path.write_text("model")

    def draw_line(angle, throttle, image, rgb):
        image[0, 0] = rgb

    monkeypatch.setattr(arena, "draw_control_line", draw_line)

    load_response = client.post(
        "/api/arena/pilots/load",
        json={
            "model_path": str(model_path),
            "model_type": "tflite_linear",
            "config_path": str(tmp_path),
        },
    )
    pilot_id = load_response.json()["pilot"]["id"]

    response = client.get(f"/api/arena/pilots/{pilot_id}/preview", params={"record_index": 0})

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")
    assert FakePilot.run_count == 1


def test_predictions_returns_limited_points(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch)
    model_path = tmp_path / "pilot.tflite"
    model_path.write_text("model")

    load_response = client.post(
        "/api/arena/pilots/load",
        json={
            "model_path": str(model_path),
            "model_type": "tflite_linear",
            "config_path": str(tmp_path),
        },
    )
    pilot_id = load_response.json()["pilot"]["id"]

    response = client.post(
        f"/api/arena/pilots/{pilot_id}/predictions",
        json={"start": 0, "limit": 1, "config_path": str(tmp_path)},
    )

    assert response.status_code == 200
    assert response.json()["points"] == [
        {
            "index": 0,
            "user_angle": 0.1,
            "user_throttle": 0.2,
            "pilot_angle": 0.25,
            "pilot_throttle": 0.5,
        }
    ]


def test_predictions_apply_image_processing_options(monkeypatch, tmp_path):
    client, arena = make_client(monkeypatch)
    model_path = tmp_path / "pilot.tflite"
    model_path.write_text("model")
    processed = np.ones((120, 160, 3), dtype=np.uint8)

    def apply_processing(image, cfg, request):
        assert request.pre_transformations == ["CROP"]
        assert request.augmentations == ["BLUR"]
        assert request.post_transformations == ["RGB2GRAY"]
        assert request.brightness == 0.2
        assert request.blur == 1.5
        return processed

    monkeypatch.setattr(arena, "apply_image_processing", apply_processing)

    load_response = client.post(
        "/api/arena/pilots/load",
        json={
            "model_path": str(model_path),
            "model_type": "tflite_linear",
            "config_path": str(tmp_path),
        },
    )
    pilot_id = load_response.json()["pilot"]["id"]

    response = client.post(
        f"/api/arena/pilots/{pilot_id}/predictions",
        json={
            "start": 0,
            "limit": 1,
            "config_path": str(tmp_path),
            "pre_transformations": ["CROP"],
            "augmentations": ["BLUR"],
            "post_transformations": ["RGB2GRAY"],
            "brightness": 0.2,
            "blur": 1.5,
        },
    )

    assert response.status_code == 200
    assert FakePilot.last_image is processed


def test_predict_uses_cache_for_same_processing_options(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch)
    model_path = tmp_path / "pilot.tflite"
    model_path.write_text("model")

    load_response = client.post(
        "/api/arena/pilots/load",
        json={
            "model_path": str(model_path),
            "model_type": "tflite_linear",
            "config_path": str(tmp_path),
        },
    )
    pilot_id = load_response.json()["pilot"]["id"]
    payload = {"record_index": 0, "config_path": str(tmp_path), "pre_transformations": ["CROP"]}

    first_response = client.post(f"/api/arena/pilots/{pilot_id}/predict", json=payload)
    second_response = client.post(f"/api/arena/pilots/{pilot_id}/predict", json=payload)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert FakePilot.run_count == 1


def test_predict_cache_separates_processing_options(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch)
    model_path = tmp_path / "pilot.tflite"
    model_path.write_text("model")

    load_response = client.post(
        "/api/arena/pilots/load",
        json={
            "model_path": str(model_path),
            "model_type": "tflite_linear",
            "config_path": str(tmp_path),
        },
    )
    pilot_id = load_response.json()["pilot"]["id"]

    first_response = client.post(
        f"/api/arena/pilots/{pilot_id}/predict",
        json={"record_index": 0, "config_path": str(tmp_path), "pre_transformations": ["CROP"]},
    )
    second_response = client.post(
        f"/api/arena/pilots/{pilot_id}/predict",
        json={"record_index": 0, "config_path": str(tmp_path), "pre_transformations": ["RGB2GRAY"]},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert FakePilot.run_count == 2


def test_unload_pilot_clears_prediction_cache(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch)
    model_path = tmp_path / "pilot.tflite"
    model_path.write_text("model")

    load_response = client.post(
        "/api/arena/pilots/load",
        json={
            "model_path": str(model_path),
            "model_type": "tflite_linear",
            "config_path": str(tmp_path),
        },
    )
    pilot_id = load_response.json()["pilot"]["id"]
    payload = {"record_index": 0, "config_path": str(tmp_path)}

    assert client.post(f"/api/arena/pilots/{pilot_id}/predict", json=payload).status_code == 200
    assert client.delete(f"/api/arena/pilots/{pilot_id}").status_code == 200

    second_load_response = client.post(
        "/api/arena/pilots/load",
        json={
            "model_path": str(model_path),
            "model_type": "tflite_linear",
            "config_path": str(tmp_path),
        },
    )
    second_pilot_id = second_load_response.json()["pilot"]["id"]

    assert client.post(f"/api/arena/pilots/{second_pilot_id}/predict", json=payload).status_code == 200
    assert FakePilot.run_count == 2
