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
import logging
import math
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Deque, Dict, Optional

import numpy as np

from drift_controller import ControllerConfig, ControlOutput, DriftController
from drift_session import DriftSession, DriftSessionState
from state_estimator import BetaEstimator, PoseSample

logger = logging.getLogger(__name__)

RAD2DEG = 180.0 / math.pi

# ENGAGED 期逐帧看门狗阈值（相机帧时基，秒）：
# 相机 fps 20~60 可变，一律按时间判定，不按帧数。
_DETECTION_LOSS_TIMEOUT_S = 0.2   # 检测丢失（RFC 安全模型：丢帧 >200ms 交还人工）
_TELEMETRY_STALE_TIMEOUT_S = 0.5  # 遥测停滞（β 在吃陈旧 yaw_rate 积分，危险）
_SEND_FAILURE_LIMIT = 3           # 控制下发连续失败次数上限

# 遥测消息字段 → 引擎内部字段的映射（gz 为 rad/s，转为 deg/s）
_TELEM_FIELD_MAP = {
    "rc_steering": "rc/steering",
    "rc_throttle": "rc/throttle",
    "gz": "imu/gyr_z",
}


class FpsMeter:
    """滑动窗帧率计量：真实处理循环频率的观测器（诊断相机/检测瓶颈）。"""

    def __init__(self, window_s: float = 2.0):
        self._window_s = window_s
        self._stamps: Deque[float] = deque()

    def tick(self, t_s: float) -> float:
        self._stamps.append(t_s)
        while self._stamps and t_s - self._stamps[0] > self._window_s:
            self._stamps.popleft()
        if len(self._stamps) >= 2:
            span = self._stamps[-1] - self._stamps[0]
            if span > 0:
                return (len(self._stamps) - 1) / span
        return 0.0


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
        # 发送观测口：有界 deque，生产长跑不得无限增长（E7）
        self.sent_messages: Deque[dict] = deque(maxlen=1000)
        self.send_failures: int = 0          # 下发失败累计（snapshot 暴露）
        self._consecutive_send_failures = 0  # 连续失败（ENGAGED 期看门狗判定）
        self.camera_loop_errors: int = 0     # 相机循环异常计数（E1）
        self.telemetry_count = 0
        self.last_beta_deg: Optional[float] = None
        self.last_pose: Optional[Dict[str, float]] = None
        self.last_preview_jpeg: Optional[bytes] = None
        self.camera_fps: float = 0.0
        self.read_ema_ms: float = 0.0
        self.detect_ema_ms: float = 0.0
        self.frames_total: int = 0   # 处理帧总数（命中率分母）
        self.tag_hits: int = 0       # 检测命中帧数（M0 验收：丢失率 <5%）
        self._frame_source = None
        self._display_frame: Optional[np.ndarray] = None  # 最新叠加帧（WebRTC/MJPEG 共用）
        self._last_telemetry_t: Optional[float] = None
        self._last_yaw_rate_dps: float = 0.0
        self._camera = None
        self._camera_thread: Optional[threading.Thread] = None
        self._running = False
        self._last_tub_path: Optional[str] = None  # 上一次生成的 tub 路径（同秒防撞名）
        self._tub_path_seq: int = 0

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
        self.sent_messages = deque(maxlen=1000)
        self.send_failures = 0
        self._consecutive_send_failures = 0
        self.camera_loop_errors = 0
        self.telemetry_count = 0
        self.last_beta_deg = None
        self.last_pose = None
        self.camera_fps = 0.0
        self.read_ema_ms = 0.0
        self.detect_ema_ms = 0.0
        self.frames_total = 0
        self.tag_hits = 0
        self._frame_source = None
        self._display_frame = None
        self._last_telemetry_t = None
        self._last_yaw_rate_dps = 0.0
        self._running = False
        self._last_tub_path = None
        self._tub_path_seq = 0

    @property
    def display_frame(self) -> Optional[np.ndarray]:
        """最新叠加显示帧（WebRTC 轨道取帧用）。"""
        return self._display_frame

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
            from sync_recorder import SyncRecorder
            path = tub_path or self._default_tub_path()
            # 先构造 SyncRecorder 再迁移状态：构造失败不得在 RECORD 态残留；
            # 反过来状态迁移失败（如标定缺失）也不得留下未关闭的 recorder
            recorder = SyncRecorder(path=path)
            try:
                self.session.start_recording()
            except Exception:
                recorder.close()
                raise
            self.recorder = recorder
        elif mode == "auto":
            self.session.start_auto()
            self.controller.reset()
            # 锚定 β 估计器：上一会话残留的 heading/滑窗会伪造新观察期的
            # 接管窗口（假接管），新会话必须从 β≈0 重新锁定
            self.beta_estimator.anchor()
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
        now = time.time()
        # 毫秒后缀：秒级时戳下同秒连开两次录制会撞名；
        # 同毫秒的极端情况（低分辨率时钟）再用递增尾号兜底
        stamp = time.strftime("%y-%m-%d_%H-%M-%S", time.localtime(now)) \
            + f"_{int(now * 1000) % 1000:03d}"
        candidate = str(base / f"overhead_{stamp}")
        if candidate == self._last_tub_path:
            self._tub_path_seq += 1
            candidate = f"{candidate}_{self._tub_path_seq}"
        self._last_tub_path = candidate
        return candidate

    # ── 发送与安全 ──────────────────────────────────────────
    def _send(self, msg: dict) -> None:
        """控制下发：记录观测口（有界），sink 失败计数。

        sink 抛异常或显式返回 False 视为一次失败（连续失败计数供
        ENGAGED 期看门狗判定）；返回 None（fire-and-forget 封装）不算失败。
        """
        self.sent_messages.append(msg)
        if self.send_sink is None:
            return
        try:
            ok = self.send_sink(msg)
        except Exception:
            ok = False
        if ok is False:
            self.send_failures += 1
            self._consecutive_send_failures += 1
        else:
            self._consecutive_send_failures = 0

    def trigger_watchdog(self, reason: str) -> None:
        """看门狗触发：仅 AUTO 期间（auto_active）才下发 car_mode 0 + 零油门
        交还人工；非 AUTO（如仅开预览）只记事件——引擎此时无权碰车。"""
        was_auto = self.auto_active()
        self.session.watchdog_trigger(reason)
        if was_auto:
            self._send({"car_mode": 0, "throttle": 0.0})

    def auto_active(self) -> bool:
        """AUTO 期间（观察/接管）为 True：浏览器控制须被服务端门禁拦截。"""
        return self.session.state in (DriftSessionState.AUTO_OBSERVE,
                                      DriftSessionState.AUTO_ENGAGED)

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
                          heading_offset_deg: float = 0.0,
                          preview_hz: float = 15.0) -> None:
        """后台线程：泵读帧→标签检测→位姿→β→process_camera_frame。

        读帧与处理分线程（FrameSource）：采集速率不受检测耗时拖累，
        处理循环只消费最新帧（丢旧不排队）；泵线程死亡触发看门狗。

        重入安全：已有运行中循环/句柄时先幂等停止（防双循环、旧相机
        句柄泄漏）。相机由引擎显式持有，stop_camera_loop 时释放。
        preview_hz<=0：完全跳过预览 JPEG 编码。
        """
        from drift_vision import (FrameSource, PoseSolver, TrajectoryTrail,
                                  solve_tag_pose, trail_course_deg,
                                  trail_speeds)

        if self._running or self._camera_thread is not None \
                or self._frame_source is not None:
            self.stop_camera_loop()  # 重入守卫：先释放旧循环与旧相机句柄
        self._camera = camera
        self._running = True
        source = FrameSource(camera)
        source.start()
        self._frame_source = source
        solver = PoseSolver(homography)
        trail = TrajectoryTrail(window_s=2.0)
        fps_meter = FpsMeter()
        preview_min_interval = 1.0 / preview_hz if preview_hz > 0 else None

        def _loop() -> None:
            import cv2
            from drift_vision import draw_tag_overlay, draw_trajectory
            last_preview_t = 0.0
            last_pose = None
            last_seq = -1
            gap_since_t: Optional[float] = None  # 连续未检出 streak 起点（帧时基）
            try:
                while self._running:
                    got = source.latest()
                    if got is None or got[2] == last_seq:
                        if not source.alive:
                            self.trigger_watchdog("相机读帧失败")
                            break
                        time.sleep(0.001)  # 等新帧
                        continue
                    frame, t_s, seq = got
                    last_seq = seq
                    self.camera_fps = fps_meter.tick(t_s)
                    t0 = time.perf_counter()
                    detection = next((d for d in detector.detect(frame)
                                      if d.tag_id == tag_id), None)
                    detect_ms = (time.perf_counter() - t0) * 1000.0
                    if self.frames_total == 0:
                        # EMA 冷启动：首样本直接赋值，避免从 0 收敛的系统性偏低
                        self.detect_ema_ms = detect_ms
                    else:
                        self.detect_ema_ms += 0.1 * (detect_ms - self.detect_ema_ms)
                    self.read_ema_ms = source.read_ema_ms
                    self.frames_total += 1
                    if detection is not None:
                        self.tag_hits += 1
                        gap_since_t = None
                    elif gap_since_t is None:
                        gap_since_t = t_s
                    if detection is None:
                        # 丢帧时不外推控制输出是有意设计：β/位姿缺帧时
                        # process_camera_frame 早退、ENGAGED 控制帧跳过——
                        # 拿陈旧状态外推会继续打方向，安全语义由看门狗
                        # （检测丢失超时）兜底。请勿"修复"为外推。
                        est = self.beta_estimator.update(None, self._last_yaw_rate_dps, t_s=t_s)
                        self.process_camera_frame(frame, t_s, None, None,
                                                  self._last_yaw_rate_dps)
                    else:
                        # 位姿解算退化（过地平线/坏单应 → _map 抛 ValueError）或
                        # PoseSolver 拒收（首帧即 NaN、历史为空返回 None）一律按
                        # 丢帧处理：不外推控制（语义见上方丢帧分支注释），循环不死。
                        try:
                            raw_pose = solve_tag_pose(
                                homography, detection.corners, t_s,
                                heading_offset_deg=heading_offset_deg)
                        except ValueError:
                            raw_pose = None
                        pose = solver.push(raw_pose) if raw_pose is not None else None
                        if pose is None:
                            est = self.beta_estimator.update(
                                None, self._last_yaw_rate_dps, t_s=t_s)
                            self.process_camera_frame(frame, t_s, None, None,
                                                      self._last_yaw_rate_dps)
                        else:
                            last_pose = pose
                            trail.add(t_s, pose.x, pose.y)
                            est = self.beta_estimator.update(
                                PoseSample(x=pose.x, y=pose.y,
                                           heading_deg=pose.heading_deg, t_s=t_s),
                                self._last_yaw_rate_dps)
                            self.process_camera_frame(
                                frame, t_s, {"x": pose.x, "y": pose.y,
                                             "heading_deg": pose.heading_deg},
                                est.beta_deg, self._last_yaw_rate_dps)
                    # ENGAGED 期逐帧安全巡检（检测丢失/遥测停滞/下发失败）
                    self._check_engaged_watchdogs(t_s, gap_since_t)
                    try:  # 显示帧逐帧更新：轨迹（2s 滑窗、按速度着色）始终叠加；
                        # 检测成功再叠绿框+车头红箭+深蓝航迹箭（方向取轨迹割线，
                        # 静止/噪声级位移时为 None 不画）；无轨迹且未检出时透传
                        # 原始帧——检测缺口期间推流不得发旧帧（预览卡顿）。
                        points = trail.snapshot(t_s)
                        speeds = trail_speeds(points)
                        vis = None
                        if points:
                            vis = frame.copy()
                            draw_trajectory(vis, homography, points, speeds)
                        if detection is not None and last_pose is not None:
                            if vis is None:
                                vis = frame.copy()
                            draw_tag_overlay(vis, homography, detection.corners,
                                             last_pose,
                                             course_deg=trail_course_deg(points))
                        self._display_frame = vis if vis is not None else frame
                    except Exception:
                        self._display_frame = frame
                    if preview_min_interval is not None \
                            and t_s - last_preview_t >= preview_min_interval:
                        try:
                            preview_frame = (self._display_frame if self._display_frame is not None
                                             else frame)
                            ok, buf = cv2.imencode(".jpg", preview_frame,
                                                   [cv2.IMWRITE_JPEG_QUALITY, 70])
                            if ok:
                                self.last_preview_jpeg = buf.tobytes()
                                last_preview_t = t_s
                        except Exception:
                            pass
            except Exception as exc:
                # 核心链路（检测/位姿/β/录盘）异常：不得静默杀循环——
                # 记日志+计数，看门狗交还人工后退出
                self.camera_loop_errors += 1
                logger.exception("漂移相机循环异常终止")
                self.trigger_watchdog(f"相机循环异常: {exc}")
            finally:
                source.stop()

        self._camera_thread = threading.Thread(target=_loop, daemon=True,
                                               name="drift-camera")
        self._camera_thread.start()

    def _check_engaged_watchdogs(self, t_s: float,
                                 detection_gap_since: Optional[float]) -> None:
        """ENGAGED 期逐帧安全巡检（相机循环每帧调用，帧时基）。

        任一条件触发看门狗交还人工：检测丢失超时 / 遥测停滞 /
        控制下发连续失败。非 ENGAGED 直接返回（观察期车在人手里）。
        """
        if self.session.state != DriftSessionState.AUTO_ENGAGED:
            return
        if detection_gap_since is not None \
                and t_s - detection_gap_since > _DETECTION_LOSS_TIMEOUT_S:
            self.trigger_watchdog("检测丢失超时")
        elif self._last_telemetry_t is not None \
                and t_s - self._last_telemetry_t > _TELEMETRY_STALE_TIMEOUT_S:
            self.trigger_watchdog("遥测停滞超时")
        elif self._consecutive_send_failures >= _SEND_FAILURE_LIMIT:
            self.trigger_watchdog("控制下发连续失败")

    def stop_camera_loop(self) -> None:
        self._running = False
        if self._camera_thread is not None:
            self._camera_thread.join(timeout=2.0)
            self._camera_thread = None
        pump_stuck = False
        if self._frame_source is not None:
            self._frame_source.stop()
            # 泵线程堵在 cap.read()（DSHOW 僵尸句柄可致无限阻塞）时，
            # 另一线程并发 close/release 是未定义行为——跳过 close，
            # 句柄泄漏给 OS 进程退出回收比 UB 安全（交接文档 §4.1 场景）。
            pump_stuck = self._frame_source.alive
            if pump_stuck:
                logger.warning("相机泵线程未在宽限内退出，跳过 camera.close() "
                               "（句柄交由 OS 回收）")
            self._frame_source = None
        if self._camera is not None:
            if not pump_stuck:
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
            # 丢检测帧：清观察期 β 稳定锚点（缺口不计入接管计时，E5）
            self.session.note_detection_gap()
            return
        state = self.session.state
        if state == DriftSessionState.AUTO_OBSERVE:
            engaged = self.session.update_auto_observation(beta_deg, t_s)
            if engaged:
                self._send({"car_mode": 2})
        elif state == DriftSessionState.AUTO_ENGAGED:
            if pose is None:
                # ENGAGED 帧缺位姿（生产链路不可达——β 缺帧已早退；测试钩子
                # 会踩到这里）：显式跳过外环，不得拿 (0,0) 垃圾坐标喂控制器
                return
            out = self.controller.update(beta_deg=beta_deg, yaw_rate_dps=yaw_rate_dps,
                                         pose=(pose["x"], pose["y"]), t_s=t_s)
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
            "camera_fps": round(self.camera_fps, 1),
            "camera_running": bool(self._camera_thread is not None
                                   and self._camera_thread.is_alive()),
            "camera_loop_errors": self.camera_loop_errors,
            "send_failures": self.send_failures,
            "read_ms": round(self.read_ema_ms, 1),
            "detect_ms": round(self.detect_ema_ms, 1),
            "frames_total": self.frames_total,
            "tag_hits": self.tag_hits,
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
        converted = {}
        for key, value in updates.items():
            v = float(value)  # TypeError/ValueError 由路由层映射 422
            if not math.isfinite(v):
                raise ValueError(f"配置项 {key} 必须为有限数值，收到 {value!r}")
            if key in _NONNEGATIVE_CONFIG_KEYS and v < 0:
                raise ValueError(f"配置项 {key} 不允许负值（物理无意义），收到 {v}")
            converted[key] = v
        for key, value in converted.items():  # 全部校验通过后才落配置
            setattr(self.config, key, value)


_CONFIG_KEYS = {
    "beta_target_deg", "k_beta", "max_yaw_rate_dps", "k_radius_to_freq",
    "k_yaw", "k_yaw_i", "integral_limit", "pulse_freq_hz", "pulse_duty",
    "pulse_amplitude", "pulse_base", "max_steering_delta_per_tick",
    "max_steering_rate_per_s", "radius_freq_sign",
}

# 负值无物理意义、一律拒绝的配置项（脉冲频率/占空比/幅值/基值、转向摆速上限）。
# β 目标、增益等带符号参数不在此门禁；radius_freq_sign 取 ±1（语义开关）。
_NONNEGATIVE_CONFIG_KEYS = {
    "pulse_freq_hz", "pulse_duty", "pulse_amplitude", "pulse_base",
    "max_steering_rate_per_s",
}


def _config_as_dict(cfg: ControllerConfig) -> dict:
    d = {key: getattr(cfg, key) for key in sorted(_CONFIG_KEYS)}
    # 展示生效值而非 None：未显式设置时按旧字段 ×60 兼容映射（与控制器同口径）
    d["max_steering_rate_per_s"] = cfg.effective_max_steering_rate_per_s
    return d


drift_engine = DriftEngine()
