# -*- coding: utf-8 -*-
"""drift_engine 层单元测试：相机循环的帧率计量。"""
import sys
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from drift_engine import DriftEngine, FpsMeter  # noqa: E402
from drift_session import DriftSessionState  # noqa: E402


def _homography():
    import numpy as np
    from drift_vision import FieldHomography
    img = np.float32([[30, 40], [600, 40], [600, 440], [30, 440]])
    field = np.float32([[0, 2], [2, 2], [2, 0], [0, 0]])
    return FieldHomography.from_correspondences(img, field)


def _engine_with_calib(tmp_path):
    """带假标定文件的独立引擎（可进 AUTO）。"""
    engine = DriftEngine(tub_base_dir=str(tmp_path))
    (tmp_path / "calib.npz").write_bytes(b"")
    engine._calibration_file = str(tmp_path / "calib.npz")
    return engine


class TestFpsMeter:
    def test_steady_rate(self):
        """0.05s 间隔的稳定流应量出 20fps。"""
        meter = FpsMeter(window_s=2.0)
        fps = 0.0
        for i in range(21):
            fps = meter.tick(t_s=0.05 * i)
        assert fps == pytest.approx(20.0, rel=0.05)

    def test_single_tick_returns_zero(self):
        """单帧不足以计算帧率，返回 0 而非除零。"""
        assert FpsMeter().tick(t_s=1.0) == 0.0

    def test_old_stamps_slide_out(self):
        """窗口外的旧时戳滑出：停流 2s 后再 tick，不应用陈旧帧算出虚高 fps。"""
        meter = FpsMeter(window_s=1.0)
        for i in range(10):  # 0.00~0.45s
            meter.tick(t_s=0.05 * i)
        assert meter.tick(t_s=2.5) == 0.0  # 窗内只剩单帧

    def test_snapshot_exposes_camera_fps(self):
        """状态快照应包含 camera_fps 字段（前端诊断显示）。"""
        from drift_engine import DriftEngine
        snap = DriftEngine().snapshot()
        assert "camera_fps" in snap and snap["camera_fps"] == 0.0


class TestTagHitCounters:
    """检测命中率计数：把"丢检测"变成可量化指标（M0 验收 tag_hits/frames <5% 丢失）。"""

    def test_snapshot_exposes_hit_counters(self):
        from drift_engine import DriftEngine
        snap = DriftEngine().snapshot()
        assert snap["frames_total"] == 0 and snap["tag_hits"] == 0

    def test_loop_counts_frames_and_hits(self):
        import numpy as np
        from drift_vision import (FakeCamera, FakeTagDetector, FieldHomography,
                                  TagDetection)
        from drift_engine import DriftEngine

        img = np.float32([[30, 40], [600, 40], [600, 440], [30, 440]])
        field = np.float32([[0, 2], [2, 2], [2, 0], [0, 0]])
        homography = FieldHomography.from_correspondences(img, field)
        corners = np.array([[300, 200], [340, 200], [340, 240], [300, 240]],
                           dtype=np.float32)
        det = FakeTagDetector([TagDetection(tag_id=0, corners=corners)])
        engine = DriftEngine(tub_base_dir=None)
        engine.start_camera_loop(FakeCamera(), det, homography, tag_id=0)
        try:
            deadline = time.time() + 3.0
            while time.time() < deadline and engine.snapshot()["frames_total"] < 5:
                time.sleep(0.02)
            snap = engine.snapshot()
            assert snap["frames_total"] >= 5
            assert snap["tag_hits"] == snap["frames_total"], \
                "每帧都命中时 tag_hits 应等于 frames_total"
        finally:
            engine.stop_camera_loop()


class TestDisplayFrameFreshness:
    def test_display_frame_advances_without_detection(self):
        """检测失败帧不得冻结预览：显示帧必须跟随最新采集帧推进。

        运动模糊导致间歇性检测丢失时，若只在检测成功时更新显示帧，
        推流会持续发旧画面（实车现象：慢推流畅、快推卡顿）。"""
        import numpy as np
        from drift_vision import FakeTagDetector, FieldHomography
        from drift_engine import DriftEngine

        class SeqCamera:
            """每帧像素值递增的合成相机（可区分新旧帧）。"""
            def __init__(self):
                self._n = 0

            def read(self):
                self._n += 1
                return (np.full((480, 640, 3), self._n % 251, np.uint8),
                        time.monotonic())

            def close(self):
                pass

        img = np.float32([[30, 40], [600, 40], [600, 440], [30, 440]])
        field = np.float32([[0, 2], [2, 2], [2, 0], [0, 0]])
        homography = FieldHomography.from_correspondences(img, field)
        engine = DriftEngine(tub_base_dir=None)
        engine.start_camera_loop(SeqCamera(), FakeTagDetector(),
                                 homography, tag_id=0)
        try:
            samples = []
            for _ in range(3):
                time.sleep(0.2)
                f = engine.display_frame
                samples.append(None if f is None else int(f[0, 0, 0]))
            assert all(s is not None for s in samples), \
                "无检测时预览不得为空"
            assert len(set(samples)) > 1, \
                "检测失败时预览帧也必须推进，不得冻结旧帧"
        finally:
            engine.stop_camera_loop()


class TestCameraLoopSmoke:
    def test_loop_runs_and_reports_stage_timing(self):
        """泵+处理循环真线程冒烟：fps 与分段耗时被统计，停止干净。"""
        import numpy as np
        from drift_vision import FakeCamera, FakeTagDetector, FieldHomography
        from drift_engine import DriftEngine

        img = np.float32([[0, 1], [1, 2], [2, 0], [0, 0]])  # 任意非退化四点
        img = np.float32([[30, 40], [600, 40], [600, 440], [30, 440]])
        field = np.float32([[0, 2], [2, 2], [2, 0], [0, 0]])
        homography = FieldHomography.from_correspondences(img, field)
        engine = DriftEngine(tub_base_dir=None)
        engine.start_camera_loop(FakeCamera(shape=(480, 640, 3)),
                                  FakeTagDetector(), homography, tag_id=0)
        try:
            # 宽限 10s：FakeCamera 泵自由空转吃满单核，重负载机器（如视频会议
            # 中）消费者线程调度延迟可超 3s；宽限只影响等待上限，不改变验证内容。
            deadline = time.time() + 10.0
            while time.time() < deadline and engine.camera_fps <= 0:
                time.sleep(0.05)
            assert engine.camera_fps > 0, "处理循环应推进"
            # FakeCamera 有 1/60s 节拍，耗时 EMA 必大于 0（>=0 是恒真空断言）
            assert engine.read_ema_ms > 0.0 and engine.detect_ema_ms > 0.0
        finally:
            engine.stop_camera_loop()


class TestCameraLoopTrajectory:
    def test_trail_drawn_and_persists_through_detection_loss(self):
        """轨迹叠加接线：运动中画面含彩色像素（轨迹+加粗箭头+深蓝 β 箭头）；
        检测丢失后 2s 滑窗内轨迹仍叠加在最新帧上（不再纯透传）。"""
        import numpy as np
        from drift_vision import FieldHomography, TagDetection
        from drift_engine import DriftEngine

        class _PacedCamera:
            """5ms 节拍的灰帧相机（真实单调时戳，轨迹窗口按真实时间修剪）。"""
            def read(self):
                time.sleep(0.005)
                return np.full((480, 640, 3), 200, np.uint8), time.monotonic()

            def close(self):
                pass

        class _MovingThenLostDetector:
            """前 30 次调用：标签车头向北、每帧向东移 8px；之后检测丢失。"""
            def __init__(self):
                self._n = 0

            def detect(self, frame):
                self._n += 1
                if self._n > 30:
                    return []
                k = self._n * 8
                corners = np.float32([[340 + k, 200], [340 + k, 160],
                                      [300 + k, 160], [300 + k, 200]])
                return [TagDetection(tag_id=0, corners=corners)]

        img = np.float32([[30, 40], [600, 40], [600, 440], [30, 440]])
        field = np.float32([[0, 2], [2, 2], [2, 0], [0, 0]])
        homography = FieldHomography.from_correspondences(img, field)
        engine = DriftEngine(tub_base_dir=None)
        engine.start_camera_loop(_PacedCamera(), _MovingThenLostDetector(),
                                 homography, tag_id=0)

        def _colored(f):
            return bool(((f[:, :, 0] != f[:, :, 1])
                         | (f[:, :, 1] != f[:, :, 2])).any())

        def _blue(f):
            b = f.reshape(-1, 3).astype(np.int32)
            return bool(((b[:, 0] > 100) & (b[:, 1] < 100) & (b[:, 2] < 100)).any())

        try:
            # 运动阶段：轨迹 + 车头红箭 + 深蓝色航迹箭都已上屏
            deadline = time.time() + 5.0
            while time.time() < deadline \
                    and engine.snapshot()["tag_hits"] < 12:
                time.sleep(0.02)
            snap = engine.snapshot()
            assert snap["tag_hits"] >= 12, "运动阶段应积累足够命中"
            f = engine.display_frame
            assert f is not None and _colored(f), "运动阶段应绘制轨迹与箭头"
            assert _blue(f), "运动中应绘制深蓝色航迹箭头（β 朝向=轨迹切线）"
            # 丢失阶段：检测丢失后，2s 滑窗内轨迹仍叠加在最新帧上
            deadline = time.time() + 5.0
            lost_overlay = False
            while time.time() < deadline:
                snap = engine.snapshot()
                f = engine.display_frame
                if snap["frames_total"] - snap["tag_hits"] > 5 \
                        and f is not None and _colored(f):
                    lost_overlay = True
                    break
                time.sleep(0.02)
            assert lost_overlay, "检测丢失后滑窗内轨迹应继续叠加（不得纯透传）"
        finally:
            engine.stop_camera_loop()


class TestObservationDetectionGap:
    """E5：观察期丢检测帧不计入 β 稳定计时（引擎侧接线）。"""

    def test_gap_frames_reset_engage_timer(self, tmp_path):
        """β 超阈 0.4s 后丢检测 0.2s，恢复后接管计时必须重新起算。"""
        engine = _engine_with_calib(tmp_path)
        engine.start("auto")
        engine.process_fake_frame(20.0, t_s=0.0)
        engine.process_fake_frame(20.0, t_s=0.4)                # 已稳定 0.4s
        engine.process_camera_frame(None, 0.5, None, None, 0.0)  # 丢检测
        engine.process_camera_frame(None, 0.6, None, None, 0.0)
        engine.process_fake_frame(20.0, t_s=0.7)                # 恢复：重新锚定 0.7
        engine.process_fake_frame(20.0, t_s=1.1)                # 仅持续 0.4s
        assert engine.session.state == DriftSessionState.AUTO_OBSERVE, \
            "检测缺口不得计入 β 稳定计时"
        engine.process_fake_frame(20.0, t_s=1.25)               # 满 0.55s
        assert engine.session.state == DriftSessionState.AUTO_ENGAGED


class TestStartAutoAnchorsEstimator:
    """E6：start("auto") 必须锚定 β 估计器。"""

    def test_start_auto_clears_beta_estimator(self, tmp_path):
        """上一会话残留的 heading/course 会伪造新观察期的接管窗口。"""
        engine = _engine_with_calib(tmp_path)
        engine.beta_estimator._set_internal(heading_deg=45.0, course_deg=30.0)
        engine.start("auto")
        assert engine.beta_estimator._heading_deg is None
        assert engine.beta_estimator._course_deg is None


class TestSentMessagesBounded:
    """E7：发送观测口有界（生产长跑不得无限增长）。"""

    def test_sent_messages_is_bounded_deque(self):
        engine = DriftEngine()
        for i in range(1100):
            engine._send({"n": i})
        assert len(engine.sent_messages) == 1000
        assert engine.sent_messages[-1]["n"] == 1099


class TestSnapshotExposure:
    """E7：snapshot 新增字段（前端契约）。"""

    def test_snapshot_exposes_camera_running_and_send_failures(self):
        snap = DriftEngine().snapshot()
        assert snap["camera_running"] is False
        assert snap["send_failures"] == 0

    def test_camera_running_tracks_loop_lifecycle(self, tmp_path):
        from drift_vision import FakeCamera, FakeTagDetector

        engine = DriftEngine(tub_base_dir=str(tmp_path))
        engine.start_camera_loop(FakeCamera(), FakeTagDetector(),
                                 _homography(), tag_id=0)
        try:
            assert engine.snapshot()["camera_running"] is True
        finally:
            engine.stop_camera_loop()
        assert engine.snapshot()["camera_running"] is False


class TestSendFailureCounting:
    """E7/E2：sink 抛异常或返回 False 计入失败；返回 None 不算失败。"""

    def test_sink_false_and_exception_count(self):
        engine = DriftEngine()
        engine.send_sink = lambda msg: False
        engine._send({"a": 1})
        assert engine.send_failures == 1

        def _boom(msg):
            raise RuntimeError("链路爆炸（合成）")

        engine.send_sink = _boom
        engine._send({"a": 2})
        assert engine.send_failures == 2
        engine.send_sink = lambda msg: None  # fire-and-forget 封装
        engine._send({"a": 3})
        assert engine.send_failures == 2
        assert engine._consecutive_send_failures == 0, "成功下发应清零连续失败"


class TestPreviewDisabled:
    """E7：preview_hz<=0 语义修正——完全跳过预览编码，而非每帧编码。"""

    def test_preview_hz_zero_skips_jpeg_encoding(self, tmp_path):
        from drift_vision import FakeCamera, FakeTagDetector

        engine = DriftEngine(tub_base_dir=str(tmp_path))
        engine.start_camera_loop(FakeCamera(), FakeTagDetector(),
                                 _homography(), tag_id=0, preview_hz=0)
        try:
            time.sleep(0.3)
            assert engine.snapshot()["frames_total"] > 3, "循环确实在跑"
            assert engine.last_preview_jpeg is None, \
                "preview_hz<=0 不得产出预览 JPEG"
        finally:
            engine.stop_camera_loop()


class TestDetectEmaColdStart:
    """E7：detect EMA 冷启动首样本直接赋值（避免从 0 收敛的系统性偏低）。"""

    def test_first_sample_assigned_not_converged_from_zero(self, tmp_path):
        from drift_vision import FakeCamera

        class _SlowFirstDetector:
            """首帧 detect 耗时 200ms，其后瞬时返回。"""

            def __init__(self):
                self._n = 0

            def detect(self, frame):
                self._n += 1
                if self._n == 1:
                    time.sleep(0.2)
                return []

        engine = DriftEngine(tub_base_dir=str(tmp_path))
        engine.start_camera_loop(FakeCamera(), _SlowFirstDetector(),
                                 _homography(), tag_id=0)
        try:
            deadline = time.time() + 5.0
            while time.time() < deadline and engine.frames_total < 1:
                time.sleep(0.01)
            assert engine.frames_total >= 1
            assert engine.detect_ema_ms >= 100.0, \
                "首帧 detect 耗时 200ms，EMA 首样本应直接赋值（旧实现只记 20ms）"
        finally:
            engine.stop_camera_loop()


class TestEngagedWithoutPose:
    """E7：ENGAGED 帧缺位姿时显式跳过外环控制（不得拿 (0,0) 垃圾坐标喂控制器）。"""

    def test_no_control_sent_when_pose_missing(self, tmp_path):
        engine = _engine_with_calib(tmp_path)
        captured = []
        engine.send_sink = captured.append
        engine.start("auto")
        engine.process_fake_frame(20.0, t_s=0.0)
        engine.process_fake_frame(20.0, t_s=0.6)   # ENGAGED
        assert engine.session.state == DriftSessionState.AUTO_ENGAGED
        captured.clear()
        engine.process_fake_frame(20.0, t_s=0.65)  # ENGAGED 但 pose=None
        offending = [m for m in captured if "angle" in m or "throttle" in m]
        assert offending == [], "ENGAGED 缺位姿帧不得下发转向/油门"


class TestUpdateConfigValidation:
    """E8 引擎层：update_config 有限性/符号门禁（路由层另映射 422）。"""

    def test_nan_rejected(self):
        with pytest.raises(ValueError):
            DriftEngine().update_config({"k_beta": float("nan")})

    def test_inf_rejected(self):
        with pytest.raises(ValueError):
            DriftEngine().update_config({"k_beta": float("inf")})

    def test_negative_pulse_duty_rejected(self):
        """占空比负值无物理意义 → 拒绝。"""
        with pytest.raises(ValueError):
            DriftEngine().update_config({"pulse_duty": -0.5})

    def test_non_numeric_rejected(self):
        with pytest.raises((TypeError, ValueError)):
            DriftEngine().update_config({"k_beta": {"x": 1}})

    def test_valid_update_still_applies(self):
        engine = DriftEngine()
        engine.update_config({"k_beta": 2.5, "pulse_duty": 0.0})
        assert engine.config.k_beta == 2.5
        assert engine.config.pulse_duty == 0.0


class TestRecordStartFailure:
    """E8：SyncRecorder 构造失败不得在 RECORD 态残留。"""

    def test_recorder_construction_failure_leaves_idle(self, tmp_path, monkeypatch):
        import sync_recorder

        engine = _engine_with_calib(tmp_path)

        def _boom(path):
            raise RuntimeError("磁盘不可写（合成）")

        monkeypatch.setattr(sync_recorder, "SyncRecorder", _boom)
        with pytest.raises(RuntimeError):
            engine.start("record")
        assert engine.session.state == DriftSessionState.IDLE
        assert engine.recorder is None


class TestDefaultTubPath:
    """E8：秒级时戳同秒连开两次录制不得撞名。"""

    def test_same_second_paths_differ(self, tmp_path):
        engine = DriftEngine(tub_base_dir=str(tmp_path / "tubs"))
        p1 = engine._default_tub_path()
        p2 = engine._default_tub_path()
        assert p1 != p2, "同秒（甚至同毫秒）生成的 tub 路径必须可区分"
