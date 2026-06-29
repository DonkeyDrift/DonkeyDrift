from .setup import on_pi

from donkeycar.parts.actuator import Arduino, ArdImu, PCA9685, PWMSteering, PWMThrottle
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

    def inWaiting(self):
        return 1

    def readline(self):
        return self.line


def _make_arduino_controller(line):
    """创建带假串口的 Arduino 控制器实例，绕过 __init__ 避免真实串口连接"""
    original_device = Arduino.ard_device
    Arduino.ard_device = FakeArduinoSerial(line)
    controller = Arduino.__new__(Arduino)
    controller.throttle = 0
    controller.steering = 0
    controller.imu_data = {}
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
