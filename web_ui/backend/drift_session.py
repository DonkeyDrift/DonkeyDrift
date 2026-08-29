# -*- coding: utf-8 -*-
"""第三视角漂移会话状态机（RFC docs/Rfc/overhead-drift-control.md 第 4 节）。

状态与分阶段控制流：
    IDLE ──start_calibration──→ CALIBRATE ──finish_calibration──→ IDLE
    IDLE ──start_recording───→ RECORD ──stop_recording──→ IDLE
    IDLE ──start_auto───→ AUTO_OBSERVE ──|β|>阈值持续 stabilize_s──→ AUTO_ENGAGED
    任意 AUTO 状态 ──watchdog_trigger──→ IDLE（原因记录进事件历史）

守卫：RECORD/AUTO 启动前标定必须就绪（calibration_ready 回调注入，
便于测试与不同的标定文件判定策略解耦）。

本模块只管状态与判定，不做 I/O——相机、遥测、控制下发由调用方
（routers/drift.py 编排层）在状态回调里接线。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional


class DriftSessionState(Enum):
    IDLE = "idle"
    CALIBRATE = "calibrate"
    RECORD = "record"
    AUTO_OBSERVE = "auto_observe"
    AUTO_ENGAGED = "auto_engaged"


@dataclass
class SessionEvent:
    """状态机事件记录，供前端时间线展示与事后排查。"""
    kind: str
    detail: dict = field(default_factory=dict)
    t_s: float = 0.0


# 接管判定默认参数（RFC 7.2：|β|>15° 持续 500ms）
DEFAULT_ENGAGE_BETA_DEG = 15.0
DEFAULT_ENGAGE_STABLE_S = 0.5


class DriftSession:
    """漂转会话状态机。所有时间参数单位为秒，角度为度。"""

    def __init__(
        self,
        calibration_ready: Callable[[], bool] = lambda: False,
        engage_beta_deg: float = DEFAULT_ENGAGE_BETA_DEG,
        engage_stable_s: float = DEFAULT_ENGAGE_STABLE_S,
        clock: Callable[[], float] = None,
    ):
        self._calibration_ready = calibration_ready
        self._engage_beta_deg = engage_beta_deg
        self._engage_stable_s = engage_stable_s
        self._clock = clock or self._default_clock
        self._state = DriftSessionState.IDLE
        self.events: List[SessionEvent] = []
        # β 稳定计时的锚点：进入"超阈值"区间的时刻；None 表示当前未超阈值
        self._beta_over_since: Optional[float] = None

    @staticmethod
    def _default_clock() -> float:
        import time
        return time.time()

    # ── 基本转换 ──────────────────────────────────────────────
    @property
    def state(self) -> DriftSessionState:
        return self._state

    def _require_state(self, expected: DriftSessionState, action: str) -> None:
        if self._state != expected:
            raise RuntimeError(
                f"非法转换：{action} 需要处于 {expected.value}，当前为 {self._state.value}")

    def _require_calibration(self) -> None:
        if not self._calibration_ready():
            raise RuntimeError("标定未完成或标定文件缺失，禁止启动该模式")

    def _record(self, kind: str, **detail) -> None:
        self.events.append(SessionEvent(kind=kind, detail=detail, t_s=self._clock()))

    def start_calibration(self) -> None:
        self._require_state(DriftSessionState.IDLE, "开始标定")
        self._state = DriftSessionState.CALIBRATE
        self._record("start_calibration")

    def finish_calibration(self, ok: bool) -> None:
        self._require_state(DriftSessionState.CALIBRATE, "结束标定")
        self._state = DriftSessionState.IDLE
        self._record("finish_calibration", ok=ok)

    def start_recording(self) -> None:
        self._require_state(DriftSessionState.IDLE, "开始录制")
        self._require_calibration()
        self._state = DriftSessionState.RECORD
        self._record("start_recording")

    def stop_recording(self) -> None:
        self._require_state(DriftSessionState.RECORD, "停止录制")
        self._state = DriftSessionState.IDLE
        self._record("stop_recording")

    # ── AUTO 分阶段控制流（RFC 阶段 1→2）──────────────────────
    def start_auto(self) -> None:
        self._require_state(DriftSessionState.IDLE, "启动自动模式")
        self._require_calibration()
        self._state = DriftSessionState.AUTO_OBSERVE
        self._beta_over_since = None
        self._record("start_auto")

    def update_auto_observation(self, beta_deg: float, t_s: float) -> bool:
        """观察期喂数据：返回是否在本次调用中触发接管。

        β 使用外部统一时基 t_s（由调用方传入，保证与视觉/遥测管道同源），
        判定逻辑：|β| 超阈值则开始/维持计时，回落则清零。
        """
        if self._state != DriftSessionState.AUTO_OBSERVE:
            return False
        if abs(beta_deg) >= self._engage_beta_deg:
            if self._beta_over_since is None:
                self._beta_over_since = t_s
            elif t_s - self._beta_over_since >= self._engage_stable_s:
                self._state = DriftSessionState.AUTO_ENGAGED
                self._record("engage", beta_deg=beta_deg, t_s=t_s)
                return True
        else:
            self._beta_over_since = None
        return False

    def stop_auto(self) -> None:
        if self._state not in (DriftSessionState.AUTO_OBSERVE,
                               DriftSessionState.AUTO_ENGAGED):
            raise RuntimeError("当前不在自动模式，无法停止")
        was_engaged = self._state == DriftSessionState.AUTO_ENGAGED
        self._state = DriftSessionState.IDLE
        self._record("stop_auto", was_engaged=was_engaged)

    def watchdog_trigger(self, reason: str) -> None:
        """看门狗：丢帧/ws 断线/β 失稳等异常，一律退回 IDLE 交还人工。"""
        if self._state in (DriftSessionState.AUTO_OBSERVE,
                           DriftSessionState.AUTO_ENGAGED):
            was_engaged = self._state == DriftSessionState.AUTO_ENGAGED
            self._state = DriftSessionState.IDLE
            self._beta_over_since = None
            self._record("watchdog", reason=reason, was_engaged=was_engaged)
