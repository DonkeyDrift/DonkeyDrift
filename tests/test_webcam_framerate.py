# -*- coding: utf-8 -*-
"""issue #128 附带修复：Webcam 必须接收 CAMERA_FRAMERATE。

Webcam 默认 framerate=20，而 DRIVE_LOOP_HZ 可达 60：配置里的
CAMERA_FRAMERATE 原先对 WEBCAM 完全不生效，采集线程按 20Hz 节流，
主循环里同一帧被重复记录约 3 次。同时 stereo 分支原先传了
Webcam 不存在的 iCam 参数，一实例化即 TypeError。
"""
import re
import sys
import types
from pathlib import Path

import numpy as np

from donkeycar.parts.camera import Webcam

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


# ---------------------------------------------------------------------------
# issue #513：Webcam 灰度分支
# ---------------------------------------------------------------------------

class _FakePygameCamera:
    """pygame.camera.Camera 替身：永远报告有一帧可抓。"""

    def __init__(self, device, resolution, fmt):
        self.device = device
        self.resolution = resolution
        self.fmt = fmt
        self.started = False

    def start(self):
        self.started = True

    def query_image(self):
        return True

    def get_image(self):
        return "fake-surface"

    def stop(self):
        self.started = False


def _fake_rgb_frame():
    return np.arange(160 * 120 * 3, dtype=np.uint8).reshape(160, 120, 3)


def _install_fake_pygame(monkeypatch, rgb_frame):
    """注入假 pygame 模块，抓帧恒定返回给定的 uint8 RGB 帧。"""
    pygame = types.ModuleType("pygame")
    camera = types.ModuleType("pygame.camera")
    image = types.ModuleType("pygame.image")
    transform = types.ModuleType("pygame.transform")
    surfarray = types.ModuleType("pygame.surfarray")

    pygame.init = lambda: None
    pygame.camera = camera
    pygame.image = image
    pygame.transform = transform
    pygame.surfarray = surfarray

    camera.init = lambda: None
    camera.list_cameras = lambda: ["/dev/fake0"]
    camera.Camera = _FakePygameCamera

    transform.scale = lambda surface, resolution: surface
    transform.rotate = lambda surface, angle: surface
    transform.flip = lambda surface, x, y: surface
    surfarray.pixels3d = lambda surface: rgb_frame

    for name, module in {
        "pygame": pygame,
        "pygame.camera": camera,
        "pygame.image": image,
        "pygame.transform": transform,
        "pygame.surfarray": surfarray,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)


def test_webcam_image_d1_warmup_and_run_return_uint8_grayscale(monkeypatch):
    rgb_frame = _fake_rgb_frame()
    _install_fake_pygame(monkeypatch, rgb_frame)

    cam = Webcam(image_w=160, image_h=120, image_d=1)

    expected = np.round(
        np.dot(rgb_frame, [0.299, 0.587, 0.114])).astype(np.uint8)
    assert cam.frame is not None
    assert cam.frame.shape == (160, 120)
    assert cam.frame.dtype == np.uint8
    assert np.array_equal(cam.frame, expected)

    result = cam.run()
    assert result.shape == (160, 120)
    assert result.dtype == np.uint8
    assert np.array_equal(result, expected)


def test_webcam_image_d3_run_returns_uint8_rgb_guard(monkeypatch):
    rgb_frame = _fake_rgb_frame()
    _install_fake_pygame(monkeypatch, rgb_frame)

    cam = Webcam(image_w=160, image_h=120, image_d=3)

    assert cam.frame.shape == (160, 120, 3)
    assert cam.frame.dtype == np.uint8
    assert np.array_equal(cam.frame, rgb_frame)

    result = cam.run()
    assert result.shape == (160, 120, 3)
    assert result.dtype == np.uint8
    assert np.array_equal(result, rgb_frame)
