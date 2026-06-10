import importlib
import sys
from datetime import datetime
from pathlib import Path

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


def test_webrtc_answer_routes_signal_to_clients(monkeypatch):
    client, drive = make_online_client()
    broadcasted = []

    async def fake_broadcast(payload):
        broadcasted.append(payload)

    monkeypatch.setattr(drive.drive_state, "broadcast_to_clients", fake_broadcast)
    session = client.post("/api/drive/webrtc/session", json={"client_id": "browser-1"}).json()

    response = client.post("/api/drive/webrtc/answer", json={
        "session_id": session["session_id"],
        "sdp": "answer-sdp",
        "type": "answer",
    })

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert broadcasted == [{
        "type": "webrtc_signal",
        "signal_type": "answer",
        "session_id": session["session_id"],
        "sdp": "answer-sdp",
        "description_type": "answer",
    }]


def test_webrtc_ice_routes_by_source(monkeypatch):
    client, drive = make_online_client()
    sent_to_car = []
    broadcasted = []

    async def fake_send_to_car(payload):
        sent_to_car.append(payload)
        return True

    async def fake_broadcast(payload):
        broadcasted.append(payload)

    monkeypatch.setattr(drive.drive_state, "send_to_car", fake_send_to_car)
    monkeypatch.setattr(drive.drive_state, "broadcast_to_clients", fake_broadcast)
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
    assert broadcasted == [{
        "type": "webrtc_signal",
        "signal_type": "ice",
        "session_id": session["session_id"],
        "candidate": candidate,
    }]


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
    })

    response = client.get("/api/drive/webrtc/stats")
    data = response.json()
    assert data["source_fps"] == 60.0
    assert data["sent_fps"] == 59.0
    assert data["stale_frames"] == 2
    assert data["peer_connection_state"] == "connected"
    assert data["ice_connection_state"] == "completed"
    assert data["ice_gathering_state"] == "complete"


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


def test_webrtc_session_resets_diagnostics():
    client, drive = make_online_client()
    drive.drive_state.webrtc_stats.update({
        "source_fps": 60.0,
        "sent_fps": 59.0,
        "peer_connection_state": "connected",
        "ice_connection_state": "completed",
        "ice_gathering_state": "complete",
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
    assert data["last_offer_at"] is None
    assert data["last_answer_at"] is None
    assert data["last_client_ice_at"] is None
    assert data["last_car_ice_at"] is None
    assert data["degraded"] is False
