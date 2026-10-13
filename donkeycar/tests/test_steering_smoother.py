import time

from donkeycar.parts.steering_smoother import SteeringSmoother


def test_first_value_initializes_and_passes_through():
    s = SteeringSmoother()
    assert s.run(0.5) == 0.5


def test_none_passes_through_without_polluting_state():
    s = SteeringSmoother()
    assert s.run(None) is None
    assert not s.initialized
    assert s.run(0.25) == 0.25


def test_ema_smooths_step():
    s = SteeringSmoother(alpha=0.5, slew_per_sec=0)
    s.run(0.0)
    v = s.run(1.0)
    assert abs(v - 0.5) < 1e-6


def test_slew_limits_step_rate():
    s = SteeringSmoother(alpha=1.0, slew_per_sec=8.0)
    s.run(0.0)
    time.sleep(0.02)
    v = s.run(1.0)
    # 20ms 间隔下 8/s 限幅只允许 ~0.16 的变化（留时间裕量）
    assert 0.0 < v <= 8.0 * 0.03


def test_converges_to_held_value():
    s = SteeringSmoother(alpha=0.35, slew_per_sec=8.0)
    v = s.run(0.0)
    for _ in range(200):
        v = s.run(-0.5)
        time.sleep(0.001)
    assert abs(v - (-0.5)) < 1e-3


def test_single_frame_glitch_is_softened():
    # 保持 -0.5 时插入单帧 0（摇杆微释放拍零）：输出不得被拉到 0 附近
    s = SteeringSmoother(alpha=0.35, slew_per_sec=8.0)
    for _ in range(100):
        s.run(-0.5)
        time.sleep(0.001)
    v = s.run(0.0)
    assert v < -0.2


def test_disabled_passthrough():
    s = SteeringSmoother(alpha=1.0, slew_per_sec=0)
    s.run(0.0)
    assert s.run(0.83) == 0.83
    assert s.run(-0.17) == -0.17
