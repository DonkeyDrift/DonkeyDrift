import os
import sys
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _make_tub(base_path: Path, record_count: int = 3) -> None:
    """Create a tub with the given number of live frames (mirrors test_tub_sessions)."""
    from donkeycar.parts.tub_v2 import Tub

    run = Tub(
        str(base_path),
        inputs=['cam/image_array', 'user/angle', 'user/throttle'],
        types=['image_array', 'float', 'float'],
    )
    for i in range(record_count):
        run.write_record({
            'user/angle': 0.1 * i,
            'user/throttle': 0.5,
        })
    run.close()


def _build_client():
    from routers import tub as tub_router

    app = FastAPI()
    app.include_router(tub_router.router, prefix="/api/tub")
    return TestClient(app)


def _set_tree_mtime(root: Path, mtime: float) -> None:
    """把目录树下全部文件的 mtime 统一设定，用来控制 last_modified 排序。"""
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            os.utime(os.path.join(dirpath, filename), (mtime, mtime))


def test_child_tubs_endpoint_discovers_depth1_and_depth2(tmp_path):
    _make_tub(tmp_path / "tub_a")
    nested = tmp_path / "data" / "tub_b"
    _make_tub(nested, record_count=2)
    # 非 tub 的普通目录不应出现在结果里
    (tmp_path / "plain_dir").mkdir()

    client = _build_client()
    response = client.get("/api/tub/child_tubs", params={"tubPath": str(tmp_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] is True
    names = {t["name"] for t in payload["child_tubs"]}
    assert names == {"tub_a", "tub_b"}
    tub_a = next(t for t in payload["child_tubs"] if t["name"] == "tub_a")
    assert tub_a["path"] == os.path.abspath(tmp_path / "tub_a")
    assert tub_a["record_count"] == 3
    assert tub_a["total_physical"] == 3
    assert tub_a["deleted_count"] == 0
    assert tub_a["last_modified_ms"] > 0


def test_child_tubs_skips_hidden_directories(tmp_path):
    _make_tub(tmp_path / ".hidden_tub")
    _make_tub(tmp_path / "visible" / ".hidden_nested")

    client = _build_client()
    response = client.get("/api/tub/child_tubs", params={"tubPath": str(tmp_path)})

    assert response.status_code == 200
    assert response.json()["child_tubs"] == []


def test_child_tubs_record_count_excludes_soft_deleted(tmp_path):
    _make_tub(tmp_path / "tub_del", record_count=5)
    from donkeycar.parts.tub_v2 import Tub

    tub = Tub(str(tmp_path / "tub_del"))
    try:
        tub.delete_records([0, 1, 2])
    finally:
        tub.close()

    client = _build_client()
    response = client.get("/api/tub/child_tubs", params={"tubPath": str(tmp_path)})

    assert response.status_code == 200
    entry = response.json()["child_tubs"][0]
    assert entry["total_physical"] == 5
    assert entry["deleted_count"] == 3
    assert entry["record_count"] == 2


def test_child_tubs_sorted_by_last_modified_desc(tmp_path):
    _make_tub(tmp_path / "tub_old")
    _make_tub(tmp_path / "tub_new")
    now = time.time()
    _set_tree_mtime(tmp_path / "tub_old", now - 3600)
    _set_tree_mtime(tmp_path / "tub_new", now)

    client = _build_client()
    response = client.get("/api/tub/child_tubs", params={"tubPath": str(tmp_path)})

    assert response.status_code == 200
    entries = response.json()["child_tubs"]
    assert [t["name"] for t in entries] == ["tub_new", "tub_old"]
    assert entries[0]["last_modified_ms"] > entries[1]["last_modified_ms"]


def test_child_tubs_missing_directory_returns_404(tmp_path):
    client = _build_client()
    response = client.get(
        "/api/tub/child_tubs", params={"tubPath": str(tmp_path / "no_such_dir")}
    )
    assert response.status_code == 404


def test_sessions_empty_includes_child_tubs(tmp_path):
    """父 tub 记录全部被软删 → sessions 为空，响应附带子 tub 列表。"""
    _make_tub(tmp_path, record_count=2)
    from donkeycar.parts.tub_v2 import Tub

    tub = Tub(str(tmp_path))
    try:
        tub.delete_records([0, 1])
    finally:
        tub.close()
    _make_tub(tmp_path / "tub_7_26-10-20", record_count=4)

    client = _build_client()
    response = client.get("/api/tub/sessions", params={"tubPath": str(tmp_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["sessions"] == []
    child_tubs = payload["child_tubs"]
    assert len(child_tubs) == 1
    assert child_tubs[0]["name"] == "tub_7_26-10-20"
    assert child_tubs[0]["record_count"] == 4


def test_sessions_non_empty_omits_child_tubs(tmp_path):
    """sessions 非空时不附带 child_tubs 字段，避免无谓的目录扫描开销。"""
    _make_tub(tmp_path, record_count=2)
    _make_tub(tmp_path / "tub_7_26-10-20", record_count=4)

    client = _build_client()
    response = client.get("/api/tub/sessions", params={"tubPath": str(tmp_path)})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["sessions"]) == 1
    assert "child_tubs" not in payload
