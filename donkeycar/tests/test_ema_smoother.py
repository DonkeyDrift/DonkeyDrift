"""EmaSmoother 通道平滑测试（油门平滑与 SteeringSmoother 共用同一实现）。"""
import time

from donkeycar.parts.steering_smoother import EmaSmoother, SteeringSmoother


def test_steering_smoother_is_ema_smoother_alias():
    s = SteeringSmoother()
    assert isinstance(s, EmaSmoother)
    # 兼容别名沿用原转向默认参数
    assert s.alpha == 0.35
    assert s.slew_per_sec == 8.0


def test_throttle_params_track_step_halving():
    # alpha=0.5（油门默认）：0.1s 间隔下 slew 余量 0.6 > 0.5，EMA 阶跃减半不被卡住
    s = EmaSmoother(alpha=0.5, slew_per_sec=6.0)
    s.run(0.0)
    time.sleep(0.1)
    v = s.run(1.0)
    assert abs(v - 0.5) < 1e-6


def test_zero_dither_is_absorbed():
    # 零位 ±1px（行程 82px 时 ≈0.012）符号抖动：EMA 输出幅值不放大、不产生钳 0 型毛刺
    s = EmaSmoother(alpha=0.5, slew_per_sec=6.0)
    v = s.run(0.012)
    assert v == 0.012
    for x in [-0.012, 0.012, -0.012, -0.012, 0.012, -0.012]:
        time.sleep(0.002)
        v = s.run(x)
        assert abs(v) <= 0.012
    # 恒定小输入可完整跟踪到目标（无死区、无钳 0）：收敛到 -0.012
    for _ in range(30):
        time.sleep(0.002)
        v = s.run(-0.012)
    assert abs(v - (-0.012)) < 1e-3


def test_slew_limits_step_rate():
    s = EmaSmoother(alpha=1.0, slew_per_sec=6.0)
    s.run(0.0)
    time.sleep(0.02)
    v = s.run(1.0)
    # 20ms 间隔下 6/s 限幅只允许 ~0.12 的变化（留时间裕量）
    assert 0.0 < v <= 6.0 * 0.03


def test_none_passes_through_without_polluting_state():
    s = EmaSmoother(alpha=0.5, slew_per_sec=6.0)
    assert s.run(None) is None
    assert not s.initialized
    assert s.run(0.25) == 0.25
