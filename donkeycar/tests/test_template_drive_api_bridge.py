from pathlib import Path


_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "donkeycar" / "templates"


def test_complete_template_uses_drive_api_bridge_when_server_url_is_set():
    source = (_TEMPLATES_DIR / "complete.py").read_text(encoding="utf-8")

    assert "from donkeydrifter.parts.drive_api_bridge import DriveApiBridge" in source
    assert "DRIVE_API_SERVER_URL" in source
    assert "DriveApiBridge(" in source
    assert "video_transport=getattr(cfg, \"DRIVE_VIDEO_TRANSPORT\", \"webrtc\")" in source
    assert "webrtc_ice_servers=getattr(cfg, \"DRIVE_WEBRTC_ICE_SERVERS\", None)" in source
    assert "LocalWebController(port=cfg.WEB_CONTROL_PORT" in source


def test_basic_template_uses_drive_api_bridge_when_server_url_is_set():
    source = (_TEMPLATES_DIR / "basic.py").read_text(encoding="utf-8")

    assert "from donkeydrifter.parts.drive_api_bridge import DriveApiBridge" in source
    assert "DRIVE_API_SERVER_URL" in source
    assert "DriveApiBridge(" in source
    assert "video_transport=getattr(cfg, \"DRIVE_VIDEO_TRANSPORT\", \"webrtc\")" in source
    assert "webrtc_ice_servers=getattr(cfg, \"DRIVE_WEBRTC_ICE_SERVERS\", None)" in source
    assert "LocalWebController(port=cfg.WEB_CONTROL_PORT" in source
    assert "'web/buttons'" in source


def test_default_configs_define_webrtc_video_options():
    for filename in ["cfg_basic.py", "cfg_complete.py", "myconfig.py"]:
        source = (_TEMPLATES_DIR / filename).read_text(encoding="utf-8")

        assert "DRIVE_VIDEO_TRANSPORT" in source
        assert "DRIVE_VIDEO_WIDTH" in source
        assert "DRIVE_VIDEO_HEIGHT" in source
        assert "DRIVE_VIDEO_FPS" in source
        assert "DRIVE_WEBRTC_ENABLED" in source
        assert "DRIVE_WEBRTC_ICE_SERVERS" in source
