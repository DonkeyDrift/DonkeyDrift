# -*- coding: utf-8 -*-
"""drift_vision 单元测试：单应性映射、位姿解算、相机/检测器抽象。

合成数据驱动的纯计算测试——不依赖真实相机与 AprilTag 库
（后端库明天实机联调，今晚用 FakeTagDetector/FakeCamera 验证几何逻辑）。
"""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from drift_vision import (
    FieldHomography,
    PoseSolver,
    solve_tag_pose,
)


# 场地坐标约定：x 向东、y 向北（米），原点在场地西南角；图像 y 轴向下。
FIELD_W, FIELD_H = 2.0, 2.0
# 图像四角（640×480）↔ 场地四角（含 y 翻转：图像上边对应场地北边）
IMG_CORNERS = np.float32([[0, 0], [639, 0], [639, 479], [0, 479]])
FIELD_CORNERS = np.float32([[0, FIELD_H], [FIELD_W, FIELD_H], [FIELD_W, 0], [0, 0]])


@pytest.fixture
def homography():
    return FieldHomography.from_correspondences(IMG_CORNERS, FIELD_CORNERS)


class TestFieldHomography:
    def test_center_maps_to_field_center(self, homography):
        cx, cy = homography.image_to_field(639 / 2, 479 / 2)
        assert cx == pytest.approx(FIELD_W / 2, abs=1e-6)
        assert cy == pytest.approx(FIELD_H / 2, abs=1e-6)

    def test_round_trip_consistency(self, homography):
        for px, py in [(30, 40), (600, 450), (320, 100)]:
            fx, fy = homography.image_to_field(px, py)
            qx, qy = homography.field_to_image(fx, fy)
            assert qx == pytest.approx(px, abs=1e-6)
            assert qy == pytest.approx(py, abs=1e-6)

    def test_y_axis_is_flipped(self, homography):
        """图像上方(y小)对应场地北侧(y大)——俯拍相机的朝向约定。"""
        _, fy_top = homography.image_to_field(320, 0)
        _, fy_bottom = homography.image_to_field(320, 479)
        assert fy_top > fy_bottom


class TestPoseSolving:
    def _make_tag_corners(self, homography, cx, cy, heading_deg, size_m=0.08):
        """在场地 (cx,cy) 处构造朝向 heading 的车顶标签四角（图像坐标）。

        约定 corners = [前左, 前右, 后右, 后左]（车体系，前=车头方向）。
        """
        h = math.radians(heading_deg)
        half = size_m / 2
        # 车体系四个角（前左/前右/后右/后左），x 前进、y 左舷（右手系）
        body = np.array([[-half, -half], [half, -half], [half, half], [-half, half]])
        rot = np.array([[math.cos(h), -math.sin(h)], [math.sin(h), math.cos(h)]])
        corners_field = (body @ rot.T) + np.array([cx, cy])
        corners_img = np.float32([
            homography.field_to_image(*p) for p in corners_field])
        return corners_img

    @pytest.mark.parametrize("cx,cy,heading", [
        (1.0, 1.0, 0.0), (0.5, 1.5, 90.0), (1.6, 0.4, -135.0), (1.0, 1.0, 179.0),
    ])
    def test_pose_recovered_within_tolerance(self, homography, cx, cy, heading):
        corners = self._make_tag_corners(homography, cx, cy, heading)
        pose = solve_tag_pose(homography, corners)
        assert pose.x == pytest.approx(cx, abs=0.01), "位置误差应 <1cm"
        assert pose.y == pytest.approx(cy, abs=0.01)
        # 角度差按环回最短差值比较
        dh = (pose.heading_deg - heading + 180) % 360 - 180
        assert abs(dh) < 1.0, "朝向误差应 <1°"

    def test_heading_wraps_correctly(self, homography):
        corners = self._make_tag_corners(homography, 1.0, 1.0, -179.0)
        pose = solve_tag_pose(homography, corners)
        dh = (pose.heading_deg - (-179.0) + 180) % 360 - 180
        assert abs(dh) < 1.0
        assert -180.0 <= pose.heading_deg <= 180.0

    @pytest.mark.parametrize("offset,heading", [
        (180.0, 0.0), (180.0, 90.0), (90.0, -45.0), (-90.0, 120.0),
    ])
    def test_heading_offset_compensates_tag_mount_rotation(
            self, homography, offset, heading):
        """标签贴上车顶时整体旋转了 offset 度：用 heading_offset_deg
        补偿后，解算朝向应恢复"视觉前边方向 = 真朝向 + offset"。"""
        corners = self._make_tag_corners(homography, 1.0, 1.0, heading)
        pose = solve_tag_pose(homography, corners,
                              heading_offset_deg=offset)
        dh = (pose.heading_deg - (heading + offset) + 180) % 360 - 180
        assert abs(dh) < 1.0
        assert -180.0 <= pose.heading_deg <= 180.0


class TestPoseSolverSmoothing:
    def test_outlier_is_rejected(self, homography):
        """单帧离群位姿被滑动窗中值拒绝（防标签误检跳变）。"""
        from drift_vision import Pose
        solver = PoseSolver(homography, window=5, max_jump_m=0.5)
        for i in range(5):
            solver.push(Pose(x=1.0, y=1.0, heading_deg=10.0, t_s=0.1 * i))
        # 第 6 帧离群跳变 1.5m（>0.5m 门限）→ 被拒，输出仍用中值
        out = solver.push(Pose(x=2.5, y=1.0, heading_deg=10.0, t_s=0.5))
        assert out.x == pytest.approx(1.0, abs=0.05)

    def test_normal_sequence_passes_through(self, homography):
        from drift_vision import Pose
        solver = PoseSolver(homography, window=5, max_jump_m=0.5)
        last = None
        for i in range(10):
            last = solver.push(Pose(x=1.0 + 0.01 * i, y=1.0, heading_deg=10.0, t_s=0.1 * i))
        assert last.x == pytest.approx(1.09, abs=0.05)


class TestCameraAbstraction:
    def test_fake_camera_yields_monotonic_timestamps(self):
        from drift_vision import FakeCamera
        cam = FakeCamera()
        stamps = [cam.read()[1] for _ in range(5)]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), "时间戳必须严格单调"

    def test_detector_backend_missing_raises_clearly(self, monkeypatch):
        """pupil-apriltags 不可用时，构造 AprilTagDetector 应报清晰错误而非静默降级。"""
        import drift_vision
        monkeypatch.setattr(drift_vision, "_PUPIL_APRILTAGS_AVAILABLE", False)
        with pytest.raises(RuntimeError, match="pupil-apriltags"):
            drift_vision.AprilTagDetector()


class TestOverlayDrawing:
    def test_draw_tag_overlay_marks_frame(self, homography):
        """叠加绘制应在帧上画出标签框（绿）与车头箭头（红）。"""
        from drift_vision import Pose, draw_tag_overlay
        import cv2
        frame = np.full((480, 640, 3), 255, dtype=np.uint8)
        corners = self._mk(homography) if False else None
        # 在场地 (1.0,1.0) 处朝东的标签四角（复用位姿测试的构造）
        h = math.radians(0.0)
        body = np.array([[-0.04, -0.04], [0.04, -0.04], [0.04, 0.04], [-0.04, 0.04]])
        rot = np.array([[math.cos(h), -math.sin(h)], [math.sin(h), math.cos(h)]])
        corners = np.float32([
            homography.field_to_image(*p) for p in (body @ rot.T + np.array([1.0, 1.0]))])
        pose = Pose(x=1.0, y=1.0, heading_deg=0.0, t_s=0.0)
        out = draw_tag_overlay(frame, homography, corners, pose)
        b = out.reshape(-1, 3)
        has_green = ((b[:, 1] > 200) & (b[:, 0] < 100) & (b[:, 2] < 100)).any()
        has_red = ((b[:, 2] > 200) & (b[:, 0] < 100) & (b[:, 1] < 100)).any()
        assert has_green, "应画出绿色标签框"
        assert has_red, "应画出红色车头箭头"
