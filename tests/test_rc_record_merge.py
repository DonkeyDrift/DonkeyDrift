"""RcRecordMerge：RC 手动驾驶时把实际执行控制量合并进录制通道的单元测试。"""

from donkeycar.parts.actuator import RcRecordMerge


def run_merge(user_angle=0.0, user_throttle=0.0,
              rc_steering=None, rc_throttle=None, rc_mode=None, rc_park=None):
    return RcRecordMerge().run(user_angle, user_throttle,
                               rc_steering, rc_throttle, rc_mode, rc_park)


def test_manual_mode_records_rc_values():
    # 固件 MANUAL（rc/mode==0）时，RC 实际执行值覆盖恒为 0 的 Web 通道
    angle, throttle = run_merge(user_angle=0.0, user_throttle=0.0,
                                rc_steering=-0.33, rc_throttle=0.5,
                                rc_mode=0, rc_park=0)
    assert angle == -0.33
    assert throttle == 0.5


def test_manual_mode_rc_values_converted_to_float():
    # 上游缓存可能是 int，输出统一为 float
    angle, throttle = run_merge(rc_steering=-1, rc_throttle=1, rc_mode=0, rc_park=0)
    assert angle == -1.0 and isinstance(angle, float)
    assert throttle == 1.0 and isinstance(throttle, float)


def test_semi_auto_mode_passes_through_user_values():
    angle, throttle = run_merge(user_angle=0.12, user_throttle=0.34,
                                rc_steering=-0.9, rc_throttle=0.9,
                                rc_mode=1, rc_park=0)
    assert (angle, throttle) == (0.12, 0.34)


def test_full_auto_mode_passes_through_user_values():
    angle, throttle = run_merge(user_angle=0.12, user_throttle=0.34,
                                rc_steering=-0.9, rc_throttle=0.9,
                                rc_mode=2, rc_park=0)
    assert (angle, throttle) == (0.12, 0.34)


def test_unknown_mode_passes_through():
    # 无 ESP32（仿真等）时 rc/mode 为 None，不改变既有录制行为
    angle, throttle = run_merge(user_angle=0.12, user_throttle=0.34,
                                rc_steering=-0.9, rc_throttle=0.9,
                                rc_mode=None, rc_park=None)
    assert (angle, throttle) == (0.12, 0.34)


def test_park_locked_passes_through():
    # park 锁定时固件不更新 car_output，T 帧是旧值，不得录进 tub
    angle, throttle = run_merge(user_angle=0.0, user_throttle=0.0,
                                rc_steering=-0.33, rc_throttle=0.5,
                                rc_mode=0, rc_park=1)
    assert (angle, throttle) == (0.0, 0.0)


def test_manual_mode_missing_rc_values_passes_through():
    # MANUAL 但尚未收到 T 帧（rc 值为 None）时透传，避免覆盖为 None
    angle, throttle = run_merge(user_angle=0.12, user_throttle=0.34,
                                rc_steering=None, rc_throttle=None,
                                rc_mode=0, rc_park=0)
    assert (angle, throttle) == (0.12, 0.34)


def test_user_values_none_are_preserved():
    # 透传路径原样返回（含 None），不引入额外默认值
    angle, throttle = run_merge(user_angle=None, user_throttle=None, rc_mode=2)
    assert (angle, throttle) == (None, None)
