import re
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


def test_complete_template_wires_rc_telemetry_into_bridge():
    """complete 模板必须把 ArdRc 产出的 rc/* 键接进 DriveApiBridge 遥测输入末尾。

    Drive 页默认开启的 RC 油门/转向曲线、驾驶模式跟随与 Park 锁定徽标都依赖
    telemetry 消息里的 rc_* 字段；ctr_inputs 若漏接（2026-09-26 前的实际状态），
    ArdRc 写入 Memory 的 rc/* 永远到不了浏览器，曲线整组空白。键序必须与
    run_threaded 签名位置对齐：pilot/throttle 之后依次是
    rc/steering、rc/throttle、rc/mode、rc/park。
    """
    source = (_TEMPLATES_DIR / "complete.py").read_text(encoding="utf-8")
    m = re.search(r"ctr_inputs\s*=\s*\[(.*?)\]", source, re.DOTALL)
    assert m, "complete.py 未找到 ctr_inputs 列表"
    keys = re.findall(r"'([^']+)'", m.group(1))
    assert "pilot/throttle" in keys, "ctr_inputs 缺少 pilot/throttle 基准位"
    tail = keys[keys.index("pilot/throttle") + 1:]
    assert tail == ["rc/steering", "rc/throttle", "rc/mode", "rc/park"], (
        f"rc/* 接线缺失或顺序错误: {tail}"
    )
    # rc/* 的生产者必须在模板中注册（ArdRc 从固件 T..S../M:P 帧解析）。
    assert "ArdRc(controller=arduino_controller)" in source
    assert "outputs=['rc/steering', 'rc/throttle', 'rc/mode', 'rc/park']" in source


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
