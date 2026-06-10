import asyncio
import base64
import json

import numpy as np

from donkeycar.parts.drive_api_bridge import (
    DriveApiBridge,
    DriveVideoFrameBuffer,
    DriveWebRtcVideoTrack,
    DriveAiortcVideoTrack,
)
from donkeydrifter.parts.drive_api_bridge import DriveApiBridge as DrifterDriveApiBridge


class FakeEncodedFrame:
    def tobytes(self):
        return b"jpeg-bytes"


def test_drive_api_bridge_is_available_from_donkeydrifter_alias():
    assert DrifterDriveApiBridge is DriveApiBridge


def test_drive_api_bridge_appends_car_role_to_url():
    bridge = DriveApiBridge("ws://host:8000/api/drive/ws", auto_start=False)
    bridge_with_query = DriveApiBridge("ws://host/ws?token=x", auto_start=False)

    assert bridge.server_url == "ws://host:8000/api/drive/ws?role=car"
    assert bridge_with_query.server_url == "ws://host/ws?token=x&role=car"


def test_drive_api_bridge_has_threaded_part_update_method():
    bridge = DriveApiBridge(auto_start=False)

    assert hasattr(bridge, "update")
    assert bridge.update() is None


def test_drive_api_bridge_handles_control_message():
    bridge = DriveApiBridge(auto_start=False)

    bridge._handle_message({
        "angle": 0.2,
        "throttle": 0.3,
        "drive_mode": "local_angle",
        "recording": True,
        "buttons": {"x": True},
    })

    assert bridge.angle == 0.2
    assert bridge.throttle == 0.3
    assert bridge.mode_latch == "local_angle"
    assert bridge.recording_latch is True
    assert bridge.buttons == {"x": True}


def test_drive_api_bridge_sends_base64_frame(monkeypatch):
    sent_payloads = []
    encoded_images = []
    bridge = DriveApiBridge(auto_start=False, video_transport="mjpeg")
    bridge.connected = True

    monkeypatch.setattr(
        "donkeycar.parts.drive_api_bridge.cv2.cvtColor",
        lambda image, code: f"converted-{image}-{code}",
    )

    def fake_imencode(extension, image):
        encoded_images.append(image)
        return True, FakeEncodedFrame()

    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.cv2.imencode", fake_imencode)
    monkeypatch.setattr(bridge, "_send_json", sent_payloads.append)

    outputs = bridge.run_threaded(img_arr="rgb-image", num_records=7, mode="user", recording=False)

    assert outputs == (0.0, 0.0, "user", False, {})
    assert encoded_images == ["converted-rgb-image-4"]
    assert sent_payloads == [{
        "type": "frame",
        "data": base64.b64encode(b"jpeg-bytes").decode("ascii"),
        "num_records": 7,
        "drive_mode": "user",
        "recording": False,
    }]


def test_frame_buffer_updates_frame_id_and_keeps_latest_frame():
    buffer = DriveVideoFrameBuffer(width=320, height=240, clock=lambda: 1.0)
    first = np.zeros((240, 320, 3), dtype=np.uint8)
    second = np.full((240, 320, 3), 255, dtype=np.uint8)

    buffer.update(first)
    buffer.update(second)

    latest = buffer.get_latest()
    assert latest is not None
    assert latest.frame_id == 2
    assert latest.timestamp == 1.0
    assert np.array_equal(latest.frame, second)


def test_frame_buffer_resizes_to_target_resolution(monkeypatch):
    buffer = DriveVideoFrameBuffer(width=320, height=240)
    source = np.zeros((120, 160, 3), dtype=np.uint8)
    resized = np.ones((240, 320, 3), dtype=np.uint8)
    calls = []

    def fake_resize(image, size):
        calls.append((image.shape, size))
        return resized

    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.cv2.resize", fake_resize)

    buffer.update(source)

    latest = buffer.get_latest()
    assert calls == [((120, 160, 3), (320, 240))]
    assert latest is not None
    assert latest.frame.shape == (240, 320, 3)


def test_frame_buffer_ignores_none_frame():
    buffer = DriveVideoFrameBuffer(width=320, height=240)

    buffer.update(None)

    assert buffer.get_latest() is None
    assert buffer.stats()["source_fps"] == 0.0


def test_frame_buffer_reports_real_source_fps():
    timestamps = iter([0.0, 1.0 / 30.0, 2.0 / 30.0, 3.0 / 30.0])
    buffer = DriveVideoFrameBuffer(width=320, height=240, clock=lambda: next(timestamps))
    frame = np.zeros((240, 320, 3), dtype=np.uint8)

    for _ in range(4):
        buffer.update(frame)

    assert round(buffer.stats()["source_fps"]) == 30


def test_drive_api_bridge_webrtc_mode_updates_frame_buffer_without_mjpeg_throttle(monkeypatch):
    bridge = DriveApiBridge(auto_start=False, video_transport="webrtc")
    sent_payloads = []
    monkeypatch.setattr(bridge, "_send_frame", lambda *args, **kwargs: sent_payloads.append(args))

    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    bridge.run_threaded(img_arr=frame, num_records=1, mode="user", recording=False)
    bridge.run_threaded(img_arr=frame, num_records=2, mode="user", recording=False)

    latest = bridge.frame_buffer.get_latest()
    assert latest is not None
    assert latest.frame_id == 2
    assert sent_payloads == []


def test_webrtc_video_track_only_emits_new_frames():
    timestamps = iter([0.0, 1.0 / 60.0])
    buffer = DriveVideoFrameBuffer(width=320, height=240)
    track = DriveWebRtcVideoTrack(buffer, fps=60, clock=lambda: next(timestamps))
    first = np.zeros((240, 320, 3), dtype=np.uint8)
    second = np.ones((240, 320, 3), dtype=np.uint8)

    buffer.update(first)
    first_output = asyncio.run(track.recv())
    repeat_output = asyncio.run(track.recv())
    buffer.update(second)
    second_output = asyncio.run(track.recv())

    assert first_output is not None
    assert repeat_output is None
    assert second_output is not None
    assert round(track.stats()["sent_fps"]) == 60
    assert track.stats()["sent_frames"] == 2
    assert track.stats()["stale_frames"] == 1


def test_drive_api_bridge_derives_http_api_base_from_ws_url():
    bridge = DriveApiBridge("wss://example.test:8443/api/drive/ws", auto_start=False)

    assert bridge.http_api_base == "https://example.test:8443/api/drive"


def test_drive_api_bridge_handles_webrtc_offer_signal(monkeypatch):
    bridge = DriveApiBridge(auto_start=False)
    handled = []
    monkeypatch.setattr(bridge, "_handle_webrtc_signal", handled.append)

    bridge._handle_message({
        "type": "webrtc_signal",
        "signal_type": "offer",
        "session_id": "session-1",
        "sdp": "offer-sdp",
        "description_type": "offer",
    })

    assert handled == [{
        "type": "webrtc_signal",
        "signal_type": "offer",
        "session_id": "session-1",
        "sdp": "offer-sdp",
        "description_type": "offer",
    }]


def test_drive_api_bridge_posts_answer_and_ice(monkeypatch):
    posted = []
    bridge = DriveApiBridge("ws://host:8000/api/drive/ws", auto_start=False)
    monkeypatch.setattr(bridge, "_post_json", lambda path, payload: posted.append((path, payload)))

    bridge._post_webrtc_answer("session-1", "answer-sdp")
    bridge._post_webrtc_ice("session-1", {"candidate": "candidate:1"})

    assert posted == [
        ("/webrtc/answer", {"session_id": "session-1", "sdp": "answer-sdp", "type": "answer"}),
        ("/webrtc/ice", {"session_id": "session-1", "source": "car", "candidate": {"candidate": "candidate:1"}}),
    ]


class FakeVideoFrame:
    def __init__(self, image, format):
        self.image = image
        self.format = format
        self.pts = None
        self.time_base = None


class FakeAvModule:
    class VideoFrame:
        @staticmethod
        def from_ndarray(image, format):
            return FakeVideoFrame(image, format)


def test_aiortc_video_track_converts_latest_frame(monkeypatch):
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.av", FakeAvModule)
    buffer = DriveVideoFrameBuffer(width=320, height=240)
    track = DriveAiortcVideoTrack(buffer, fps=60)
    frame = np.zeros((240, 320, 3), dtype=np.uint8)

    buffer.update(frame)
    output = asyncio.run(track.recv())

    assert isinstance(output, FakeVideoFrame)
    assert output.image is frame
    assert output.format == "rgb24"
    assert output.pts == 1
    assert output.time_base is not None


def test_drive_api_bridge_creates_aiortc_peer_from_offer(monkeypatch):
    created = []
    answers = []

    class FakePeerConnection:
        def __init__(self):
            self.tracks = []
            self.remote = None
            self.localDescription = type("Description", (), {"sdp": "answer-sdp"})()
            created.append(self)

        def addTrack(self, track):
            self.tracks.append(track)

        async def setRemoteDescription(self, description):
            self.remote = description

        async def createAnswer(self):
            return "answer"

        async def setLocalDescription(self, answer):
            self.answer = answer

    class FakeSessionDescription:
        def __init__(self, sdp, type):
            self.sdp = sdp
            self.type = type

    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.RTCPeerConnection", FakePeerConnection)
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.RTCSessionDescription", FakeSessionDescription)

    bridge = DriveApiBridge(auto_start=False)
    monkeypatch.setattr(bridge, "_post_webrtc_answer", lambda session_id, sdp: answers.append((session_id, sdp)))

    bridge._handle_webrtc_signal({
        "type": "webrtc_signal",
        "signal_type": "offer",
        "session_id": "session-1",
        "sdp": "offer-sdp",
        "description_type": "offer",
    })

    assert bridge.active_webrtc_session_id == "session-1"
    assert len(created) == 1
    assert len(created[0].tracks) == 1
    assert created[0].remote.sdp == "offer-sdp"
    assert answers == [("session-1", "answer-sdp")]
