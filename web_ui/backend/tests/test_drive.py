import asyncio
import importlib
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def make_client():
    drive = importlib.import_module("routers.drive")
    drive = importlib.reload(drive)
    app = FastAPI()
    app.include_router(drive.router, prefix="/api/drive")
    return TestClient(app), drive


def make_online_client():
    client, drive = make_client()
    drive.drive_state.car_last_seen = datetime.now()
    return client, drive


def test_drive_stats_reports_recent_fps():
    client, drive = make_client()
    drive.drive_state.car_last_seen = datetime.now()
    drive.drive_state.frame_timestamps.extend([1.0, 1.25, 1.5, 1.75, 2.0])

    response = client.get("/api/drive/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["online"] is True
    assert data["fps"] == 4
    assert data["car_ws_connected"] is False
    assert data["last_seen_age_sec"] is not None


def test_drive_stats_reports_offline_diagnostics():
    client, _ = make_client()

    response = client.get("/api/drive/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["online"] is False
    assert data["fps"] == 0
    assert data["car_ws_connected"] is False
    assert data["last_seen_age_sec"] is None


def test_webrtc_session_requires_online_car():
    client, _ = make_client()

    response = client.post("/api/drive/webrtc/session", json={"client_id": "browser-1"})

    assert response.status_code == 400
    assert "车端未连接" in response.json()["detail"]


def test_webrtc_session_replaces_existing_session():
    client, _ = make_online_client()

    first = client.post("/api/drive/webrtc/session", json={"client_id": "browser-1"})
    second = client.post("/api/drive/webrtc/session", json={"client_id": "browser-2"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["session_id"] != second.json()["session_id"]
    assert second.json()["single_client"] is True

    old_offer = client.post("/api/drive/webrtc/offer", json={
        "session_id": first.json()["session_id"],
        "sdp": "old-offer",
        "type": "offer",
    })
    assert old_offer.status_code == 404


def test_webrtc_offer_routes_signal_to_car(monkeypatch):
    client, drive = make_online_client()
    sent_to_car = []

    async def fake_send_to_car(payload):
        sent_to_car.append(payload)
        return True

    monkeypatch.setattr(drive.drive_state, "send_to_car", fake_send_to_car)
    session = client.post("/api/drive/webrtc/session", json={"client_id": "browser-1"}).json()

    response = client.post("/api/drive/webrtc/offer", json={
        "session_id": session["session_id"],
        "sdp": "offer-sdp",
        "type": "offer",
    })

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert sent_to_car == [{
        "type": "webrtc_signal",
        "signal_type": "offer",
        "session_id": session["session_id"],
        "sdp": "offer-sdp",
        "description_type": "offer",
    }]


def test_webrtc_answer_routes_signal_to_session_client(monkeypatch):
    client, drive = make_online_client()
    sent_to_client = []

    async def fake_send_to_client(client_id, payload):
        sent_to_client.append((client_id, payload))
        return True

    monkeypatch.setattr(drive.drive_state, "send_to_client", fake_send_to_client)
    session = client.post("/api/drive/webrtc/session", json={"client_id": "browser-1"}).json()

    response = client.post("/api/drive/webrtc/answer", json={
        "session_id": session["session_id"],
        "sdp": "answer-sdp",
        "type": "answer",
    })

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert sent_to_client == [("browser-1", {
        "type": "webrtc_signal",
        "signal_type": "answer",
        "session_id": session["session_id"],
        "sdp": "answer-sdp",
        "description_type": "answer",
    })]


def test_webrtc_ice_routes_by_source(monkeypatch):
    client, drive = make_online_client()
    sent_to_car = []
    sent_to_client = []

    async def fake_send_to_car(payload):
        sent_to_car.append(payload)
        return True

    async def fake_send_to_client(client_id, payload):
        sent_to_client.append((client_id, payload))
        return True

    monkeypatch.setattr(drive.drive_state, "send_to_car", fake_send_to_car)
    monkeypatch.setattr(drive.drive_state, "send_to_client", fake_send_to_client)
    session = client.post("/api/drive/webrtc/session", json={"client_id": "browser-1"}).json()
    candidate = {"candidate": "candidate:1", "sdpMid": "0", "sdpMLineIndex": 0}

    client_response = client.post("/api/drive/webrtc/ice", json={
        "session_id": session["session_id"],
        "source": "client",
        "candidate": candidate,
    })
    car_response = client.post("/api/drive/webrtc/ice", json={
        "session_id": session["session_id"],
        "source": "car",
        "candidate": candidate,
    })

    assert client_response.status_code == 200
    assert car_response.status_code == 200
    assert sent_to_car == [{
        "type": "webrtc_signal",
        "signal_type": "ice",
        "session_id": session["session_id"],
        "candidate": candidate,
    }]
    assert sent_to_client == [("browser-1", {
        "type": "webrtc_signal",
        "signal_type": "ice",
        "session_id": session["session_id"],
        "candidate": candidate,
    })]


def test_webrtc_stats_reports_session_and_video_metrics():
    client, drive = make_online_client()
    session = client.post("/api/drive/webrtc/session", json={"client_id": "browser-1"}).json()
    drive.drive_state.webrtc_stats.update({
        "source_fps": 60.0,
        "sent_fps": 59.5,
        "browser_fps": 58.9,
        "browser_p95_frame_interval_ms": 24.5,
        "disconnect_count": 1,
        "degraded": False,
    })

    response = client.get("/api/drive/webrtc/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["active"] is True
    assert data["session_id"] == session["session_id"]
    assert data["webrtc_available"] is True
    assert data["source_fps"] == 60.0
    assert data["sent_fps"] == 59.5
    assert data["browser_fps"] == 58.9
    assert data["browser_p95_frame_interval_ms"] == 24.5
    assert data["disconnect_count"] == 1
    assert data["transport"] == "webrtc"
    assert data["degraded"] is False


def test_car_webrtc_stats_message_updates_backend_stats():
    client, drive = make_online_client()
    session = client.post("/api/drive/webrtc/session", json={"client_id": "browser-1"}).json()

    drive.drive_state.apply_car_webrtc_stats({
        "type": "webrtc_stats",
        "session_id": session["session_id"],
        "source_fps": 60.0,
        "sent_fps": 59.0,
        "stale_frames": 2,
        "peer_connection_state": "connected",
        "ice_connection_state": "completed",
        "ice_gathering_state": "complete",
        "local_description_error": None,
        "local_description_elapsed_ms": 18.5,
        "answer_sent_elapsed_ms": 35.0,
        "local_candidates_sent": 2,
    })

    response = client.get("/api/drive/webrtc/stats")
    data = response.json()
    assert data["source_fps"] == 60.0
    assert data["sent_fps"] == 59.0
    assert data["stale_frames"] == 2
    assert data["peer_connection_state"] == "connected"
    assert data["ice_connection_state"] == "completed"
    assert data["ice_gathering_state"] == "complete"
    assert data["local_description_error"] is None
    assert data["local_description_elapsed_ms"] == 18.5
    assert data["answer_sent_elapsed_ms"] == 35.0
    assert data["local_candidates_sent"] == 2


def test_browser_webrtc_stats_update_backend_stats():
    client, _ = make_online_client()
    session = client.post("/api/drive/webrtc/session", json={"client_id": "browser-1"}).json()

    response = client.post("/api/drive/webrtc/browser-stats", json={
        "session_id": session["session_id"],
        "browser_fps": 58.4,
        "browser_p95_frame_interval_ms": 23.7,
        "inbound_fps": 58.0,
        "frames_dropped": 3,
        "jitter_ms": 4.2,
        "jitter_buffer_delay_ms": 12.5,
    })

    assert response.status_code == 200
    data = client.get("/api/drive/webrtc/stats").json()
    assert data["browser_fps"] == 58.4
    assert data["browser_p95_frame_interval_ms"] == 23.7
    assert data["inbound_fps"] == 58.0
    assert data["frames_dropped"] == 3
    assert data["jitter_ms"] == 4.2
    assert data["jitter_buffer_delay_ms"] == 12.5


def test_browser_webrtc_stats_reject_stale_session():
    client, _ = make_online_client()
    client.post("/api/drive/webrtc/session", json={"client_id": "browser-1"})

    response = client.post("/api/drive/webrtc/browser-stats", json={
        "session_id": "stale-session",
        "browser_fps": 58.4,
        "browser_p95_frame_interval_ms": 23.7,
    })

    assert response.status_code == 404
    data = client.get("/api/drive/webrtc/stats").json()
    assert data["browser_fps"] == 0.0
    assert data["browser_p95_frame_interval_ms"] == 0.0
    assert data["inbound_fps"] == 0.0
    assert data["frames_dropped"] == 0


def test_webrtc_stats_exposes_signaling_timestamps():
    client, drive = make_online_client()
    async def ok_send_to_car(_payload):
        return True

    async def ok_broadcast(_payload):
        return None

    drive.drive_state.send_to_car = ok_send_to_car
    drive.drive_state.broadcast_to_clients = ok_broadcast
    session = client.post("/api/drive/webrtc/session", json={"client_id": "browser-1"}).json()

    client.post("/api/drive/webrtc/offer", json={"session_id": session["session_id"], "sdp": "offer", "type": "offer"})
    client.post("/api/drive/webrtc/answer", json={"session_id": session["session_id"], "sdp": "answer", "type": "answer"})
    client.post("/api/drive/webrtc/ice", json={
        "session_id": session["session_id"],
        "source": "client",
        "candidate": {"candidate": "candidate:1"},
    })

    data = client.get("/api/drive/webrtc/stats").json()
    assert data["last_offer_at"] is not None
    assert data["last_answer_at"] is not None
    assert data["offer_to_answer_elapsed_ms"] is not None
    assert data["last_client_ice_at"] is not None


def test_car_webrtc_stats_ignores_stale_session():
    client, drive = make_online_client()
    client.post("/api/drive/webrtc/session", json={"client_id": "browser-1"})

    drive.drive_state.apply_car_webrtc_stats({
        "type": "webrtc_stats",
        "session_id": "stale-session",
        "source_fps": 1.0,
        "sent_fps": 1.0,
    })

    response = client.get("/api/drive/webrtc/stats")
    data = response.json()
    assert data["source_fps"] == 0.0
    assert data["sent_fps"] == 0.0


def test_car_frame_message_updates_num_records_and_broadcasts_state(monkeypatch):
    client, drive = make_online_client()
    broadcasted = []

    async def fake_broadcast(payload):
        broadcasted.append(payload)

    monkeypatch.setattr(drive.drive_state, "broadcast_to_clients", fake_broadcast)

    with client.websocket_connect("/api/drive/ws?role=car") as car_ws:
        car_ws.send_json({
            "type": "frame",
            "data": "aGVsbG8=",  # base64 'hello'
            "num_records": 16460,
            "drive_mode": "local_angle",
            "recording": True,
        })

    assert drive.drive_state.num_records == 16460
    assert drive.drive_state.drive_mode == "local_angle"
    assert drive.drive_state.recording is True

    car_state_messages = [m for m in broadcasted if m.get("type") == "car_state"]
    assert len(car_state_messages) == 1
    assert car_state_messages[0]["num_records"] == 16460
    assert car_state_messages[0]["drive_mode"] == "local_angle"
    assert car_state_messages[0]["recording"] is True


def test_car_frame_message_with_none_state_does_not_crash(monkeypatch):
    client, drive = make_online_client()
    broadcasted = []

    async def fake_broadcast(payload):
        broadcasted.append(payload)

    monkeypatch.setattr(drive.drive_state, "broadcast_to_clients", fake_broadcast)

    with client.websocket_connect("/api/drive/ws?role=car") as car_ws:
        car_ws.send_json({
            "type": "frame",
            "data": "aGVsbG8=",
            "num_records": None,
            "drive_mode": None,
            "recording": None,
        })

    assert drive.drive_state.num_records == 0
    assert drive.drive_state.drive_mode == "user"
    assert drive.drive_state.recording is False


def test_car_state_only_broadcasts_on_change(monkeypatch):
    client, drive = make_online_client()
    broadcasted = []

    async def fake_broadcast(payload):
        broadcasted.append(payload)

    monkeypatch.setattr(drive.drive_state, "broadcast_to_clients", fake_broadcast)

    with client.websocket_connect("/api/drive/ws?role=car") as car_ws:
        # first message establishes state
        car_ws.send_json({"num_records": 100})
        # same value should not broadcast again
        car_ws.send_json({"num_records": 100})
        # new value should broadcast
        car_ws.send_json({"num_records": 110})

    car_state_messages = [m for m in broadcasted if m.get("type") == "car_state"]
    assert len(car_state_messages) == 2
    assert car_state_messages[0]["num_records"] == 100
    assert car_state_messages[1]["num_records"] == 110


def test_webrtc_session_resets_diagnostics():
    client, drive = make_online_client()
    drive.drive_state.webrtc_stats.update({
        "source_fps": 60.0,
        "sent_fps": 59.0,
        "peer_connection_state": "connected",
        "ice_connection_state": "completed",
        "ice_gathering_state": "complete",
        "local_description_error": "TimeoutError: TimeoutError()",
        "local_description_elapsed_ms": 2001.0,
        "answer_sent_elapsed_ms": 42.0,
        "local_candidates_sent": 2,
        "offer_to_answer_elapsed_ms": 5000.0,
        "last_offer_at": 1.0,
        "last_answer_at": 2.0,
        "last_client_ice_at": 3.0,
        "last_car_ice_at": 4.0,
        "degraded": True,
    })

    client.post("/api/drive/webrtc/session", json={"client_id": "browser-2"})

    data = client.get("/api/drive/webrtc/stats").json()
    assert data["source_fps"] == 0.0
    assert data["sent_fps"] == 0.0
    assert data["peer_connection_state"] is None
    assert data["ice_connection_state"] is None
    assert data["ice_gathering_state"] is None
    assert data["local_description_error"] is None
    assert data["local_description_elapsed_ms"] is None
    assert data["answer_sent_elapsed_ms"] is None
    assert data["local_candidates_sent"] == 0
    assert data["offer_to_answer_elapsed_ms"] is None
    assert data["last_offer_at"] is None
    assert data["last_answer_at"] is None
    assert data["last_client_ice_at"] is None
    assert data["last_car_ice_at"] is None
    assert data["degraded"] is False


@pytest.mark.anyio
async def test_sim_recovery_starts_and_stops():
    client, drive = make_client()
    assert drive.drive_state.sim_recovery_task is None

    drive.drive_state.start_sim_recovery()
    assert drive.drive_state.sim_recovery_task is not None
    assert not drive.drive_state.sim_recovery_task.done()

    drive.drive_state.stop_sim_recovery()
    # Give the event loop a chance to process cancellation
    await asyncio.sleep(0.1)
    assert drive.drive_state.sim_recovery_task is None or drive.drive_state.sim_recovery_task.done()


@pytest.mark.anyio
async def test_activate_sim_recovery_starts_worker(monkeypatch):
    client, drive = make_client()
    started = []

    def fake_start():
        started.append(True)

    monkeypatch.setattr(drive.drive_state, "start_sim_recovery", fake_start)

    # Simulate a client websocket that sends activate then disconnects
    with client.websocket_connect("/api/drive/ws?role=client&client_id=browser-1") as ws:
        ws.send_json({"type": "activate_sim_recovery"})
        time.sleep(0.1)

    assert len(started) == 1


def test_client_connect_requests_car_state_when_online(monkeypatch):
    client, drive = make_online_client()
    sent_to_car = []

    async def fake_send_to_car(payload):
        sent_to_car.append(payload)
        return True

    monkeypatch.setattr(drive.drive_state, "send_to_car", fake_send_to_car)

    with client.websocket_connect("/api/drive/ws?role=client&client_id=browser-1") as ws:
        pass

    assert {"type": "request_car_state"} in sent_to_car


def test_client_connect_does_not_request_car_state_when_offline(monkeypatch):
    client, drive = make_client()  # offline by default
    sent_to_car = []

    async def fake_send_to_car(payload):
        sent_to_car.append(payload)
        return True

    monkeypatch.setattr(drive.drive_state, "send_to_car", fake_send_to_car)

    with client.websocket_connect("/api/drive/ws?role=client&client_id=browser-1") as ws:
        pass

    assert {"type": "request_car_state"} not in sent_to_car


def test_client_car_mode_command_forwards_to_car(monkeypatch):
    client, drive = make_online_client()
    sent_to_car = []

    async def fake_send_to_car(payload):
        sent_to_car.append(payload)
        return True

    monkeypatch.setattr(drive.drive_state, "send_to_car", fake_send_to_car)

    with client.websocket_connect("/api/drive/ws?role=client&client_id=browser-1") as ws:
        ws.send_json({"car_mode": 2})
        time.sleep(0.1)

    assert {"car_mode": 2} in sent_to_car


async def _first_frame_part(drive):
    gen = drive._frame_generator()
    try:
        return await gen.__anext__()
    finally:
        await gen.aclose()


def test_video_stream_emits_placeholder_when_online_without_frame():
    client, drive = make_client()
    drive.drive_state.car_last_seen = datetime.now()
    drive.drive_state.last_frame = None

    part = asyncio.run(_first_frame_part(drive))

    assert b"Content-Type: image/jpeg" in part
    payload = part.split(b"\r\n\r\n", 1)[1]
    assert payload.startswith(b"\xff\xd8")


def test_video_stream_emits_real_frame_when_online():
    client, drive = make_client()
    drive.drive_state.car_last_seen = datetime.now()
    drive.drive_state.last_frame = b"\xff\xd8REALJPEG\xff\xd9"

    part = asyncio.run(_first_frame_part(drive))

    assert b"REALJPEG" in part


def test_video_stream_emits_placeholder_when_offline():
    # 车端离线时也要立即推占位帧，否则 <img> 收不到首帧，前端会一直
    # 卡在「正在连接摄像头」，甚至被浏览器判为 onError 显示「摄像头未连接」。
    client, drive = make_client()
    drive.drive_state.last_frame = None

    part = asyncio.run(_first_frame_part(drive))

    assert b"Content-Type: image/jpeg" in part
    payload = part.split(b"\r\n\r\n", 1)[1]
    assert payload.startswith(b"\xff\xd8")


# ===========================================================================
# /drive/load_model（issue #003：选模型 = 持久化选择 + 触发车端带模型重启）
# ===========================================================================

def _make_models_dir(tmp_path, names=("DKG-1.tflite",)):
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (models_dir / name).write_bytes(b"model-bytes")
    return models_dir


def _patch_model_store(monkeypatch, drive, tmp_path):
    """把模型持久化文件指到临时目录，避免写真实 ~/.donkeycar。"""
    model_file = tmp_path / "drive_model.json"
    monkeypatch.setattr(drive.webui_instance, "DRIVE_MODEL_FILE", model_file)
    return model_file


def test_load_model_persists_selection_and_triggers_restart(
        monkeypatch, tmp_path):
    """合法选择：写入持久化记录（tflite 推导 tflite_linear）并触发 launcher
    重启车进程；车端离线也允许（重启后上线即带模型）。"""
    client, drive = make_client()  # 故意不在线：不再要求 car_online
    _make_models_dir(tmp_path)
    model_file = _patch_model_store(monkeypatch, drive, tmp_path)
    launcher_calls = []

    def fake_post(path, body):
        launcher_calls.append((path, body))
        return 200, b'{"status": "launched"}'

    monkeypatch.setattr(drive, "_post_to_launcher", fake_post)

    response = client.post("/api/drive/load_model", json={
        "model_path": "./models/DKG-1.tflite",
        "working_dir": str(tmp_path),
    })

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["restarting"] is True
    assert launcher_calls == [("/api/launch/drive", b"")]

    import json as _json
    record = _json.loads(model_file.read_text(encoding="utf-8"))
    assert record["model"] == str(tmp_path / "models" / "DKG-1.tflite")
    assert record["model_type"] == "tflite_linear"


def test_load_model_h5_leaves_type_to_config(monkeypatch, tmp_path):
    """.h5 不推导 --type（交给车端 myconfig DEFAULT_MODEL_TYPE）。"""
    client, drive = make_client()
    _make_models_dir(tmp_path, names=("m.h5",))
    model_file = _patch_model_store(monkeypatch, drive, tmp_path)
    monkeypatch.setattr(
        drive, "_post_to_launcher", lambda path, body: (200, b"{}"))

    response = client.post("/api/drive/load_model", json={
        "model_path": "./models/m.h5",
        "working_dir": str(tmp_path),
    })

    assert response.status_code == 200
    import json as _json
    record = _json.loads(model_file.read_text(encoding="utf-8"))
    assert record["model_type"] is None


def test_load_model_rejects_path_outside_models_dir(monkeypatch, tmp_path):
    """路径逃逸 models 目录（../ 或绝对路径）一律 400。"""
    client, drive = make_online_client()
    _make_models_dir(tmp_path)
    _patch_model_store(monkeypatch, drive, tmp_path)
    outside = tmp_path / "evil.tflite"
    outside.write_bytes(b"x")
    monkeypatch.setattr(
        drive, "_post_to_launcher", lambda path, body: (200, b"{}"))

    for bad in ("../evil.tflite", str(outside), "./models/../../etc/x.tflite"):
        response = client.post("/api/drive/load_model", json={
            "model_path": bad,
            "working_dir": str(tmp_path),
        })
        assert response.status_code == 400, bad


def test_load_model_rejects_missing_file(monkeypatch, tmp_path):
    client, drive = make_online_client()
    _make_models_dir(tmp_path)
    _patch_model_store(monkeypatch, drive, tmp_path)

    response = client.post("/api/drive/load_model", json={
        "model_path": "./models/nope.tflite",
        "working_dir": str(tmp_path),
    })

    assert response.status_code == 400


def test_load_model_rejects_disallowed_extension(monkeypatch, tmp_path):
    client, drive = make_online_client()
    _make_models_dir(tmp_path, names=("notes.txt",))
    _patch_model_store(monkeypatch, drive, tmp_path)

    response = client.post("/api/drive/load_model", json={
        "model_path": "./models/notes.txt",
        "working_dir": str(tmp_path),
    })

    assert response.status_code == 400


def test_load_model_requires_working_dir(tmp_path):
    client, _ = make_client()

    response = client.post("/api/drive/load_model", json={
        "model_path": "./models/DKG-1.tflite",
    })

    assert response.status_code == 400


def test_load_model_launcher_unreachable_returns_restart_required(
        monkeypatch, tmp_path):
    """launcher 不在线：选择已持久化，但如实告知前端需手动重启，
    不再像旧实现那样「假成功」。"""
    client, drive = make_client()
    _make_models_dir(tmp_path)
    model_file = _patch_model_store(monkeypatch, drive, tmp_path)

    def failing_post(path, body):
        raise OSError("connection refused")

    monkeypatch.setattr(drive, "_post_to_launcher", failing_post)

    response = client.post("/api/drive/load_model", json={
        "model_path": "./models/DKG-1.tflite",
        "working_dir": str(tmp_path),
    })

    assert response.status_code == 200
    data = response.json()
    assert data["restarting"] is False
    assert data["restart_required"] is True
    assert model_file.exists()  # 选择仍已持久化


def test_load_model_launcher_error_returns_restart_required(
        monkeypatch, tmp_path):
    """launcher 报业务错误（如找不到 mycar 项目）：同样降级为需手动重启。"""
    client, drive = make_client()
    _make_models_dir(tmp_path)
    _patch_model_store(monkeypatch, drive, tmp_path)
    monkeypatch.setattr(
        drive, "_post_to_launcher",
        lambda path, body: (500, b'{"status": "error", "error": "no mycar"}'))

    response = client.post("/api/drive/load_model", json={
        "model_path": "./models/DKG-1.tflite",
        "working_dir": str(tmp_path),
    })

    assert response.status_code == 200
    data = response.json()
    assert data["restarting"] is False
    assert data["restart_required"] is True
    assert "no mycar" in data["message"]


def test_load_model_clear_selection_removes_record(monkeypatch, tmp_path):
    """选「无模型」：删除持久化记录并触发重启（卸载模型也需重启生效）。"""
    client, drive = make_client()
    _make_models_dir(tmp_path)
    model_file = _patch_model_store(monkeypatch, drive, tmp_path)
    model_file.write_text('{"model": "/x/m.tflite"}', encoding="utf-8")
    launcher_calls = []
    monkeypatch.setattr(
        drive, "_post_to_launcher",
        lambda path, body: launcher_calls.append(path) or (200, b"{}"))

    response = client.post("/api/drive/load_model", json={
        "model_path": "",
        "working_dir": str(tmp_path),
    })

    assert response.status_code == 200
    assert response.json()["restarting"] is True
    assert not model_file.exists()
    assert launcher_calls == ["/api/launch/drive"]
