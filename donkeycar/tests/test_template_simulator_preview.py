"""验证 simulator.py 模板的预览分辨率解耦接线。

simulator.py 应：1) DonkeyGymEnv 输出 cam/image_array（NN）+ preview/image_array（预览原始帧）；
2) DriveApiBridge 以 preview/image_array 作为视频源；3) 构造参数带上 jpeg_quality 与
preserve_source_resolution，且 DonkeyGymEnv 开启 output_preview。
"""
import ast
from pathlib import Path

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "donkeycar" / "templates"
_SOURCE = (_TEMPLATES_DIR / "simulator.py").read_text(encoding="utf-8")


def _vadd_calls():
    tree = ast.parse(_SOURCE)
    calls = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "V"
            and node.func.attr == "add"
        ):
            calls.append(node)
    return calls


def _kw_list(call, name):
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, (ast.List, ast.Tuple)):
            return ast.literal_eval(kw.value)
    return None


def test_cam_outputs_include_preview_image_array():
    cam = next(c for c in _vadd_calls() if isinstance(c.args[0], ast.Name) and c.args[0].id == "cam")
    outputs = _kw_list(cam, "outputs")
    assert outputs == ["cam/image_array", "preview/image_array"]


def test_bridge_consumes_preview_image_array():
    bridge = None
    for c in _vadd_calls():
        if isinstance(c.args[0], ast.Name) and c.args[0].id == "ctr":
            inputs = _kw_list(c, "inputs")
            if inputs and "preview/image_array" in inputs:
                bridge = c
                break
    assert bridge is not None, "DriveApiBridge 未以 preview/image_array 作为视频源"
    inputs = _kw_list(bridge, "inputs")
    assert inputs[0] == "preview/image_array"


def test_drive_api_bridge_constructor_configures_quality():
    assert 'jpeg_quality=getattr(cfg, "DRIVE_VIDEO_JPEG_QUALITY", 95)' in _SOURCE
    assert "preserve_source_resolution=True" in _SOURCE


def test_donkey_gym_env_enables_output_preview():
    assert "output_preview=True" in _SOURCE


def test_simulator_config_defines_render_and_jpeg_quality():
    cfg = (_TEMPLATES_DIR / "cfg_simulator.py").read_text(encoding="utf-8")
    assert "render_img_w" in cfg
    assert "render_img_h" in cfg
    assert "DRIVE_VIDEO_JPEG_QUALITY" in cfg


def test_complete_config_defines_jpeg_quality():
    cfg = (_TEMPLATES_DIR / "cfg_complete.py").read_text(encoding="utf-8")
    assert "DRIVE_VIDEO_JPEG_QUALITY" in cfg
