from .setup import on_pi

from donkeycar.parts.actuator import Arduino, PCA9685, PWMSteering, PWMThrottle
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
    original_device = Arduino.ard_device
    Arduino.ard_device = FakeArduinoSerial(line)
    controller = Arduino.__new__(Arduino)
    controller.throttle = 0
    controller.steering = 0

    try:
        result = controller.Arduino_readline()
    finally:
        Arduino.ard_device = original_device

    assert result["throttle"] == pytest.approx(expected_throttle)
    assert result["steering"] == pytest.approx(expected_steering)
