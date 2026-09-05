import io
import sys
import zipfile
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


def test_import_model_rejects_unsupported_extension(tmp_path):
    with _build_client() as client:
        resp = client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={"file": ("notes.txt", b"data", "application/octet-stream")},
        )

    assert resp.status_code == 400
    assert not (tmp_path / "models" / "notes.txt").exists()


def test_import_model_accepts_h5_and_lists_it(tmp_path):
    with _build_client() as client:
        resp = client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={"file": ("pilot.h5", b"h5data", "application/octet-stream")},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "pilot.h5"

        listed = client.get("/api/trainer/models", params={"working_dir": str(tmp_path)})

    assert listed.status_code == 200
    names = {item["name"] for item in listed.json()["models"]}
    assert "pilot.h5" in names


def _make_savedmodel_zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_import_model_accepts_savedmodel_zip_and_lists_it(tmp_path):
    payload = _make_savedmodel_zip({
        "mymodel.savedmodel/saved_model.pb": b"pb",
        "mymodel.savedmodel/variables/variables.data-00000-of-00001": b"weights",
        "mymodel.savedmodel/variables/variables.index": b"index",
    })
    with _build_client() as client:
        resp = client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={"file": ("mymodel.zip", payload, "application/zip")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "mymodel.savedmodel"

        dest = tmp_path / "models" / "mymodel.savedmodel"
        assert (dest / "saved_model.pb").is_file()
        assert (dest / "variables" / "variables.index").is_file()

        listed = client.get("/api/trainer/models", params={"working_dir": str(tmp_path)})

    assert listed.status_code == 200
    models = {item["name"]: item for item in listed.json()["models"]}
    assert "mymodel.savedmodel" in models
    assert models["mymodel.savedmodel"]["type"] == "dir"
    assert models["mymodel.savedmodel"]["size"] > 0


def test_import_model_rejects_zip_without_savedmodel(tmp_path):
    payload = _make_savedmodel_zip({"readme.txt": b"nope"})
    with _build_client() as client:
        resp = client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={"file": ("fake.zip", payload, "application/zip")},
        )

    assert resp.status_code == 400
    assert not (tmp_path / "models" / "fake.savedmodel").exists()


def test_import_model_rejects_zip_path_traversal(tmp_path):
    payload = _make_savedmodel_zip({
        "saved_model.pb": b"pb",
        "../evil.pb": b"x",
    })
    with _build_client() as client:
        resp = client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={"file": ("evil.zip", payload, "application/zip")},
        )

    assert resp.status_code == 400
    assert not (tmp_path / "models" / "evil.savedmodel").exists()
    assert not (tmp_path / "evil.pb").exists()


def test_import_model_rejects_duplicate_savedmodel_name(tmp_path):
    payload = _make_savedmodel_zip({"saved_model.pb": b"pb"})
    with _build_client() as client:
        first = client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={"file": ("dup.zip", payload, "application/zip")},
        )
        second = client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={"file": ("dup.zip", payload, "application/zip")},
        )

    assert first.status_code == 200
    assert second.status_code == 409


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
