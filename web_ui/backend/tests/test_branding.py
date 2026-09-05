import importlib
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_app_title_uses_donkeydrifter_brand():
    main = importlib.import_module("main")

    assert main.app.title == "DonkeyDrift Web API"


def test_root_message_uses_donkeydrifter_brand():
    main = importlib.import_module("main")
    client = TestClient(main.app)
    index_path = os.path.join(main.FRONTEND_DIST, "index.html")

    response = client.get("/")

    assert response.status_code == 200
    if os.path.isfile(index_path):
        # 前端已构建：GET / 由 StaticFiles 挂载返回 SPA 的 index.html
        assert "text/html" in response.headers["content-type"]
    else:
        # 前端未构建或 dist 缺少 index.html：返回 JSON 提示
        assert response.json()["message"].startswith(
            "DonkeyDrift Web UI is running"
        )
