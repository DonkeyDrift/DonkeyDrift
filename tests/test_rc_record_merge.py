# -*- coding: utf-8 -*-
"""RcRecordMerge：RC 手动驾驶时把 RC 实际控制量合并进 tub 录制通道（Issue #133）。"""
from pathlib import Path

from donkeydrifter.parts.actuator import RcRecordMerge

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPLETE_PY = REPO_ROOT / "donkeycar" / "templates" / "complete.py"


def run_merge(user_angle, user_throttle, rc_steering, rc_throttle,
              rc_mode, rc_park=None):
    return RcRecordMerge().run(user_angle, user_throttle, rc_steering,
                               rc_throttle, rc_mode, rc_park)


def test_manual_mode_merges_rc_values():
    """MANUAL（rc/mode==0）且非 park 时，用 RC 实际值覆盖 user 通道。"""
    assert run_merge(0.0, 0.0, 0.35, -0.6, 0, False) == (0.35, -0.6)


def test_semi_auto_passthrough():
    """SEMI AUTO（rc/mode==1）沿用旧逻辑，不覆盖。"""
    assert run_merge(0.1, 0.2, 0.9, 0.9, 1, False) == (0.1, 0.2)


def test_full_auto_passthrough():
    """FULL AUTO（rc/mode==2）透传，不覆盖。"""
    assert run_merge(-0.3, 0.4, 0.9, -0.9, 2, False) == (-0.3, 0.4)


def test_park_passthrough():
    """park 锁定时透传，避免 park 抢闸值被写入训练数据。"""
    assert run_merge(0.0, 0.0, 0.8, -0.8, 0, True) == (0.0, 0.0)


def test_unknown_mode_passthrough():
    """rc/mode 未知（None，如仿真、M 帧未到）时安全透传。"""
    assert run_merge(0.12, 0.34, 0.9, -0.9, None, None) == (0.12, 0.34)


def test_invalid_rc_value_passthrough():
    """rc 值为 None（串口未收到 T 帧）时不覆盖。"""
    assert run_merge(0.0, 0.0, None, 0.5, 0, False) == (0.0, 0.0)
    assert run_merge(0.0, 0.0, 0.5, None, 0, False) == (0.0, 0.0)


def test_bool_rc_value_rejected():
    """bool 是 int 子类，视为无效值透传。"""
    assert run_merge(0.1, 0.1, True, False, 0, False) == (0.1, 0.1)


def test_complete_template_wires_rc_record_merge():
    """complete.py 在 TubWriter 前接入 RcRecordMerge，且 ARDUINO_CONTROLLER 链发布 rc/*。"""
    src = COMPLETE_PY.read_text(encoding="utf-8")
    assert "RcRecordMerge()" in src
    assert src.index("V.add(RcRecordMerge()") < src.index("tub_writer = TubWriter(")
    assert "ArdRc(controller=arduino_controller)" in src
    assert "'rc/steering', 'rc/throttle', 'rc/mode', 'rc/park'" in src
