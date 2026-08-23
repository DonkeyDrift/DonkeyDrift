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


def test_get_version_returns_version_string():
    from donkeycar._version import __version__

    from routers import config

    app = FastAPI()
    app.include_router(config.router, prefix="/api/config")
    client = TestClient(app)

    response = client.get("/api/config/version")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == __version__


def _make_car_project(base):
    car = base / "mycar"
    car.mkdir(parents=True)
    (car / "config.py").write_text("IMAGE_H = 120\n")
    (car / "manage.py").write_text("# manage\n")
    return car


def test_discover_projects_finds_single_project(tmp_path):
    from routers import config

    app = FastAPI()
    app.include_router(config.router, prefix="/api/config")
    client = TestClient(app)

    car = _make_car_project(tmp_path / "projects")

    response = client.get("/api/config/discover_projects", params={"root": str(tmp_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["projects"] == [str(car)]


def test_discover_projects_multiple_and_none(tmp_path):
    from routers import config

    app = FastAPI()
    app.include_router(config.router, prefix="/api/config")
    client = TestClient(app)

    # 空目录：没有项目
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    response = client.get("/api/config/discover_projects", params={"root": str(empty_root)})
    assert response.status_code == 200
    assert response.json()["count"] == 0

    # 多个项目：全部返回
    first = _make_car_project(tmp_path / "a")
    second = _make_car_project(tmp_path / "b")
    response = client.get("/api/config/discover_projects", params={"root": str(tmp_path)})
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["projects"] == sorted([str(first), str(second)])


def test_discover_projects_reports_last_project(tmp_path, monkeypatch):
    from routers import config

    app = FastAPI()
    app.include_router(config.router, prefix="/api/config")
    client = TestClient(app)

    car = _make_car_project(tmp_path / "projects")
    state_file = tmp_path / "loader_state.json"
    monkeypatch.setattr(config, "_loader_state_path", lambda: str(state_file))

    # 无记录时 last_project 为 None
    response = client.get("/api/config/discover_projects", params={"root": str(tmp_path)})
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["last_project"] is None

    # load 成功后记录该项目
    response = client.post("/api/config/load", json={"path": str(car)})
    assert response.status_code == 200
    response = client.get("/api/config/discover_projects", params={"root": str(tmp_path)})
    payload = response.json()
    assert payload["last_project"] == str(car)

    # 上次项目在扫描根之外但仍然有效时，一并返回
    other_root = tmp_path / "elsewhere"
    other_root.mkdir()
    response = client.get("/api/config/discover_projects", params={"root": str(other_root)})
    payload = response.json()
    assert payload["last_project"] == str(car)
    assert payload["projects"] == [str(car)]

    # 状态文件损坏时不报错，回退 None
    state_file.write_text("{invalid json")
    response = client.get("/api/config/discover_projects", params={"root": str(other_root)})
    payload = response.json()
    assert payload["last_project"] is None
    assert payload["projects"] == []


def test_find_car_projects_skips_hidden_and_no_descent(tmp_path):
    from routers.config import find_car_projects

    # 隐藏目录/缓存目录中的项目不扫描
    hidden = tmp_path / ".cache" / "mycar"
    hidden.mkdir(parents=True)
    (hidden / "config.py").write_text("")
    (hidden / "manage.py").write_text("")

    # 项目目录内部不再下钻（嵌套的“项目”不重复发现）
    car = tmp_path / "mycar"
    car.mkdir()
    (car / "config.py").write_text("")
    (car / "manage.py").write_text("")
    nested = car / "inner"
    nested.mkdir()
    (nested / "config.py").write_text("")
    (nested / "manage.py").write_text("")

    # 只有 config.py 没有 manage.py 的目录不算项目
    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / "config.py").write_text("")

    projects = find_car_projects(str(tmp_path))
    assert projects == [str(car)]
