from pathlib import Path


_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "donkeycar" / "templates"


def test_complete_template_uses_drive_api_bridge_when_server_url_is_set():
    source = (_TEMPLATES_DIR / "complete.py").read_text(encoding="utf-8")

    assert "from donkeydrifter.parts.drive_api_bridge import DriveApiBridge" in source
    assert "DRIVE_API_SERVER_URL" in source
    assert "DriveApiBridge(" in source
    assert "video_transport=getattr(cfg, \"DRIVE_VIDEO_TRANSPORT\", \"webrtc\")" in source
    assert "webrtc_ice_servers=getattr(cfg, \"DRIVE_WEBRTC_ICE_SERVERS\", None)" in source
    assert "LocalWebController" not in source
    assert "WebFpv" not in source


def test_complete_template_drive_api_bridge_outputs_include_car_mode_cmd():
    """complete 模板的 DriveApiBridge 输出须按 7 元组顺序对齐，car/mode_cmd 落到第 7 位。

    run_threaded 返回 (angle, throttle, mode, recording, buttons,
    reconnect_simulator, car_mode_cmd)。outputs 若少写 reconnect_simulator，
    car/mode_cmd 会错接到 reconnect_simulator 布尔值，导致车控模式命令失效。
    """
    source = (_TEMPLATES_DIR / "complete.py").read_text(encoding="utf-8")
    expected = (
        "outputs=['user/steering', 'user/throttle', 'user/mode', "
        "'recording', 'web/buttons', 'reconnect_simulator', 'car/mode_cmd']"
    )
    assert expected in source


def test_basic_template_uses_drive_api_bridge_when_server_url_is_set():
    source = (_TEMPLATES_DIR / "basic.py").read_text(encoding="utf-8")

    assert "from donkeydrifter.parts.drive_api_bridge import DriveApiBridge" in source
    assert "DRIVE_API_SERVER_URL" in source
    assert "DriveApiBridge(" in source
    assert "video_transport=getattr(cfg, \"DRIVE_VIDEO_TRANSPORT\", \"webrtc\")" in source
    assert "webrtc_ice_servers=getattr(cfg, \"DRIVE_WEBRTC_ICE_SERVERS\", None)" in source
    assert "LocalWebController" not in source
    assert "WebFpv" not in source
    assert "'web/buttons'" in source


def test_templates_default_to_local_web_ui_server_url():
    """阶段1：未显式配置 DRIVE_API_SERVER_URL 时，默认连本机新 Web UI 后端。"""
    default_url = '"ws://127.0.0.1:8000/api/drive/ws"'
    for filename in ["complete.py", "basic.py"]:
        source = (_TEMPLATES_DIR / filename).read_text(encoding="utf-8")

        assert default_url in source, f"{filename} 未包含默认 DRIVE_API_SERVER_URL"


def test_simulator_and_square_templates_dropped_local_web_controller():
    """阶段2：simulator/square 模板不再使用 LocalWebController / WebFpv。"""
    for filename in ["simulator.py", "square.py"]:
        source = (_TEMPLATES_DIR / filename).read_text(encoding="utf-8")

        assert "LocalWebController" not in source, f"{filename} 仍引用 LocalWebController"
        assert "WebFpv" not in source, f"{filename} 仍引用 WebFpv"


def test_default_configs_define_webrtc_video_options():
    for filename in ["cfg_basic.py", "cfg_complete.py", "myconfig.py"]:
        source = (_TEMPLATES_DIR / filename).read_text(encoding="utf-8")

        assert "DRIVE_VIDEO_TRANSPORT" in source
        assert "DRIVE_VIDEO_WIDTH" in source
        assert "DRIVE_VIDEO_HEIGHT" in source
        assert "DRIVE_VIDEO_FPS" in source
        assert "DRIVE_WEBRTC_ENABLED" in source
        assert "DRIVE_WEBRTC_ICE_SERVERS" in source
