import base64
import json

from donkeycar.parts.drive_api_bridge import DriveApiBridge
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
    bridge = DriveApiBridge(auto_start=False)
    bridge.connected = True

    monkeypatch.setattr(
        "donkeycar.parts.drive_api_bridge.cv2.imencode",
        lambda extension, image: (True, FakeEncodedFrame()),
    )
    monkeypatch.setattr(bridge, "_send_json", sent_payloads.append)

    outputs = bridge.run_threaded(img_arr=object(), num_records=7, mode="user", recording=False)

    assert outputs == (0.0, 0.0, "user", False, {})
    assert sent_payloads == [{
        "type": "frame",
        "data": base64.b64encode(b"jpeg-bytes").decode("ascii"),
        "num_records": 7,
        "drive_mode": "user",
        "recording": False,
    }]
