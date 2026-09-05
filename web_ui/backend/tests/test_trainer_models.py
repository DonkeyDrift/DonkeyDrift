import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _build_client():
    from routers import trainer as trainer_router

    app = FastAPI()
    app.include_router(trainer_router.router, prefix="/api/trainer")
    return TestClient(app)


def test_import_model_writes_tflite_into_models_dir(tmp_path):
    with _build_client() as client:
        resp = client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={"file": ("my-model.tflite", b"\x00\x01\x02\x03", "application/octet-stream")},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] is True
    assert body["name"] == "my-model.tflite"
    assert body["size"] == 4
    dest = tmp_path / "models" / "my-model.tflite"
    assert dest.is_file()
    assert dest.read_bytes() == b"\x00\x01\x02\x03"


def test_import_model_rejects_non_tflite(tmp_path):
    with _build_client() as client:
        resp = client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={"file": ("model.h5", b"data", "application/octet-stream")},
        )

    assert resp.status_code == 400
    assert not (tmp_path / "models" / "model.h5").exists()


def test_import_model_rejects_duplicate_name(tmp_path):
    with _build_client() as client:
        first = client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={"file": ("dup.tflite", b"original", "application/octet-stream")},
        )
        second = client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={"file": ("dup.tflite", b"changed", "application/octet-stream")},
        )

    assert first.status_code == 200
    assert second.status_code == 409
    # 原文件内容保持不变，未被覆盖
    assert (tmp_path / "models" / "dup.tflite").read_bytes() == b"original"


def test_import_model_sanitizes_path_traversal(tmp_path):
    with _build_client() as client:
        resp = client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={"file": ("../../evil.tflite", b"x", "application/octet-stream")},
        )

    assert resp.status_code == 200
    assert resp.json()["name"] == "evil.tflite"
    assert (tmp_path / "models" / "evil.tflite").is_file()
    assert not (tmp_path / "evil.tflite").exists()
