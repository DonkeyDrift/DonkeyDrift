"""验证 simulator.py 模板正确连接了重连标志。"""
from pathlib import Path


def test_simulator_template_wires_reconnect_flag():
    source = Path("donkeycar/templates/simulator.py").read_text()

    assert "'reconnect_simulator_requested'" in source, \
        "DriveApiBridge 应输出 reconnect_simulator_requested"
    assert "'reconnect_simulator'" in source, \
        "DonkeyGymEnv 应接收 reconnect_simulator 输入"
