# -*- coding: utf-8 -*-
"""第三视角漂移编排引擎（RFC 第 4 节分阶段控制流）。

组合 DriftSession / BetaEstimator / DriftController / SyncRecorder，
衔接现有 drive 通路：
- 控制下发：send_sink（由 routers 注入 → drive_state.send_to_car，进程内，
  与浏览器客户端同构）；
- 遥测上行：on_telemetry 由 drive_state.telemetry_hooks 调用（广播点分叉）；
- 相机循环：生产环境由 asyncio task 驱动 USBCamera→检测→process_camera_frame；
  测试直接调 process_fake_frame / process_camera_frame。

安全（RFC 阶段 3）：观察期不下发任何转向/油门（人 RC 在开）；接管时
car_mode=2；看门狗触发时 car_mode=0 + 零油门交还人工。
"""
import math
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from drift_controller import ControllerConfig, ControlOutput, DriftController
from drift_session import DriftSession, DriftSessionState
from state_estimator import BetaEstimator, PoseSample

RAD2DEG = 180.0 / math.pi

# 遥测消息字段 → 引擎内部字段的映射（gz 为 rad/s，转为 deg/s）
_TELEM_FIELD_MAP = {
    "rc_steering": "rc/steering",
    "rc_throttle": "rc/throttle",
    "gz": "imu/gyr_z",
}


class DriftEngine:
    def __init__(self, tub_base_dir: Optional[str] = None):
        self._tub_base_dir = tub_base_dir
        self._calibration_file: Optional[str] = None
        self.session = DriftSession(calibration_ready=self._calibration_ok)
        self.beta_estimator = BetaEstimator()
        self.config = ControllerConfig()
        self.controller = DriftController(self.config)
        self.recorder = None
        self.send_sink: Optional[Callable[[dict], None]] = None
        self.sent_messages: List[dict] = []
        self.telemetry_count = 0
        self.last_beta_deg: Optional[float] = None
        self.last_pose: Optional[Dict[str, float]] = None
        self.last_preview_jpeg: Optional[bytes] = None
        self._last_telemetry_t: Optional[float] = None
        self._last_yaw_rate_dps: float = 0.0
        self._camera = None
        self._camera_thread: Optional[threading.Thread] = None
        self._running = False

    # ── 生命周期 ────────────────────────────────────────────
    def reset(self, calibration_file: Optional[str] = None,
              tub_base_dir: Optional[str] = None) -> None:
        if calibration_file is not None:
            self._calibration_file = calibration_file
        if tub_base_dir is not None:
            self._tub_base_dir = tub_base_dir
        self.session = DriftSession(calibration_ready=self._calibration_ok)
        self.beta_estimator = BetaEstimator()
        self.config = ControllerConfig()
        self.controller = DriftController(self.config)
        self._close_recorder()
        self.recorder = None
        self.send_sink = None
        self.sent_messages = []
        self.telemetry_count = 0
        self.last_beta_deg = None
        self.last_pose = None
        self._last_telemetry_t = None
        self._last_yaw_rate_dps = 0.0
        self._running = False

    def _calibration_ok(self) -> bool:
        return (self._calibration_file is not None
                and Path(self._calibration_file).exists())

    def _close_recorder(self) -> None:
        if self.recorder is not None:
            try:
                self.recorder.close()
            except Exception:
                pass

    # ── 模式切换（API 调用）──────────────────────────────────
    def start(self, mode: str, tub_path: Optional[str] = None) -> None:
        if mode == "calibrate":
            self.session.start_calibration()
        elif mode == "record":
            self.session.start_recording()
            from sync_recorder import SyncRecorder
            path = tub_path or self._default_tub_path()
            self.recorder = SyncRecorder(path=path)
        elif mode == "auto":
            self.session.start_auto()
            self.controller.reset()
        else:
            raise ValueError(f"未知模式: {mode}")

    def stop(self) -> None:
        state = self.session.state
        if state == DriftSessionState.CALIBRATE:
            self.session.finish_calibration(ok=True)
        elif state == DriftSessionState.RECORD:
            self.session.stop_recording()
            self._close_recorder()
            self.recorder = None
        elif state in (DriftSessionState.AUTO_OBSERVE, DriftSessionState.AUTO_ENGAGED):
            self.session.stop_auto()
            self._send({"car_mode": 0, "throttle": 0.0})

    def _default_tub_path(self) -> str:
        base = Path(self._tub_base_dir or "data/drift_tubs")
        base.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%y-%m-%d_%H-%M-%S")
        return str(base / f"overhead_{stamp}")

    # ── 发送与安全 ──────────────────────────────────────────
    def _send(self, msg: dict) -> None:
        self.sent_messages.append(msg)
        if self.send_sink is not None:
            try:
                self.send_sink(msg)
            except Exception:
                pass

    def trigger_watchdog(self, reason: str) -> None:
        self.session.watchdog_trigger(reason)
        self._send({"car_mode": 0, "throttle": 0.0})

    # ── 遥测上行（drive_state.telemetry_hooks 注入）──────────
    def on_telemetry(self, t_s: float, fields: Dict[str, float]) -> None:
        self.telemetry_count += 1
        self._last_telemetry_t = t_s
        if self.recorder is not None:
            self.recorder.on_telemetry(t_s, fields)

    def ingest_telemetry_msg(self, msg: dict) -> None:
        """把 drive 通路遥测消息（gz=rad/s）转换为引擎字段并喂入。"""
        fields = {}
        for src, dst in _TELEM_FIELD_MAP.items():
            if src in msg and msg[src] is not None:
                v = float(msg[src])
                fields[dst] = v * RAD2DEG if src == "gz" else v
        if fields:
            if "imu/gyr_z" in fields:
                self._last_yaw_rate_dps = fields["imu/gyr_z"]
            self.on_telemetry(time.monotonic(), fields)

    # ── 相机循环（生产链路）──────────────────────────────────
    def start_camera_loop(self, camera, detector, homography, tag_id: int,
                          preview_every_n: int = 6) -> None:
        """后台线程：相机→标签检测→位姿→β→process_camera_frame。"""
        from drift_vision import PoseSolver, solve_tag_pose

        self._running = True
        solver = PoseSolver(homography)

        def _loop() -> None:
            import cv2
            frame_count = 0
            while self._running:
                try:
                    frame, t_s = camera.read()
                except Exception:
                    self.trigger_watchdog("相机读帧失败")
                    break
                detection = next((d for d in detector.detect(frame)
                                  if d.tag_id == tag_id), None)
                if detection is None:
                    est = self.beta_estimator.update(None, self._last_yaw_rate_dps, t_s=t_s)
                    self.process_camera_frame(frame, t_s, None, None,
                                              self._last_yaw_rate_dps)
                else:
                    pose = solver.push(solve_tag_pose(homography, detection.corners, t_s))
                    est = self.beta_estimator.update(
                        PoseSample(x=pose.x, y=pose.y,
                                   heading_deg=pose.heading_deg, t_s=t_s),
                        self._last_yaw_rate_dps)
                    self.process_camera_frame(
                        frame, t_s, {"x": pose.x, "y": pose.y,
                                     "heading_deg": pose.heading_deg},
                        est.beta_deg, self._last_yaw_rate_dps)
                frame_count += 1
                if frame_count % preview_every_n == 0:
                    try:
                        ok, buf = cv2.imencode(".jpg", frame,
                                               [cv2.IMWRITE_JPEG_QUALITY, 70])
                        if ok:
                            self.last_preview_jpeg = buf.tobytes()
                    except Exception:
                        pass

        self._camera_thread = threading.Thread(target=_loop, daemon=True,
                                               name="drift-camera")
        self._camera_thread.start()

    def stop_camera_loop(self) -> None:
        self._running = False
        if self._camera_thread is not None:
            self._camera_thread.join(timeout=2.0)
            self._camera_thread = None
        if self._camera is not None:
            try:
                self._camera.close()
            except Exception:
                pass
            self._camera = None

    # ── 帧处理（相机循环 / 测试直调）─────────────────────────
    def process_camera_frame(self, frame: np.ndarray, t_s: float,
                             pose: Optional[Dict[str, float]],
                             beta_deg: Optional[float],
                             yaw_rate_dps: float) -> None:
        """一帧完整处理：录 tub（RECORD）/ 状态机+控制（AUTO）。"""
        self.last_beta_deg = beta_deg
        if pose is not None:
            self.last_pose = pose
            if self.recorder is not None and beta_deg is not None:
                self.recorder.on_camera_frame(t_s=t_s, image=frame, pose=pose,
                                              beta_deg=beta_deg,
                                              yaw_rate_dps=yaw_rate_dps)
        if beta_deg is None:
            return
        state = self.session.state
        if state == DriftSessionState.AUTO_OBSERVE:
            engaged = self.session.update_auto_observation(beta_deg, t_s)
            if engaged:
                self._send({"car_mode": 2})
        elif state == DriftSessionState.AUTO_ENGAGED:
            px, py = (pose["x"], pose["y"]) if pose else (0.0, 0.0)
            out = self.controller.update(beta_deg=beta_deg, yaw_rate_dps=yaw_rate_dps,
                                         pose=(px, py), t_s=t_s)
            self._send({"angle": out.steering, "throttle": out.throttle})

    def process_fake_frame(self, beta_deg: float, t_s: float) -> None:
        """测试钩子：绕过视觉直接喂 β（AUTO 语义链路与真实帧一致）。"""
        self.process_camera_frame(frame=None, t_s=t_s, pose=None,
                                  beta_deg=beta_deg, yaw_rate_dps=0.0)

    # ── 状态快照（API）──────────────────────────────────────
    def snapshot(self) -> dict:
        return {
            "state": self.session.state.value,
            "calibration_ready": self._calibration_ok(),
            "beta_deg": self.last_beta_deg,
            "pose": self.last_pose,
            "telemetry_count": self.telemetry_count,
            "frames_written": self.recorder.frames_written if self.recorder else 0,
            "events": [{"kind": e.kind, "detail": e.detail, "t_s": e.t_s}
                       for e in list(self.session.events)[-20:]],
            "config": _config_as_dict(self.config),
        }

    def update_config(self, updates: dict) -> None:
        allowed = _CONFIG_KEYS.intersection(updates)
        unknown = set(updates) - allowed
        if unknown:
            raise KeyError(f"未知配置项: {sorted(unknown)}")
        for key, value in updates.items():
            setattr(self.config, key, float(value))


_CONFIG_KEYS = {
    "beta_target_deg", "k_beta", "max_yaw_rate_dps", "k_radius_to_freq",
    "k_yaw", "k_yaw_i", "integral_limit", "pulse_freq_hz", "pulse_duty",
    "pulse_amplitude", "pulse_base", "max_steering_delta_per_tick",
}


def _config_as_dict(cfg: ControllerConfig) -> dict:
    return {key: getattr(cfg, key) for key in sorted(_CONFIG_KEYS)}


drift_engine = DriftEngine()
