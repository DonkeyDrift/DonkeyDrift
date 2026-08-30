# -*- coding: utf-8 -*-
"""drift_vision 单元测试：单应性映射、位姿解算、相机/检测器抽象。

合成数据驱动的纯计算测试——不依赖真实相机与 AprilTag 库
（后端库明天实机联调，今晚用 FakeTagDetector/FakeCamera 验证几何逻辑）。
"""
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from drift_vision import (
    FakeCamera,
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

    def test_sustained_jump_recovers(self, homography):
        """检测缺口期间车真实移过 0.5m：连续 window 帧一致的新位姿必须
        被采信恢复跟踪，否则位姿/箭头会永久冻结在缺口前的中值上
        （实车现象：快推后红箭头跟不上，绿框正常）。"""
        from drift_vision import Pose
        solver = PoseSolver(homography, window=5, max_jump_m=0.5)
        for i in range(5):
            solver.push(Pose(x=1.0, y=1.0, heading_deg=10.0, t_s=0.1 * i))
        # 检测缺口后恢复：车已在 1.2m 外，且新位姿连续稳定出现
        out = None
        for i in range(5):
            out = solver.push(Pose(x=2.2, y=1.0, heading_deg=10.0,
                                   t_s=0.6 + 0.1 * i))
        assert out.x == pytest.approx(2.2, abs=0.05), \
            "持续一致的新位姿必须被采信，不得永久锁定在旧中值"


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


class TestUSBCameraExposure:
    """手动曝光链路（运动模糊的根因控制）：快推时 16ms 曝光把标签拖成
    20~40% 涂抹，任何分辨率/锐化都救不回；必须把曝光压到 ~1/250s。

    DirectShow 语义：CAP_PROP_EXPOSURE 的值是 log2(秒)（-7=1/128s），
    且必须先关自动曝光（DSHOW 约定 0.25=手动、0.75=自动），否则手动值
    被驱动忽略。旧的 exposure_us 参数语义与 DSHOW 不符，已重构。
    """

    @staticmethod
    def _fake_capture(monkeypatch):
        import cv2
        calls = []

        class FakeCap:
            def __init__(self, index, backend):
                pass

            def set(self, prop, value):
                calls.append((prop, value))
                return True

            def isOpened(self):
                return True

        monkeypatch.setattr(cv2, "VideoCapture", FakeCap)
        return calls, cv2

    def test_manual_exposure_disables_auto_first(self, monkeypatch):
        """手动曝光：先关自动，再设曝光值（顺序错误会被驱动忽略）。"""
        calls, cv2 = self._fake_capture(monkeypatch)
        from drift_vision import USBCamera
        USBCamera(index=1, exposure=-7.0)
        auto_idx = next(i for i, (p, v) in enumerate(calls)
                        if p == cv2.CAP_PROP_AUTO_EXPOSURE)
        exp_idx = next(i for i, (p, v) in enumerate(calls)
                       if p == cv2.CAP_PROP_EXPOSURE)
        assert calls[auto_idx][1] == 0.25, "DSHOW 手动曝光约定值 0.25"
        assert calls[exp_idx][1] == -7.0
        assert auto_idx < exp_idx, "必须先关自动曝光再设曝光值"

    def test_default_keeps_auto_exposure(self, monkeypatch):
        """不传曝光：完全不动曝光属性（行为与旧版一致）。"""
        calls, cv2 = self._fake_capture(monkeypatch)
        from drift_vision import USBCamera
        USBCamera(index=1)
        assert not any(p in (cv2.CAP_PROP_AUTO_EXPOSURE, cv2.CAP_PROP_EXPOSURE)
                       for p, _ in calls)


class TestAdaptiveDetection:
    """运动模糊下的检测余量：decode_sharpening + 半分辨率未检出时全分辨率重试。

    实车现象：快推时 360p 下标签 ~39px 接近 AprilTag 检测下限，模糊帧
    检测丢失/解出垃圾朝向；720p 下标签 78px 余量翻倍。好帧仍走半分辨率
    保持 60fps，只有难帧付全分辨率检测的 ~30ms 代价。
    """

    @staticmethod
    def _fake_pupil(monkeypatch, hit_shapes, recorded):
        """造一个 pupil Detector 替身：仅当灰度图尺寸命中 hit_shapes 时检出。"""
        import drift_vision

        class FakePupil:
            def __init__(self, families, **kwargs):
                recorded["init_kwargs"] = kwargs

            def detect(self, gray):
                recorded["shapes"].append(gray.shape)
                if gray.shape[:2] in hit_shapes:
                    from types import SimpleNamespace
                    return [SimpleNamespace(
                        tag_id=0,
                        corners=np.array([[10, 10], [20, 10], [20, 20], [10, 20]],
                                         dtype=np.float32))]
                return []

        monkeypatch.setattr(drift_vision, "_PupilDetector", FakePupil)

    def test_sharpening_passed_to_backend(self, monkeypatch):
        """decode_sharpening 提升模糊标签解码率，默认必须高于库默认 0.25。"""
        import drift_vision
        recorded = {"shapes": []}
        self._fake_pupil(monkeypatch, set(), recorded)
        det = drift_vision.AprilTagDetector(downscale=2)
        assert recorded["init_kwargs"].get("decode_sharpening", 0) > 0.25
        assert det is not None

    def test_half_res_hit_skips_full_res(self, monkeypatch):
        """半分辨率命中时不做全分辨率重试，角点按倍率还原。"""
        import drift_vision
        recorded = {"shapes": []}
        self._fake_pupil(monkeypatch, {(360, 640)}, recorded)
        det = drift_vision.AprilTagDetector(downscale=2)
        dets = det.detect(np.zeros((720, 1280, 3), np.uint8))
        assert len(dets) == 1
        assert recorded["shapes"] == [(360, 640)], "好帧不得付出全分辨率代价"
        assert dets[0].corners[1, 0] == pytest.approx(40.0)  # 20 × 2 还原

    def test_full_res_retry_on_miss(self, monkeypatch):
        """半分辨率未检出时用全分辨率重试，命中角点不再缩放。"""
        import drift_vision
        recorded = {"shapes": []}
        self._fake_pupil(monkeypatch, {(720, 1280)}, recorded)
        det = drift_vision.AprilTagDetector(downscale=2)
        dets = det.detect(np.zeros((720, 1280, 3), np.uint8))
        assert len(dets) == 1
        assert recorded["shapes"] == [(360, 640), (720, 1280)]
        assert dets[0].corners[1, 0] == pytest.approx(20.0)  # 全分辨率原始坐标

    def test_miss_at_both_scales_returns_empty(self, monkeypatch):
        """两级都未检出返回空列表（调用方按检测失败处理）。"""
        import drift_vision
        recorded = {"shapes": []}
        self._fake_pupil(monkeypatch, set(), recorded)
        det = drift_vision.AprilTagDetector(downscale=2)
        assert det.detect(np.zeros((720, 1280, 3), np.uint8)) == []
        assert recorded["shapes"] == [(360, 640), (720, 1280)]


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


class TestDetectorDownscale:
    """检测降分辨率：速度优化的坐标正确性保障。"""

    def _synth_scene(self) -> np.ndarray:
        """白底 720p 场景中央放一个 tag36h11 ID0（每模块 12px）。"""
        import sys as _sys
        scripts = Path(__file__).resolve().parents[3] / "scripts"
        if str(scripts) not in _sys.path:
            _sys.path.insert(0, str(scripts))
        from generate_apriltag import load_codes, render_tag_grid
        tag = render_tag_grid(load_codes(scripts / "data" / "tag36h11_codes.txt")[0], 12)
        scene = np.full((720, 1280), 255, dtype=np.uint8)
        h, w = tag.shape
        scene[300:300 + h, 500:500 + w] = tag
        return cv2.cvtColor(scene, cv2.COLOR_GRAY2BGR)

    def test_downscale_keeps_fullres_coordinates(self):
        pytest.importorskip("pupil_apriltags")
        from drift_vision import AprilTagDetector
        frame = self._synth_scene()
        det1 = AprilTagDetector()
        det2 = AprilTagDetector(downscale=2)
        full = [d for d in det1.detect(frame) if d.tag_id == 0]
        half = [d for d in det2.detect(frame) if d.tag_id == 0]
        assert len(full) == 1 and len(half) == 1
        # 降采样检测的角点应还原到全分辨率坐标（±3px）
        assert np.allclose(full[0].corners, half[0].corners, atol=3.0)


class TestFrameSource:
    def test_consumer_gets_latest_frame_without_queueing(self):
        """读帧线程持续推进，慢消费者每次拿最新帧（丢旧不排队）。"""
        from drift_vision import FrameSource
        cam = FakeCamera(shape=(480, 640, 3))
        src = FrameSource(cam)
        src.start()
        try:
            deadline = time.time() + 2.0  # 等泵线程产出首帧
            while src.latest() is None and time.time() < deadline:
                time.sleep(0.01)
            seen = []
            for _ in range(20):
                got = src.latest()
                if got is not None:
                    _, _, seq = got
                    if not seen or seq > seen[-1]:
                        seen.append(seq)
                time.sleep(0.01)
            assert seen and seen[-1] > seen[0], "帧序号应持续推进"
        finally:
            src.stop()
