from .setup import on_pi

from donkeycar.parts.actuator import (
    Arduino, ArdImu, PCA9685, PWMSteering, PWMThrottle,
    ArdPWMSteering, ArdPWMThrottle, ArdModeCmd,
)
import pytest


@pytest.mark.skipif(on_pi() == False, reason='Not on RPi')
def test_PCA9685():
    c = PCA9685(0)

@pytest.mark.skipif(on_pi() == False, reason='Not on RPi')
def test_PWMSteering():
    c = PCA9685(0)
    s = PWMSteering(c, 300, 440)


class FakeArduinoSerial:
    def __init__(self, line):
        self.line = line
        self.written = []

    def inWaiting(self):
        return 1

    def readline(self):
        return self.line

    def write(self, data):
        self.written.append(data)
        return len(data)


def _make_arduino_controller(line):
    """创建带假串口的 Arduino 控制器实例，绕过 __init__ 避免真实串口连接"""
    original_device = Arduino.ard_device
    Arduino.ard_device = FakeArduinoSerial(line)
    controller = Arduino.__new__(Arduino)
    controller.throttle = 0
    controller.steering = 0
    controller.imu_data = {}
    controller._rx_buf = bytearray(line)
    return controller, original_device


def _restore_arduino_device(original_device):
    Arduino.ard_device = original_device


@pytest.mark.parametrize(
    "line, expected_throttle, expected_steering",
    [
        (b"T100S100\n", 1.0, 1.0),
        (b"T-100S-100\n", -1.0, -1.0),
        (b"T0S0\n", 0.0, 0.0),
        (b"T150S-150\n", 1.0, -1.0),
        (b"T:50:S:-50\n", 0.5, -0.5),
    ],
)
def test_arduino_readline_normalizes_rc_control_values(
    line, expected_throttle, expected_steering
):
    controller, original_device = _make_arduino_controller(line)
    try:
        result = controller.Arduino_readline()
    finally:
        _restore_arduino_device(original_device)

    assert result["throttle"] == pytest.approx(expected_throttle)
    assert result["steering"] == pytest.approx(expected_steering)


# ======================== $IMU 解析测试 ========================

IMU_LINE = b"$IMU,37473,662375,-0.0192,-0.1484,9.2751,-0.1058,0.0173,-0.0176\n"


def test_arduino_readline_parses_imu_data():
    """$IMU 帧应正确解析并存储到 controller.imu_data"""
    controller, original_device = _make_arduino_controller(IMU_LINE)
    try:
        result = controller.Arduino_readline()
    finally:
        _restore_arduino_device(original_device)

    # $IMU 帧不干扰控制数据流，应返回 None
    assert result is None

    # 验证 IMU 数据已存储
    imu = controller.imu_data
    assert imu['seq'] == 37473
    assert imu['ts_ms'] == 662375
    assert imu['accel_x'] == pytest.approx(-0.0192)
    assert imu['accel_y'] == pytest.approx(-0.1484)
    assert imu['accel_z'] == pytest.approx(9.2751)
    assert imu['gyro_x'] == pytest.approx(-0.1058)
    assert imu['gyro_y'] == pytest.approx(0.0173)
    assert imu['gyro_z'] == pytest.approx(-0.0176)


def test_arduino_readline_imu_returns_none_for_control_flow():
    """$IMU 帧返回 None，不应被 ArdPWMSteering 当作控制数据处理"""
    controller, original_device = _make_arduino_controller(IMU_LINE)
    try:
        result = controller.Arduino_readline()
    finally:
        _restore_arduino_device(original_device)

    # None 在 ArdPWMSteering.update() 中通过 if(self.Input_Temp): 检查被跳过
    assert result is None


def test_arduino_readline_imu_malformed_returns_none():
    """格式错误的 $IMU 帧应被静默处理，不抛异常"""
    controller, original_device = _make_arduino_controller(
        b"$IMU,bad,data\n"
    )
    try:
        result = controller.Arduino_readline()
    finally:
        _restore_arduino_device(original_device)

    # 解析失败时 Arduino_readline 的 except 分支不返回任何值（隐式 None）
    # 且不应抛出异常
    assert result is None


def test_arduino_readline_imu_partial_fields():
    """字段数不足的 $IMU 帧应被安全处理"""
    controller, original_device = _make_arduino_controller(
        b"$IMU,1,2,3,4,5,6,7\n"  # 仅 7 个字段（含 $IMU 前缀），期望 8 个
    )
    try:
        result = controller.Arduino_readline()
    finally:
        _restore_arduino_device(original_device)

    # 字段数不匹配，不更新 imu_data
    assert result is None


def test_arduino_readline_imu_drops_t_frame_contamination():
    """$IMU 帧末尾混入 T/S 控制帧时应丢弃，不抛异常"""
    controller, original_device = _make_arduino_controller(
        b"$IMU,59810,11448725,-0.1437,-0.3232,9.1530,-0.1122,0.0141,-0T2S-1\n"
    )
    try:
        result = controller.Arduino_readline()
    finally:
        _restore_arduino_device(original_device)

    assert result is None
    assert controller.imu_data == {}  # 不更新被污染的 IMU 数据


def test_arduino_readline_imu_drops_concatenated_numbers():
    """$IMU 帧中数字被拼接（逗号丢失）时应丢弃"""
    controller, original_device = _make_arduino_controller(
        b"$IMU,59794,11448469,-0.15800.1293,-0.2993,9.1435,-0.1130,0.0163,-0.0176\n"
    )
    try:
        result = controller.Arduino_readline()
    finally:
        _restore_arduino_device(original_device)

    assert result is None
    assert controller.imu_data == {}


def test_arduino_readline_imu_drops_invalid_numeric_field():
    """$IMU 帧中出现非法数字字段（如 '-'）时应丢弃"""
    controller, original_device = _make_arduino_controller(
        b"$IMU,60022,11452117,-,-0.2705,9.1506,-0.1122,0.0144,-0.0163\n"
    )
    try:
        result = controller.Arduino_readline()
    finally:
        _restore_arduino_device(original_device)

    assert result is None
    assert controller.imu_data == {}


# ======================== ArdImu Part 测试 ========================

class FakeArduinoControllerForImu:
    """模拟 Arduino 控制器，提供 imu_data 属性"""
    def __init__(self):
        self.imu_data = {}


def test_ardimu_poll_reads_imu_from_controller():
    """ArdImu.poll() 应从控制器读取 IMU 数据并更新自身属性"""
    fake_ctrl = FakeArduinoControllerForImu()
    fake_ctrl.imu_data = {
        'seq': 1, 'ts_ms': 1000,
        'accel_x': 0.01, 'accel_y': 0.02, 'accel_z': 9.81,
        'gyro_x': 0.1, 'gyro_y': 0.2, 'gyro_z': 0.3,
    }
    imu = ArdImu(controller=fake_ctrl)
    imu.poll()

    assert imu.accel_x == pytest.approx(0.01)
    assert imu.accel_y == pytest.approx(0.02)
    assert imu.accel_z == pytest.approx(9.81)
    assert imu.gyro_x == pytest.approx(0.1)
    assert imu.gyro_y == pytest.approx(0.2)
    assert imu.gyro_z == pytest.approx(0.3)
    # 当前固件未上传温度
    assert imu.temp == 0.0


def test_ardimu_run_threaded_returns_correct_tuple():
    """ArdImu.run_threaded() 应返回标准 IMU 元组格式"""
    fake_ctrl = FakeArduinoControllerForImu()
    fake_ctrl.imu_data = {
        'seq': 1, 'ts_ms': 2000,
        'accel_x': 0.1, 'accel_y': -0.2, 'accel_z': 9.8,
        'gyro_x': -0.01, 'gyro_y': 0.02, 'gyro_z': -0.03,
    }
    imu = ArdImu(controller=fake_ctrl)
    imu.poll()

    ax, ay, az, gx, gy, gz, temp = imu.run_threaded()
    assert ax == pytest.approx(0.1)
    assert ay == pytest.approx(-0.2)
    assert az == pytest.approx(9.8)
    assert gx == pytest.approx(-0.01)
    assert gy == pytest.approx(0.02)
    assert gz == pytest.approx(-0.03)
    assert temp == 0.0


def test_ardimu_poll_skips_empty_imu_data():
    """imu_data 为空时 poll() 不应修改属性"""
    fake_ctrl = FakeArduinoControllerForImu()
    imu = ArdImu(controller=fake_ctrl)
    # 设置初始值
    imu.accel_x = 1.0
    imu.poll()  # imu_data 为空，应跳过更新
    assert imu.accel_x == 1.0  # 未被覆盖


def test_ardimu_requires_controller():
    """ArdImu 必须传入控制器实例"""
    with pytest.raises(ValueError, match="ArdImu 需要一个 Arduino 控制器实例"):
        ArdImu(controller=None)


# ======================== 帧边界同步恢复测试 ========================


def test_arduino_readline_recovers_from_frame_slip():
    """前一帧尾部与下一帧头部被拼接成乱码时，应丢弃整行并解析后续完整帧"""
    # "-0.0T3S0\n" 模拟 $IMU 帧末尾的 -0.0 与 T3S0 控制帧被错误拼接；
    # 保守策略下整行丢弃，下一正常帧 T50S-50 被正确解析。
    controller, original_device = _make_arduino_controller(b"-0.0T3S0\nT50S-50\n")
    try:
        result = controller.Arduino_readline()
    finally:
        _restore_arduino_device(original_device)

    assert result is not None
    assert result["throttle"] == pytest.approx(0.5)
    assert result["steering"] == pytest.approx(-0.5)


def test_arduino_readline_recovers_from_imu_frame_slip():
    """控制帧尾部与下一 $IMU 帧拼接时，应丢弃错位字节并解析 $IMU"""
    imu_tail = b"9.2751,-0.1058,0.0173,-0.0176"
    next_imu = b"$IMU,37474,662376,-0.0200,-0.1500,9.2800,-0.1000,0.0200,-0.0200"
    controller, original_device = _make_arduino_controller(
        imu_tail + b"\n" + next_imu + b"\n"
    )
    try:
        result = controller.Arduino_readline()
    finally:
        _restore_arduino_device(original_device)

    assert result is None
    imu = controller.imu_data
    assert imu['seq'] == 37474
    assert imu['ts_ms'] == 662376
    assert imu['accel_x'] == pytest.approx(-0.0200)


def test_arduino_readline_drops_noise_without_header():
    """缓冲区中全是噪声且没有有效帧头时，应安全清空并返回 None"""
    controller, original_device = _make_arduino_controller(b"garbage,no,frame\n")
    try:
        result = controller.Arduino_readline()
    finally:
        _restore_arduino_device(original_device)

    assert result is None
    assert controller._rx_buf == b""


# ======================== ArdPWM 透传/缩放测试 ========================

class FakeControllerForArdPWM:
    """为 ArdPWMSteering/ArdPWMThrottle 提供的最小控制器替身"""
    def __init__(self):
        self.steeringCmd = 0
        self.throttleCmd = 0
        self.Input_RC = None
        self.imu_data = {}
        self._rx_buf = bytearray()
        self._cmds = []

    def set_cmd(self, mode, channel, val):
        self._cmds.append((mode, channel, val))
        if channel == 0:
            self.steeringCmd = val
        elif channel == 1:
            self.throttleCmd = val


@pytest.fixture
def fake_ard_pwm_controller():
    return FakeControllerForArdPWM()


def test_ardpwm_steering_user_mode_passthrough(fake_ard_pwm_controller):
    """user 模式应透传上游 steering_ard 还原后的 user/angle，不因 RC 怠速返回 None"""
    steering = ArdPWMSteering(controller=fake_ard_pwm_controller,
                              left_val=-100, right_val=100)
    # 模拟串口读到 T0S0，Output_Steering 会被设为 0.0
    steering.Output_Steering = 0.0
    steering.Output_Throttle = 0.0

    mode, angle = steering.run_threaded('user', 50.0)
    assert mode == 'user'
    assert angle == pytest.approx(0.5)
    # user 模式不应写入 set_cmd
    assert fake_ard_pwm_controller._cmds == []


def test_ardpwm_steering_user_mode_zero_angle_returns_zero(fake_ard_pwm_controller):
    """user 模式真实输入 0 时应返回 0，而不是因 0 为 falsy 返回 None"""
    steering = ArdPWMSteering(controller=fake_ard_pwm_controller,
                              left_val=-100, right_val=100)
    mode, angle = steering.run_threaded('user', 0.0)
    assert mode == 'user'
    assert angle == pytest.approx(0.0)


def test_ardpwm_steering_auto_mode_writes_pwm(fake_ard_pwm_controller):
    """非 user 模式应写入 PWM 命令并把 steering_ard 还原为 angle 返回"""
    steering = ArdPWMSteering(controller=fake_ard_pwm_controller,
                              left_val=-100, right_val=100)
    mode, angle = steering.run_threaded('local', -75.0)
    assert mode == 'local'
    assert angle == pytest.approx(-0.75)
    assert len(fake_ard_pwm_controller._cmds) == 1
    assert fake_ard_pwm_controller._cmds[0][0] == 'local'
    assert fake_ard_pwm_controller._cmds[0][1] == 0  # channel
    # -75 映射到 left_val=-100, right_val=100 的中间偏左
    assert fake_ard_pwm_controller.steeringCmd == -75


def test_ardpwm_throttle_user_mode_passthrough(fake_ard_pwm_controller):
    """user 模式应透传上游 throttleUser，不因 0 为 falsy 返回 None"""
    throttle = ArdPWMThrottle(controller=fake_ard_pwm_controller,
                              max_pulse=100, zero_pulse=0, min_pulse=-100)
    result = throttle.run('user', 0.0, 0.3)
    assert result == pytest.approx(0.3)
    assert fake_ard_pwm_controller._cmds == []


def test_ardpwm_throttle_user_mode_zero_returns_zero(fake_ard_pwm_controller):
    """user 模式 throttleUser=0 时应返回 0，而不是 None"""
    throttle = ArdPWMThrottle(controller=fake_ard_pwm_controller,
                              max_pulse=100, zero_pulse=0, min_pulse=-100)
    result = throttle.run('user', 0.0, 0.0)
    assert result == pytest.approx(0.0)


def test_ardpwm_throttle_auto_mode_writes_pwm(fake_ard_pwm_controller):
    """非 user 模式应写入 PWM 并把 throttle_ard 还原为 throttle 返回"""
    original_device = Arduino.ard_device
    Arduino.ard_device = FakeArduinoSerial(b"")
    try:
        fake_ard_pwm_controller.steeringCmd = 30
        throttle = ArdPWMThrottle(controller=fake_ard_pwm_controller,
                                  max_pulse=100, zero_pulse=0, min_pulse=-100)
        result = throttle.run('local', 60.0, 0.0)
        assert result == pytest.approx(0.6)
        assert fake_ard_pwm_controller.throttleCmd == 60
        # run() 应返回 run_threaded 的结果，而不是 None
        assert result is not None
    finally:
        Arduino.ard_device = original_device


# ======================== 车控模式下行命令测试 ========================

def test_arduino_set_car_mode_writes_cmd_frame():
    """set_car_mode 应向串口写出 C<m> 帧，非法值不写。"""
    original_device = Arduino.ard_device
    fake = FakeArduinoSerial(b"")
    Arduino.ard_device = fake
    try:
        controller = Arduino.__new__(Arduino)
        controller.set_car_mode(2)
        assert fake.written == [b"C2\n"]

        # 非法值不写
        controller.set_car_mode(3)
        controller.set_car_mode(-1)
        assert fake.written == [b"C2\n"]
    finally:
        Arduino.ard_device = original_device


class FakeModeController:
    def __init__(self):
        self.written = []

    def set_car_mode(self, mode):
        self.written.append(mode)


def test_ard_mode_cmd_writes_and_dedups():
    """ArdModeCmd 首次命令写入、重复命令去重、None 不写。"""
    ctrl = FakeModeController()
    part = ArdModeCmd(controller=ctrl)

    part.run(2)
    part.run(2)       # 重复命令去重
    part.run(None)    # 无命令不写
    part.run(1)

    assert ctrl.written == [2, 1]


def test_ard_mode_cmd_requires_controller():
    """ArdModeCmd 未提供控制器时应抛 ValueError。"""
    with pytest.raises(ValueError):
        ArdModeCmd(controller=None)

