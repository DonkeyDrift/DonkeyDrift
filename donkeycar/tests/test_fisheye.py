# -*- coding: utf-8 -*-
"""鱼眼去畸变图像变换（FISHEYE）的单元测试。"""
import importlib.util
import os
import sys
import types

import cv2
import numpy as np
import pytest

from donkeycar.parts import fisheye
from donkeycar.parts.image_transformations import image_transformer


def make_fisheye_frame(w=320, h=240, cx=160, cy=120, r=110):
    """构造一张合成鱼眼图：黑底 + 白色成像圆 + 圆内网格线。"""
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.circle(frame, (cx, cy), r, (255, 255, 255), -1)
    for x in range(cx - r, cx + r + 1, 20):
        cv2.line(frame, (x, cy - r), (x, cy + r), (0, 0, 0), 1)
    for y in range(cy - r, cy + r + 1, 20):
        cv2.line(frame, (cx - r, y), (cx + r, y), (0, 0, 0), 1)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.circle(mask, (cx, cy), r, 255, -1)
    frame[mask == 0] = 0
    return frame


def test_estimate_image_circle():
    frame = make_fisheye_frame()
    cx, cy, r = fisheye.estimate_image_circle(frame)
    assert abs(cx - 160) < 6
    assert abs(cy - 120) < 6
    assert abs(r - 110) < 8


def test_estimate_image_circle_raises_on_blank():
    with pytest.raises(ValueError):
        fisheye.estimate_image_circle(np.zeros((240, 320, 3), dtype=np.uint8))


def test_undistort_shape_and_no_black():
    frame = make_fisheye_frame()
    cfg = types.SimpleNamespace(IMAGE_W=320, IMAGE_H=240, FISHEYE_CIRCLE=(160, 120, 108))
    part = fisheye.FisheyeUndistort(cfg)
    out = part.run(frame)
    assert out.shape == frame.shape
    assert part.out_fov is not None and 30 < part.out_fov < 179
    gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    assert (gray < 20).mean() < 0.02  # 去畸变后基本无黑边


def test_undistort_resize_to_target():
    frame = make_fisheye_frame()
    cfg = types.SimpleNamespace(IMAGE_W=320, IMAGE_H=240,
                                FISHEYE_WIDTH=160, FISHEYE_HEIGHT=120)
    out = fisheye.FisheyeUndistort(cfg).run(frame)
    assert out.shape == (120, 160, 3)


def test_fixed_output_fov():
    frame = make_fisheye_frame()
    cfg = types.SimpleNamespace(IMAGE_W=320, IMAGE_H=240, FISHEYE_OUT_FOV_DEG=90.0)
    part = fisheye.FisheyeUndistort(cfg)
    part.run(frame)
    assert abs(part.out_fov - 90.0) < 1.0


def test_run_none_returns_none():
    cfg = types.SimpleNamespace(IMAGE_W=320, IMAGE_H=240)
    assert fisheye.FisheyeUndistort(cfg).run(None) is None


def test_factory_registration():
    cfg = types.SimpleNamespace(IMAGE_W=320, IMAGE_H=240)
    part = image_transformer("FISHEYE", cfg)
    assert isinstance(part, fisheye.FisheyeUndistort)


def _load_undistort_tub_module():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "scripts", "undistort_tub.py")
    spec = importlib.util.spec_from_file_location("undistort_tub", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_undistort_tub_end_to_end(tmp_path, monkeypatch):
    from donkeycar.parts.tub_v2 import Tub

    src = str(tmp_path / "data")
    dst = str(tmp_path / "data_undistorted")
    tub = Tub(src, inputs=["cam/image_array"], types=["image_array"])
    for i in range(3):
        frame = make_fisheye_frame()
        frame[100:140, 140:180] = (i * 40, 200, 100)  # 保证每帧不同
        tub.write_record({"cam/image_array": frame})
    tub.close()

    module = _load_undistort_tub_module()
    monkeypatch.setattr(sys, "argv", ["undistort_tub.py", "--tub", src, "--out", dst,
                                      "--workers", "1"])
    assert module.main() == 0

    # 元数据原样复制，文件名保持不变
    assert os.path.exists(os.path.join(dst, "manifest.json"))
    out_images = sorted(os.listdir(os.path.join(dst, "images")))
    assert out_images == ["0_cam_image_array_.jpg", "1_cam_image_array_.jpg",
                          "2_cam_image_array_.jpg"]
    # 输出仍可被 tub 读取（len 不变）
    out_tub = Tub(dst, read_only=True)
    assert len(out_tub) == len(tub)
    out_tub.close()
    # 图像仍为 320x240 且已去畸变（左上角不再是纯黑）
    out_img = cv2.cvtColor(cv2.imread(os.path.join(dst, "images", "0_cam_image_array_.jpg")),
                           cv2.COLOR_BGR2GRAY)
    assert out_img.shape == (240, 320)
    assert out_img[:6, :6].mean() > 30

