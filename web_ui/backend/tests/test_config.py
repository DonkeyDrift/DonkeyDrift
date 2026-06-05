import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_load_config_merges_base_config_and_myconfig(tmp_path):
    (tmp_path / "config.py").write_text("IMAGE_H = 120\nIMAGE_W = 160\nIMAGE_DEPTH = 3\n")
    (tmp_path / "myconfig.py").write_text("IMAGE_H = 240\n")

    from routers import config

    app = FastAPI()
    app.include_router(config.router, prefix="/api/config")
    client = TestClient(app)

    response = client.post("/api/config/load", json={"path": str(tmp_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["IMAGE_H"] == 240
    assert payload["config"]["IMAGE_W"] == 160
    assert payload["config"]["IMAGE_DEPTH"] == 3
