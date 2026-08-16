# -*- coding: utf-8 -*-
"""issue #128 附带修复：Webcam 必须接收 CAMERA_FRAMERATE。

Webcam 默认 framerate=20，而 DRIVE_LOOP_HZ 可达 60：配置里的
CAMERA_FRAMERATE 原先对 WEBCAM 完全不生效，采集线程按 20Hz 节流，
主循环里同一帧被重复记录约 3 次。同时 stereo 分支原先传了
Webcam 不存在的 iCam 参数，一实例化即 TypeError。
"""
import re
from pathlib import Path

_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "donkeycar" / "templates"


def _webcam_calls(source: str) -> list[str]:
    """提取每个 Webcam(...) 完整调用（含跨行），排除 import 行。"""
    lines = [
        line for line in source.splitlines()
        if "import" not in line or "Webcam(" not in line
    ]
    source = "\n".join(lines)
    return re.findall(r"Webcam\([^)]*\)", source)


def test_complete_template_webcam_gets_framerate():
    source = (_TEMPLATES_DIR / "complete.py").read_text(encoding="utf-8")
    calls = _webcam_calls(source)
    assert calls, "complete.py should instantiate Webcam"
    for call in calls:
        assert "framerate=cfg.CAMERA_FRAMERATE" in call, (
            f"Webcam call must pass framerate=cfg.CAMERA_FRAMERATE: {call}"
        )


def test_complete_template_stereo_webcam_uses_camera_index():
    source = (_TEMPLATES_DIR / "complete.py").read_text(encoding="utf-8")
    # Webcam.__init__ 没有 iCam 参数（CvCam 才有），stereo 分支不能再用
    for call in _webcam_calls(source):
        assert "iCam" not in call, f"Webcam does not accept iCam: {call}"


def test_basic_template_webcam_gets_framerate():
    source = (_TEMPLATES_DIR / "basic.py").read_text(encoding="utf-8")
    calls = _webcam_calls(source)
    assert calls, "basic.py should instantiate Webcam"
    for call in calls:
        assert "framerate=cfg.CAMERA_FRAMERATE" in call, (
            f"Webcam call must pass framerate=cfg.CAMERA_FRAMERATE: {call}"
        )
