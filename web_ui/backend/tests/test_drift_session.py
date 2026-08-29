# -*- coding: utf-8 -*-
"""DriftSession 状态机单元测试（RFC docs/Rfc/overhead-drift-control.md 第 4 节）。

覆盖：状态转换与守卫、接管判定（β 稳定门限）、看门狗路径、事件历史。
全部使用合成数据，不依赖相机/串口/网络。
"""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from drift_session import DriftSession, DriftSessionState


def make_session(calibration_ok=True):
    return DriftSession(calibration_ready=lambda: calibration_ok)


class TestBasicTransitions:
    def test_initial_state_is_idle(self):
        assert DriftSession().state == DriftSessionState.IDLE

    def test_idle_to_calibrate_and_back(self):
        s = make_session()
        s.start_calibration()
        assert s.state == DriftSessionState.CALIBRATE
        s.finish_calibration(ok=True)
        assert s.state == DriftSessionState.IDLE

    def test_calibrate_failure_also_returns_to_idle(self):
        s = make_session()
        s.start_calibration()
        s.finish_calibration(ok=False)
        assert s.state == DriftSessionState.IDLE

    def test_record_requires_calibration(self):
        s = make_session(calibration_ok=False)
        with pytest.raises(RuntimeError, match="标定"):
            s.start_recording()

    def test_record_round_trip(self):
        s = make_session()
        s.start_recording()
        assert s.state == DriftSessionState.RECORD
        s.stop_recording()
        assert s.state == DriftSessionState.IDLE

    def test_record_cannot_jump_to_auto(self):
        s = make_session()
        s.start_recording()
        with pytest.raises(RuntimeError):
            s.start_auto()


class TestAutoEngagement:
    def test_auto_starts_in_observe(self):
        s = make_session()
        s.start_auto()
        assert s.state == DriftSessionState.AUTO_OBSERVE

    def test_auto_requires_calibration(self):
        s = make_session(calibration_ok=False)
        with pytest.raises(RuntimeError, match="标定"):
            s.start_auto()

    def test_engage_after_stable_beta(self):
        """|β|>15° 持续 500ms → AUTO_ENGAGED（RFC 阶段 2 判定）。"""
        s = make_session()
        s.start_auto()
        # 0~0.4s：β 超阈值但未满 500ms，保持观察
        s.update_auto_observation(beta_deg=20.0, t_s=0.0)
        s.update_auto_observation(beta_deg=22.0, t_s=0.4)
        assert s.state == DriftSessionState.AUTO_OBSERVE
        # 0.6s：持续超阈值满 500ms，接管
        s.update_auto_observation(beta_deg=25.0, t_s=0.6)
        assert s.state == DriftSessionState.AUTO_ENGAGED

    def test_beta_dip_resets_stability_timer(self):
        """β 中途回落阈值以下 → 计时重置，抖动不得误触发接管。"""
        s = make_session()
        s.start_auto()
        s.update_auto_observation(beta_deg=20.0, t_s=0.0)
        s.update_auto_observation(beta_deg=5.0, t_s=0.3)   # 回落
        s.update_auto_observation(beta_deg=20.0, t_s=0.4)  # 重新起算
        s.update_auto_observation(beta_deg=22.0, t_s=0.7)  # 只持续了 0.3s
        assert s.state == DriftSessionState.AUTO_OBSERVE
        s.update_auto_observation(beta_deg=22.0, t_s=0.95)  # 满 500ms
        assert s.state == DriftSessionState.AUTO_ENGAGED

    def test_negative_beta_also_counts(self):
        """反方向漂移（逆时针）同样满足 |β| 判定。"""
        s = make_session()
        s.start_auto()
        s.update_auto_observation(beta_deg=-18.0, t_s=0.0)
        s.update_auto_observation(beta_deg=-20.0, t_s=0.55)
        assert s.state == DriftSessionState.AUTO_ENGAGED

    def test_small_beta_never_engages(self):
        s = make_session()
        s.start_auto()
        for t in [0.0, 0.3, 0.6, 1.0, 2.0]:
            s.update_auto_observation(beta_deg=10.0, t_s=t)
        assert s.state == DriftSessionState.AUTO_OBSERVE


class TestWatchdogAndStop:
    def test_watchdog_returns_to_idle_with_reason(self):
        s = make_session()
        s.start_auto()
        s.update_auto_observation(beta_deg=20.0, t_s=0.0)
        s.update_auto_observation(beta_deg=22.0, t_s=0.6)
        assert s.state == DriftSessionState.AUTO_ENGAGED
        s.watchdog_trigger("相机丢帧超过 200ms")
        assert s.state == DriftSessionState.IDLE

    def test_watchdog_during_observe_also_returns_to_idle(self):
        s = make_session()
        s.start_auto()
        s.watchdog_trigger("WebSocket 断开")
        assert s.state == DriftSessionState.IDLE

    def test_stop_auto_from_engaged(self):
        s = make_session()
        s.start_auto()
        s.update_auto_observation(beta_deg=20.0, t_s=0.0)
        s.update_auto_observation(beta_deg=22.0, t_s=0.6)
        s.stop_auto()
        assert s.state == DriftSessionState.IDLE


class TestEventHistory:
    def test_events_are_recorded(self):
        s = make_session()
        s.start_recording()
        s.stop_recording()
        kinds = [e.kind for e in s.events]
        assert "start_recording" in kinds
        assert "stop_recording" in kinds

    def test_watchdog_reason_is_kept(self):
        s = make_session()
        s.start_auto()
        s.watchdog_trigger("测试原因")
        reasons = [e.detail.get("reason") for e in s.events if e.kind == "watchdog"]
        assert "测试原因" in reasons
