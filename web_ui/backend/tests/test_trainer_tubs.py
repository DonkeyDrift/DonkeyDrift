import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _make_tub(path: Path, records: int = 1):
    """Create a minimal tub with a manifest.json and one record."""
    path.mkdir(parents=True, exist_ok=True)
    from donkeycar.parts.tub_v2 import Tub

    tub = Tub(
        str(path),
        inputs=['user/angle', 'user/throttle'],
        types=['float', 'float'],
    )
    for i in range(records):
        tub.write_record({'user/angle': 0.1 * i, 'user/throttle': 0.5})
    tub.close()


def _build_client():
    from routers import trainer as trainer_router

    app = FastAPI()
    app.include_router(trainer_router.router, prefix="/api/trainer")
    return TestClient(app)


def test_list_tubs_finds_data_dir_and_subtubs(tmp_path):
    _make_tub(tmp_path / "data", records=2)
    _make_tub(tmp_path / "data" / "tub_2026_08_17")

    with _build_client() as client:
        resp = client.get("/api/trainer/tubs", params={"working_dir": str(tmp_path)})

    assert resp.status_code == 200
    body = resp.json()
    rels = [t["relative_path"] for t in body["tubs"]]
    assert "./data" in rels
    assert "./data/tub_2026_08_17" in rels
    for t in body["tubs"]:
        assert Path(t["absolute_path"], "manifest.json").is_file()
    assert body["current_tub_path"] == ""


def test_list_tubs_empty_when_no_data(tmp_path):
    with _build_client() as client:
        resp = client.get("/api/trainer/tubs", params={"working_dir": str(tmp_path)})

    assert resp.status_code == 200
    assert resp.json()["tubs"] == []


def test_list_tubs_skips_non_tub_dirs_and_finds_data_siblings(tmp_path):
    # data exists but is not a tub; data_backup is a tub sibling
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "not_a_tub").mkdir()
    _make_tub(tmp_path / "data_backup")

    with _build_client() as client:
        resp = client.get("/api/trainer/tubs", params={"working_dir": str(tmp_path)})

    assert resp.status_code == 200
    rels = [t["relative_path"] for t in resp.json()["tubs"]]
    assert rels == ["./data_backup"]


def test_list_tubs_reports_loaded_tub(tmp_path):
    _make_tub(tmp_path / "data")

    from routers import tub as tub_router
    from routers import trainer as trainer_router

    app = FastAPI()
    app.include_router(tub_router.router, prefix="/api/tub")
    app.include_router(trainer_router.router, prefix="/api/trainer")
    client = TestClient(app)

    loaded = client.post("/api/tub/load", json={"path": str(tmp_path / "data")})
    assert loaded.status_code == 200

    resp = client.get("/api/trainer/tubs", params={"working_dir": str(tmp_path)})
    assert resp.status_code == 200
    assert resp.json()["current_tub_path"] == str(tmp_path / "data")
