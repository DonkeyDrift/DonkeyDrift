import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_app_title_uses_donkeydrifter_brand():
    main = importlib.import_module("main")

    assert main.app.title == "DonkeyDrifter Web API"


def test_root_message_uses_donkeydrifter_brand():
    main = importlib.import_module("main")
    client = TestClient(main.app)

    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["message"] == "DonkeyDrifter Web API is running"
