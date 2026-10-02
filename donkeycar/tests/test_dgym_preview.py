"""
DonkeyGymEnv 渲染分辨率与 NN 输入分辨率解耦的单测。

验证：设置 render_img_w/render_img_h 后，向模拟器请求更高渲染分辨率，
dgym 内部把渲染帧下采样回 img_w×img_h 作为 cam/image_array（NN 输入），
并把渲染原始帧作为 preview/image_array；未设置 render 键时缺省按
1920×1080 全高清渲染（Drive 页面用户看到的必须是最高画质）。
"""
import numpy as np
import pytest
from unittest.mock import patch

pytest.importorskip("gym_donkeycar")

from donkeycar.parts.dgym import DonkeyGymEnv


class FakeHighResEnv:
    """返回 480×640 渲染帧的假模拟器环境。"""
    def reset(self):
        return np.zeros((480, 640, 3), dtype=np.uint8), {}

    def step(self, action):
        return np.zeros((480, 640, 3), dtype=np.uint8), 0.0, False, False, {}

    def close(self):
        pass


class FakeLowResEnv:
    """返回 120×160 渲染帧的假模拟器环境。"""
    def reset(self):
        return np.zeros((120, 160, 3), dtype=np.uint8), {}

    def step(self, action):
        return np.zeros((120, 160, 3), dtype=np.uint8), 0.0, False, False, {}

    def close(self):
        pass


class FakeFullHdEnv:
    """返回 1080×1920 全高清渲染帧的假模拟器环境。"""
    def reset(self):
        return np.zeros((1080, 1920, 3), dtype=np.uint8), {}

    def step(self, action):
        return np.zeros((1080, 1920, 3), dtype=np.uint8), 0.0, False, False, {}

    def close(self):
        pass


def test_requests_render_resolution_from_simulator():
    captured = {}

    def fake_make(env_name, conf=None):
        captured.update(conf or {})
        return FakeHighResEnv()

    with patch("donkeycar.parts.dgym.gym.make", side_effect=fake_make):
        DonkeyGymEnv(
            sim_path="remote",
            conf={"img_h": 120, "img_w": 160, "render_img_h": 480, "render_img_w": 640},
        )

    assert captured["img_w"] == 640
    assert captured["img_h"] == 480
    assert captured["cam_resolution"] == (480, 640, 3)


def test_downsample_nn_input_and_keep_preview_resolution():
    with patch("donkeycar.parts.dgym.gym.make", return_value=FakeHighResEnv()):
        env = DonkeyGymEnv(
            sim_path="remote",
            conf={"img_h": 120, "img_w": 160, "render_img_h": 480, "render_img_w": 640},
        )

    assert env.frame.shape == (120, 160, 3)  # NN 输入（cam/image_array）
    assert env.preview_frame.shape == (480, 640, 3)  # 预览帧（preview/image_array）


def test_no_render_keys_defaults_to_fullhd_render():
    captured = {}

    def fake_make(env_name, conf=None):
        captured.update(conf or {})
        return FakeFullHdEnv()

    with patch("donkeycar.parts.dgym.gym.make", side_effect=fake_make):
        env = DonkeyGymEnv(sim_path="remote", conf={"img_h": 120, "img_w": 160})

    # 未设置 render_img_w/h：缺省按 1920×1080 全高清渲染（Drive 页必须最高画质），
    # NN 输入仍下采样回 img_w×img_h
    assert captured["img_w"] == 1920
    assert captured["img_h"] == 1080
    assert captured["cam_resolution"] == (1080, 1920, 3)
    assert env.frame.shape == (120, 160, 3)
    assert env.preview_frame.shape == (1080, 1920, 3)


def test_run_threaded_outputs_preview_when_enabled():
    with patch("donkeycar.parts.dgym.gym.make", return_value=FakeHighResEnv()):
        env = DonkeyGymEnv(
            sim_path="remote",
            conf={"img_h": 120, "img_w": 160, "render_img_h": 480, "render_img_w": 640},
            output_preview=True,
        )

    result = env.run_threaded(0.0, 0.0)
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0].shape == (120, 160, 3)  # cam/image_array
    assert result[1].shape == (480, 640, 3)  # preview/image_array


def test_run_threaded_without_preview_keeps_scalar_return():
    with patch("donkeycar.parts.dgym.gym.make", return_value=FakeLowResEnv()):
        env = DonkeyGymEnv(sim_path="remote", conf={"img_h": 120, "img_w": 160})

    result = env.run_threaded(0.0, 0.0)
    assert not isinstance(result, list)  # 保持旧的标量返回（向后兼容）
    assert result.shape == (120, 160, 3)
