import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _make_tub(base_path: Path):
    """Create a tub with two recording sessions (3 + 2 live frames)."""
    from donkeycar.parts.tub_v2 import Tub

    # One Tub instance per recording run, mirroring separate drive sessions
    for session_records in (3, 2):
        run = Tub(
            str(base_path),
            inputs=['cam/image_array', 'user/angle', 'user/throttle'],
            types=['image_array', 'float', 'float'],
        )
        for i in range(session_records):
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


def test_list_sessions_groups_records_by_session(tmp_path):
    _make_tub(tmp_path)
    client = _build_client()

    response = client.get("/api/tub/sessions", params={"tubPath": str(tmp_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] is True
    sessions = payload["sessions"]
    assert len(sessions) == 2
    # Each Tub instance gets its own session id; both groups must be present
    counts = sorted(s["record_count"] for s in sessions)
    assert counts == [2, 3]
    # Newest recording (written last, highest first index) must be listed first
    assert sessions[0]["first_index"] > sessions[1]["first_index"]
    for session in sessions:
        assert session["session_id"]
        assert session["first_index"] <= session["last_index"]
        assert session["start_time_ms"] is not None
        assert session["end_time_ms"] is not None


def test_list_sessions_tolerates_empty_rollover_catalog(tmp_path):
    """Regression: a 0-byte catalog (created at roll-over before any record
    lands) used to make the read-only open fail with
    "cannot mmap an empty file", so the list endpoint 500'd."""
    from donkeycar.parts.tub_v2 import Tub

    run = Tub(
        str(tmp_path),
        inputs=['cam/image_array', 'user/angle', 'user/throttle'],
        types=['image_array', 'float', 'float'],
    )
    for i in range(3):
        run.write_record({'user/angle': 0.1 * i, 'user/throttle': 0.5})
    # Roll over to a fresh catalog and stop without writing into it
    run.manifest._add_catalog()
    run.close()

    client = _build_client()
    response = client.get("/api/tub/sessions", params={"tubPath": str(tmp_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] is True
    assert len(payload["sessions"]) == 1
    assert payload["sessions"][0]["record_count"] == 3


def test_get_session_records_returns_only_that_session(tmp_path):
    _make_tub(tmp_path)
    client = _build_client()

    sessions = client.get(
        "/api/tub/sessions", params={"tubPath": str(tmp_path)}
    ).json()["sessions"]
    target = sessions[0]

    response = client.get(
        "/api/tub/session_records",
        params={"tubPath": str(tmp_path), "sessionId": target["session_id"]},
    )

    assert response.status_code == 200
    records = response.json()["records"]
    assert len(records) == target["record_count"]
    assert all(
        str(r["_session_id"]) == target["session_id"] for r in records
    )


def test_delete_session_removes_all_its_live_records(tmp_path):
    _make_tub(tmp_path)
    client = _build_client()

    sessions = client.get(
        "/api/tub/sessions", params={"tubPath": str(tmp_path)}
    ).json()["sessions"]
    target = sessions[0]
    other = sessions[1]

    response = client.post(
        "/api/tub/delete_session",
        json={"tub_path": str(tmp_path), "session_id": target["session_id"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] is True
    assert payload["deleted_count"] == target["record_count"]

    remaining = client.get(
        "/api/tub/sessions", params={"tubPath": str(tmp_path)}
    ).json()["sessions"]
    assert len(remaining) == 1
    assert remaining[0]["session_id"] == other["session_id"]
    assert remaining[0]["record_count"] == other["record_count"]


def test_delete_session_unknown_session_returns_404(tmp_path):
    _make_tub(tmp_path)
    client = _build_client()

    response = client.post(
        "/api/tub/delete_session",
        json={"tub_path": str(tmp_path), "session_id": "no-such-session"},
    )

    assert response.status_code == 404


def test_get_image_rejects_path_traversal(tmp_path):
    """#487：path 穿越出 tub 目录必须拒绝，杜绝任意文件读取。"""
    _make_tub(tmp_path)
    client = _build_client()

    for evil in (
        "../../etc/passwd",
        "../../../home/user/.ssh/id_rsa",
        "images/../../../secret.txt",
    ):
        response = client.get(
            "/api/tub/image",
            params={"tubPath": str(tmp_path), "path": evil},
        )
        assert response.status_code in (400, 404), evil
        assert response.status_code != 200 or b"root:" not in response.content


def test_get_image_serves_frame_inside_tub(tmp_path):
    """#487 修复不回归：tub 内合法图片（images/ 前缀与裸文件名两种形态）正常返回。"""
    from donkeycar.parts.tub_v2 import Tub
    import numpy as np

    run = Tub(
        str(tmp_path),
        inputs=['cam/image_array', 'user/angle'],
        types=['image_array', 'float'],
    )
    run.write_record({
        'user/angle': 0.0,
        'cam/image_array': np.zeros((8, 8, 3), dtype=np.uint8),
    })
    run.close()

    images_dir = tmp_path / "images"
    frame_name = sorted(p.name for p in images_dir.glob("*.jpg"))[0]
    frame_bytes = (images_dir / frame_name).read_bytes()

    client = _build_client()
    for path_form in (frame_name, f"images/{frame_name}"):
        response = client.get(
            "/api/tub/image",
            params={"tubPath": str(tmp_path), "path": path_form},
        )
        assert response.status_code == 200, path_form
        assert response.content == frame_bytes
