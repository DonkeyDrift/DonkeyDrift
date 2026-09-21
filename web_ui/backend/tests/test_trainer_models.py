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

def _png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (0, 128, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _jpg_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buf, format="JPEG")
    return buf.getvalue()


def test_import_model_with_loss_image_and_meta(tmp_path):
    meta = b'{"final_loss": 0.042, "best_loss": 0.031, "epochs": 12}'
    with _build_client() as client:
        resp = client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={
                "file": ("m1.tflite", b"\x00\x01", "application/octet-stream"),
                "loss_image": ("chart.png", _png_bytes(), "image/png"),
                "meta_json": ("meta.json", meta, "application/json"),
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["finalLoss"] == 0.042
        assert body["bestLoss"] == 0.031
        assert body["previewPath"] == str(tmp_path / "models" / "m1.png")

        listed = client.get("/api/trainer/models", params={"working_dir": str(tmp_path)})
        preview = client.get(
            "/api/trainer/models/preview",
            params={"path": str(tmp_path / "models" / "m1.png")},
        )

    assert listed.status_code == 200
    models = {item["name"]: item for item in listed.json()["models"]}
    assert models["m1.tflite"]["previewPath"] == str(tmp_path / "models" / "m1.png")
    assert models["m1.tflite"]["finalLoss"] == 0.042
    assert models["m1.tflite"]["bestLoss"] == 0.031
    assert (tmp_path / "models" / "m1_meta.json").is_file()
    assert preview.status_code == 200
    assert preview.content == _png_bytes()


def test_import_model_loss_image_jpg_converted_to_png(tmp_path):
    with _build_client() as client:
        resp = client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={
                "file": ("m2.h5", b"h5data", "application/octet-stream"),
                "loss_image": ("chart.jpg", _jpg_bytes(), "image/jpeg"),
            },
        )
        assert resp.status_code == 200

    png = tmp_path / "models" / "m2.png"
    assert png.is_file()
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_upload_model_loss_for_imported_model(tmp_path):
    with _build_client() as client:
        imported = client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={"file": ("m3.tflite", b"x", "application/octet-stream")},
        )
        assert imported.status_code == 200

        resp = client.post(
            "/api/trainer/models/m3.tflite/loss",
            data={"working_dir": str(tmp_path)},
            files={
                "loss_image": ("chart.png", _png_bytes(), "image/png"),
                "meta_json": ("meta.json", b'{"final_loss": 0.9, "best_loss": 0.8}', "application/json"),
            },
        )
        assert resp.status_code == 200
        assert resp.json()["finalLoss"] == 0.9
        assert resp.json()["bestLoss"] == 0.8

        listed = client.get("/api/trainer/models", params={"working_dir": str(tmp_path)})

    models = {item["name"]: item for item in listed.json()["models"]}
    assert models["m3.tflite"]["previewPath"] == str(tmp_path / "models" / "m3.png")
    assert models["m3.tflite"]["finalLoss"] == 0.9
    assert models["m3.tflite"]["bestLoss"] == 0.8


def test_upload_model_loss_unknown_model_404(tmp_path):
    with _build_client() as client:
        resp = client.post(
            "/api/trainer/models/nope.tflite/loss",
            data={"working_dir": str(tmp_path)},
            files={"loss_image": ("chart.png", _png_bytes(), "image/png")},
        )
    assert resp.status_code == 404


def test_upload_model_loss_no_files_400(tmp_path):
    with _build_client() as client:
        client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={"file": ("m5.tflite", b"x", "application/octet-stream")},
        )
        resp = client.post(
            "/api/trainer/models/m5.tflite/loss",
            data={"working_dir": str(tmp_path)},
        )
    assert resp.status_code == 400


def test_upload_model_loss_invalid_meta_400(tmp_path):
    with _build_client() as client:
        client.post(
            "/api/trainer/models/import",
            data={"working_dir": str(tmp_path)},
            files={"file": ("m6.tflite", b"x", "application/octet-stream")},
        )
        resp = client.post(
            "/api/trainer/models/m6.tflite/loss",
            data={"working_dir": str(tmp_path)},
            files={"meta_json": ("meta.json", b"not json", "application/json")},
        )
    assert resp.status_code == 400

