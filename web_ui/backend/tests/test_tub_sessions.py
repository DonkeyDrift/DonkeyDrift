import io
import os
import sys
import tarfile
from pathlib import Path

import numpy as np
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


def _make_tub_with_images(base_path: Path, sessions=(2, 2, 2)):
    """Create a tub with several recording sessions, each writing real images."""
    from donkeycar.parts.tub_v2 import Tub

    for session_records in sessions:
        run = Tub(
            str(base_path),
            inputs=['cam/image_array', 'user/angle', 'user/throttle'],
            types=['image_array', 'float', 'float'],
        )
        for i in range(session_records):
            image = np.zeros((4, 4, 3), dtype=np.uint8)
            image[..., 0] = run.manifest.current_index
            run.write_record({
                'cam/image_array': image,
                'user/angle': 0.1 * i,
                'user/throttle': 0.5,
            })
        run.close()


def _download(client, tub_path: Path, session_id: str):
    response = client.get(
        "/api/tub/download_session",
        params={"tubPath": str(tub_path), "sessionId": session_id},
    )
    assert response.status_code == 200
    return response.content


def test_download_session_exports_self_contained_tub(tmp_path):
    """The archive must mirror the data/ layout (manifest.json + catalogs +
    images/) so an extracted session loads as a valid tub."""
    _make_tub_with_images(tmp_path)
    client = _build_client()
    sessions = client.get(
        "/api/tub/sessions", params={"tubPath": str(tmp_path)}
    ).json()["sessions"]
    target = sessions[0]

    content = _download(client, tmp_path, target["session_id"])

    extract_dir = tmp_path.parent / "export"
    extract_dir.mkdir()
    with tarfile.open(fileobj=io.BytesIO(content)) as tar:
        names = tar.getnames()
        assert "manifest.json" in names
        assert any(n.endswith(".catalog") for n in names)
        assert any(n.endswith(".catalog_manifest") for n in names)
        images = [n for n in names if n.startswith("images/")]
        assert len(images) == target["record_count"]
        tar.extractall(extract_dir)

    from donkeycar.parts.tub_v2 import Tub

    tub = Tub(str(extract_dir), read_only=True)
    try:
        records = [r for r in tub]
        assert len(records) == target["record_count"]
        assert all(
            str(r["_session_id"]) == target["session_id"] for r in records
        )
        # 记录按新 tub 位置重新编号，与 manifest.current_index 一致
        assert [r["_index"] for r in records] == list(range(len(records)))
        for record in records:
            image_path = os.path.join(extract_dir, "images", record["cam/image_array"])
            assert os.path.exists(image_path)
    finally:
        tub.close()


def test_download_session_excludes_soft_deleted_frames(tmp_path):
    """Soft-deleted frames stay out of the export so images and data stay
    one-to-one consistent."""
    _make_tub_with_images(tmp_path)
    client = _build_client()
    sessions = client.get(
        "/api/tub/sessions", params={"tubPath": str(tmp_path)}
    ).json()["sessions"]
    target = sessions[0]

    from donkeycar.parts.tub_v2 import Tub

    deleter = Tub(str(tmp_path))
    try:
        deleter.delete_records(target["first_index"])
    finally:
        deleter.close()

    content = _download(client, tmp_path, target["session_id"])

    with tarfile.open(fileobj=io.BytesIO(content)) as tar:
        images = [n for n in tar.getnames() if n.startswith("images/")]
    assert len(images) == target["record_count"] - 1


def test_download_session_without_live_records_returns_404(tmp_path):
    _make_tub_with_images(tmp_path)
    client = _build_client()

    response = client.get(
        "/api/tub/download_session",
        params={"tubPath": str(tmp_path), "sessionId": "no-such-session"},
    )

    assert response.status_code == 404
