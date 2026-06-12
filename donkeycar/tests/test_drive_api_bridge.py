import asyncio
import base64
import json
import time

import numpy as np

from donkeycar.parts.drive_api_bridge import (
    DriveApiBridge,
    DriveVideoFrameBuffer,
    DriveWebRtcVideoTrack,
    DriveAiortcVideoTrack,
    parse_webrtc_ice_servers,
)
from donkeydrifter.parts.drive_api_bridge import DriveApiBridge as DrifterDriveApiBridge


class FakeEncodedFrame:
    def tobytes(self):
        return b"jpeg-bytes"


def test_parse_webrtc_ice_servers_accepts_empty_and_list():
    servers = [{"urls": ["turn:192.168.3.96:3478?transport=udp"], "username": "donkey", "credential": "secret"}]

    assert parse_webrtc_ice_servers(None) == []
    assert parse_webrtc_ice_servers("") == []
    assert parse_webrtc_ice_servers(servers) == servers


def test_parse_webrtc_ice_servers_accepts_json_string():
    raw = '[{"urls":["turn:192.168.3.96:3478?transport=udp"],"username":"donkey","credential":"secret"}]'

    assert parse_webrtc_ice_servers(raw) == [
        {"urls": ["turn:192.168.3.96:3478?transport=udp"], "username": "donkey", "credential": "secret"}
    ]


def test_parse_webrtc_ice_servers_rejects_invalid_json_and_non_array():
    assert parse_webrtc_ice_servers("not-json") == []
    assert parse_webrtc_ice_servers('{"urls":"turn:host"}') == []


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


def test_drive_api_bridge_accepts_webrtc_ice_servers_config():
    servers = [{"urls": ["turn:192.168.3.96:3478?transport=udp"], "username": "donkey", "credential": "secret"}]

    bridge = DriveApiBridge(auto_start=False, webrtc_ice_servers=servers)

    assert bridge.webrtc_ice_servers == servers


def test_drive_api_bridge_env_ice_servers_override_constructor(monkeypatch):
    monkeypatch.setenv("DRIVE_WEBRTC_ICE_SERVERS", '[{"urls":["turn:env:3478"],"username":"env","credential":"secret"}]')

    bridge = DriveApiBridge(auto_start=False, webrtc_ice_servers=[{"urls": ["turn:cfg:3478"]}])

    assert bridge.webrtc_ice_servers == [{"urls": ["turn:env:3478"], "username": "env", "credential": "secret"}]


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
    # Suppress the periodic car_state send so this test only verifies the frame payload.
    bridge.last_car_state = time.time()

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

    assert outputs == (0.0, 0.0, "user", False, {}, False)
    assert encoded_images == ["converted-rgb-image-4"]
    assert [p for p in sent_payloads if p.get("type") == "frame"] == [{
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


def test_frame_buffer_waits_for_new_frame():
    async def scenario():
        buffer = DriveVideoFrameBuffer(width=320, height=240)
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        waiter = asyncio.create_task(buffer.wait_for_new_frame(last_frame_id=0, timeout=0.1))
        await asyncio.sleep(0)

        buffer.update(frame)
        latest = await waiter

        assert latest is not None
        assert latest.frame_id == 1
        assert latest.frame is frame

    asyncio.run(scenario())


def test_frame_buffer_wait_for_new_frame_returns_existing_frame_immediately():
    async def scenario():
        buffer = DriveVideoFrameBuffer(width=320, height=240)
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        buffer.update(frame)

        latest = await buffer.wait_for_new_frame(last_frame_id=0, timeout=0.1)

        assert latest is not None
        assert latest.frame_id == 1

    asyncio.run(scenario())


def test_frame_buffer_wait_for_new_frame_returns_none_on_timeout():
    async def scenario():
        buffer = DriveVideoFrameBuffer(width=320, height=240)

        latest = await buffer.wait_for_new_frame(last_frame_id=0, timeout=0.001)

        assert latest is None

    asyncio.run(scenario())


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


def test_aiortc_video_track_waits_for_next_frame(monkeypatch):
    async def scenario():
        monkeypatch.setattr("donkeycar.parts.drive_api_bridge.av", FakeAvModule)
        buffer = DriveVideoFrameBuffer(width=320, height=240)
        track = DriveAiortcVideoTrack(buffer, fps=60)
        first = np.zeros((240, 320, 3), dtype=np.uint8)
        second = np.ones((240, 320, 3), dtype=np.uint8)

        buffer.update(first)
        first_output = await track.recv()
        second_task = asyncio.create_task(track.recv())
        await asyncio.sleep(0)
        assert not second_task.done()

        buffer.update(second)
        second_output = await asyncio.wait_for(second_task, timeout=0.1)

        assert first_output.image is first
        assert second_output.image is second
        assert track.stats()["sent_frames"] == 2

    asyncio.run(scenario())


class FakePeerConnection:
    def __init__(self):
        self.tracks = []
        self.remote = None
        self.candidates = []
        self.localDescription = type("Description", (), {"sdp": "answer-sdp"})()

    def addTrack(self, track):
        self.tracks.append(track)

    async def setRemoteDescription(self, description):
        self.remote = description

    async def createAnswer(self):
        return type("Answer", (), {"sdp": "answer-sdp"})()

    async def setLocalDescription(self, answer):
        self.answer = answer
        self.localDescription = type("Description", (), {"sdp": "local-answer-sdp"})()

    async def addIceCandidate(self, candidate):
        self.candidates.append(candidate)


class FakeSessionDescription:
    def __init__(self, sdp, type):
        self.sdp = sdp
        self.type = type


class FakeIceCandidate:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeIceServer:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeConfiguration:
    def __init__(self, iceServers):
        self.iceServers = iceServers


def test_drive_api_bridge_creates_aiortc_peer_from_offer(monkeypatch):
    created = []
    answers = []

    class RecordingPeerConnection(FakePeerConnection):
        def __init__(self):
            super().__init__()
            created.append(self)

    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.RTCPeerConnection", RecordingPeerConnection)
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.RTCSessionDescription", FakeSessionDescription)

    bridge = DriveApiBridge(auto_start=False)

    async def mock_post_webrtc_answer_async(session_id, sdp):
        answers.append((session_id, sdp))
    monkeypatch.setattr(bridge, "_post_webrtc_answer_async", mock_post_webrtc_answer_async)

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


def test_drive_api_bridge_passes_ice_servers_to_aiortc_peer(monkeypatch):
    created = []
    servers = [{"urls": ["turn:192.168.3.96:3478?transport=udp"], "username": "donkey", "credential": "secret", "unknown": "ignored"}]

    class RecordingPeerConnection(FakePeerConnection):
        def __init__(self, configuration=None):
            super().__init__()
            self.configuration = configuration
            created.append(self)

    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.RTCPeerConnection", RecordingPeerConnection)
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.RTCSessionDescription", FakeSessionDescription)
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.RTCConfiguration", FakeConfiguration)
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.RTCIceServer", FakeIceServer)

    bridge = DriveApiBridge(auto_start=False, webrtc_ice_servers=servers)

    async def mock_post_webrtc_answer_async(_session_id, _sdp):
        pass
    monkeypatch.setattr(bridge, "_post_webrtc_answer_async", mock_post_webrtc_answer_async)

    bridge._handle_webrtc_signal({
        "type": "webrtc_signal",
        "signal_type": "offer",
        "session_id": "session-1",
        "sdp": "offer-sdp",
        "description_type": "offer",
    })

    assert created[0].configuration.iceServers[0].kwargs == {
        "urls": ["turn:192.168.3.96:3478?transport=udp"],
        "username": "donkey",
        "credential": "secret",
    }


def test_drive_api_bridge_posts_answer_before_set_local_description(monkeypatch, caplog):
    """setLocalDescription 阻塞或失败时 answer 也必须先回传。"""
    created = []
    answers = []

    class HangingSetLocal(FakePeerConnection):
        def __init__(self):
            super().__init__()
            created.append(self)

        async def setLocalDescription(self, answer):
            assert answers == [("session-x", "answer-sdp")]
            raise RuntimeError("setLocalDescription 失败")

    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.RTCPeerConnection", HangingSetLocal)
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.RTCSessionDescription", FakeSessionDescription)

    bridge = DriveApiBridge(auto_start=False)

    async def mock_post_webrtc_answer_async(session_id, sdp):
        answers.append((session_id, sdp))
    monkeypatch.setattr(bridge, "_post_webrtc_answer_async", mock_post_webrtc_answer_async)

    bridge._handle_webrtc_signal({
        "type": "webrtc_signal",
        "signal_type": "offer",
        "session_id": "session-x",
        "sdp": "offer-sdp",
        "description_type": "offer",
    })

    assert answers == [("session-x", "answer-sdp")]
    assert "RuntimeError" in caplog.text
    assert "setLocalDescription 失败" in bridge.webrtc_local_description_error
    assert bridge.webrtc_answer_sent_elapsed_ms is not None


def test_drive_api_bridge_posts_local_ice_candidates_from_sdp_once():
    posted = []
    bridge = DriveApiBridge(auto_start=False)
    bridge.active_webrtc_session_id = "session-1"

    async def mock_post_webrtc_ice_async(session_id, candidate):
        posted.append((session_id, candidate))
    bridge._post_webrtc_ice_async = mock_post_webrtc_ice_async

    sdp = "\r\n".join([
        "v=0",
        "m=video 9 UDP/TLS/RTP/SAVPF 96",
        "a=mid:0",
        "a=candidate:1 1 udp 2130706431 192.168.1.2 5000 typ host",
        "a=candidate:2 1 udp 1694498815 203.0.113.10 3478 typ relay raddr 0.0.0.0 rport 0",
    ])

    bridge._post_local_ice_candidates_from_sdp("session-1", sdp)
    bridge._post_local_ice_candidates_from_sdp("session-1", sdp)

    assert posted == [
        ("session-1", {
            "candidate": "candidate:1 1 udp 2130706431 192.168.1.2 5000 typ host",
            "sdpMid": "0",
            "sdpMLineIndex": 0,
        }),
        ("session-1", {
            "candidate": "candidate:2 1 udp 1694498815 203.0.113.10 3478 typ relay raddr 0.0.0.0 rport 0",
            "sdpMid": "0",
            "sdpMLineIndex": 0,
        }),
    ]
    assert bridge.local_candidates_sent == 2


def test_drive_api_bridge_ignores_sdp_ice_for_stale_session():
    posted = []
    bridge = DriveApiBridge(auto_start=False)
    bridge.active_webrtc_session_id = "session-1"
    bridge._post_webrtc_ice = lambda session_id, candidate: posted.append((session_id, candidate))

    bridge._post_local_ice_candidates_from_sdp("stale-session", "a=mid:0\na=candidate:1 1 udp 1 host 1 typ host")

    assert posted == []


def test_drive_api_bridge_reports_local_description_diagnostics(monkeypatch):
    sent = []
    bridge = DriveApiBridge(auto_start=False)
    bridge.active_webrtc_session_id = "session-1"
    bridge.webrtc_peer = type("Peer", (), {
        "connectionState": "new",
        "iceConnectionState": "new",
        "iceGatheringState": "gathering",
    })()
    bridge.webrtc_local_description_error = "TimeoutError: TimeoutError()"
    bridge.webrtc_local_description_elapsed_ms = 2001.0
    monkeypatch.setattr(bridge, "_send_json", sent.append)
    monkeypatch.setattr(bridge.frame_buffer, "stats", lambda: {"source_fps": 58.0})
    monkeypatch.setattr(bridge.webrtc_track, "stats", lambda: {"sent_fps": 0.0, "stale_frames": 3})

    bridge._send_webrtc_stats()

    assert sent[0]["local_description_error"] == "TimeoutError: TimeoutError()"
    assert sent[0]["local_description_elapsed_ms"] == 2001.0


def test_drive_api_bridge_reports_answer_and_candidate_diagnostics(monkeypatch):
    sent = []
    bridge = DriveApiBridge(auto_start=False)
    bridge.active_webrtc_session_id = "session-1"
    bridge.webrtc_peer = type("Peer", (), {
        "connectionState": "connected",
        "iceConnectionState": "completed",
        "iceGatheringState": "complete",
    })()
    bridge.webrtc_answer_sent_elapsed_ms = 42.0
    bridge.local_candidates_sent = 2
    monkeypatch.setattr(bridge, "_send_json", sent.append)
    monkeypatch.setattr(bridge.frame_buffer, "stats", lambda: {"source_fps": 58.0})
    monkeypatch.setattr(bridge.webrtc_track, "stats", lambda: {"sent_fps": 58.0, "stale_frames": 3})

    bridge._send_webrtc_stats()

    assert sent[0]["answer_sent_elapsed_ms"] == 42.0
    assert sent[0]["local_candidates_sent"] == 2


def test_drive_api_bridge_adds_matching_ice_candidate(monkeypatch):
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.RTCIceCandidate", FakeIceCandidate)
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.candidate_from_sdp", None)
    bridge = DriveApiBridge(auto_start=False)
    bridge.active_webrtc_session_id = "session-1"
    bridge.webrtc_peer = FakePeerConnection()

    bridge._handle_webrtc_signal({
        "type": "webrtc_signal",
        "signal_type": "ice",
        "session_id": "session-1",
        "candidate": {"candidate": "candidate:1", "sdpMid": "0", "sdpMLineIndex": 0},
    })

    assert len(bridge.webrtc_peer.candidates) == 1
    assert bridge.webrtc_peer.candidates[0].kwargs == {
        "candidate": "candidate:1",
        "sdpMid": "0",
        "sdpMLineIndex": 0,
    }


def test_drive_api_bridge_ignores_ice_for_stale_session(monkeypatch):
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.RTCIceCandidate", FakeIceCandidate)
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.candidate_from_sdp", None)
    bridge = DriveApiBridge(auto_start=False)
    bridge.active_webrtc_session_id = "session-1"
    bridge.webrtc_peer = FakePeerConnection()

    bridge._handle_webrtc_signal({
        "type": "webrtc_signal",
        "signal_type": "ice",
        "session_id": "stale-session",
        "candidate": {"candidate": "candidate:1"},
    })

    assert bridge.webrtc_peer.candidates == []


def test_drive_api_bridge_sends_webrtc_stats_when_session_active(monkeypatch):
    sent = []
    bridge = DriveApiBridge(auto_start=False)
    bridge.active_webrtc_session_id = "session-1"
    bridge.webrtc_peer = type("Peer", (), {
        "connectionState": "connected",
        "iceConnectionState": "completed",
        "iceGatheringState": "complete",
    })()
    monkeypatch.setattr(bridge, "_send_json", sent.append)
    monkeypatch.setattr(bridge.frame_buffer, "stats", lambda: {"source_fps": 60.0})
    monkeypatch.setattr(bridge.webrtc_track, "stats", lambda: {"sent_fps": 59.0, "stale_frames": 2})

    bridge._send_webrtc_stats()

    assert sent == [{
        "type": "webrtc_stats",
        "session_id": "session-1",
        "source_fps": 60.0,
        "sent_fps": 59.0,
        "stale_frames": 2,
        "peer_connection_state": "connected",
        "ice_connection_state": "completed",
        "ice_gathering_state": "complete",
        "local_description_error": None,
        "local_description_elapsed_ms": None,
        "answer_sent_elapsed_ms": None,
        "local_candidates_sent": 0,
    }]


def test_drive_api_bridge_does_not_send_webrtc_stats_without_session(monkeypatch):
    sent = []
    bridge = DriveApiBridge(auto_start=False)
    monkeypatch.setattr(bridge, "_send_json", sent.append)

    bridge._send_webrtc_stats()

    assert sent == []


class FakeLocalCandidate:
    sdpMid = "0"
    sdpMLineIndex = 0

    def to_sdp(self):
        return "candidate:local"


def test_drive_api_bridge_posts_local_ice_candidate():
    posted = []
    bridge = DriveApiBridge(auto_start=False)
    bridge.active_webrtc_session_id = "session-1"

    async def mock_post_webrtc_ice_async(session_id, candidate):
        posted.append((session_id, candidate))
    bridge._post_webrtc_ice_async = mock_post_webrtc_ice_async

    bridge._handle_local_ice_candidate(FakeLocalCandidate())

    assert posted == [("session-1", {
        "candidate": "candidate:local",
        "sdpMid": "0",
        "sdpMLineIndex": 0,
    })]


def test_drive_api_bridge_ignores_local_ice_without_session():
    posted = []
    bridge = DriveApiBridge(auto_start=False)

    async def mock_post_webrtc_ice_async(session_id, candidate):
        posted.append((session_id, candidate))
    bridge._post_webrtc_ice_async = mock_post_webrtc_ice_async

    bridge._handle_local_ice_candidate(FakeLocalCandidate())

    assert posted == []


def test_drive_api_bridge_parses_remote_ice_candidate(monkeypatch):
    parsed = []

    def fake_candidate_from_sdp(value):
        parsed.append(value)
        return {"parsed": value}

    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.candidate_from_sdp", fake_candidate_from_sdp)
    bridge = DriveApiBridge(auto_start=False)

    candidate = bridge._build_remote_ice_candidate({
        "candidate": "candidate:remote",
        "sdpMid": "0",
        "sdpMLineIndex": 0,
    })

    assert parsed == ["candidate:remote"]
    assert candidate == {"parsed": "candidate:remote", "sdpMid": "0", "sdpMLineIndex": 0}


def test_drive_api_bridge_sends_heartbeat_without_active_session(monkeypatch):
    sent = []
    bridge = DriveApiBridge(auto_start=False)
    monkeypatch.setattr(bridge, "_send_json", sent.append)

    bridge._send_heartbeat()

    assert sent == [{"type": "heartbeat"}]


def test_drive_api_bridge_webrtc_mode_sends_periodic_heartbeat_without_session(monkeypatch):
    sent = []
    timestamps = iter([10.0, 10.0, 13.1, 13.1])
    bridge = DriveApiBridge(auto_start=False, video_transport="webrtc")
    bridge.connected = True
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.time.time", lambda: next(timestamps))
    monkeypatch.setattr(bridge, "_send_json", sent.append)

    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    bridge.run_threaded(img_arr=frame)
    bridge.run_threaded(img_arr=frame)

    assert {"type": "heartbeat"} in sent


def test_drive_api_bridge_falls_back_to_mjpeg_when_webrtc_dependency_missing(monkeypatch):
    sent_frames = []
    bridge = DriveApiBridge(auto_start=False, video_transport="webrtc")
    bridge.connected = True
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.RTCPeerConnection", None)
    monkeypatch.setattr(bridge, "_send_frame", lambda *args, **kwargs: sent_frames.append(args))
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.time.time", lambda: 10.0)

    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    bridge.run_threaded(img_arr=frame, num_records=3, mode="user", recording=False)

    assert sent_frames == [(frame, 3, "user", False)]


def test_aiortc_video_track_reports_sent_stats(monkeypatch):
    timestamps = iter([0.0, 1.0 / 60.0])
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.av", FakeAvModule)
    buffer = DriveVideoFrameBuffer(width=320, height=240)
    track = DriveAiortcVideoTrack(buffer, fps=60, clock=lambda: next(timestamps))
    frame = np.zeros((240, 320, 3), dtype=np.uint8)

    buffer.update(frame)
    asyncio.run(track.recv())
    buffer.update(frame)
    asyncio.run(track.recv())

    stats = track.stats()
    assert round(stats["sent_fps"]) == 60
    assert stats["sent_frames"] == 2


def test_drive_api_bridge_falls_back_to_mjpeg_until_aiortc_track_sends(monkeypatch):
    sent_frames = []
    bridge = DriveApiBridge(auto_start=False, video_transport="webrtc")
    bridge.connected = True
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.RTCPeerConnection", object)
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.av", FakeAvModule)
    monkeypatch.setattr(bridge, "_send_frame", lambda *args, **kwargs: sent_frames.append(args))
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.time.time", lambda: 10.0)

    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    bridge.run_threaded(img_arr=frame, num_records=3, mode="user", recording=False)

    assert sent_frames == [(frame, 3, "user", False)]


def test_drive_api_bridge_stops_mjpeg_fallback_after_aiortc_track_sends(monkeypatch):
    sent_frames = []
    bridge = DriveApiBridge(auto_start=False, video_transport="webrtc")
    bridge.connected = True
    bridge.aiortc_track = type("Track", (), {"sent_frames": 1})()
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.RTCPeerConnection", object)
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.av", FakeAvModule)
    monkeypatch.setattr(bridge, "_send_frame", lambda *args, **kwargs: sent_frames.append(args))
    monkeypatch.setattr("donkeycar.parts.drive_api_bridge.time.time", lambda: 10.0)

    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    bridge.run_threaded(img_arr=frame, num_records=3, mode="user", recording=False)

    assert sent_frames == []


def test_drive_api_bridge_handles_reconnect_simulator():
    bridge = DriveApiBridge(server_url="ws://localhost:8000/api/drive/ws", auto_start=False)
    bridge._handle_message({"type": "reconnect_simulator"})

    assert bridge.reconnect_simulator is True

    outputs = bridge.run_threaded(img_arr=None, num_records=0, mode="user", recording=False)
    # outputs order: angle, throttle, mode, recording, buttons, reconnect_simulator
    assert len(outputs) == 6, f"expected 6 outputs, got {len(outputs)}: {outputs}"
    assert outputs[-1] is True
    assert bridge.reconnect_simulator is False
