"""MUS4 串口协议契约测试（DonkeyDrift 侧）。

契约源：`protocol/mus4_serial_v1.yaml`（两仓库共享的唯一协议事实来源）。
本测试不改运行时行为，只做**防漂移**：断言实现里的字面量与 schema 声明一致，
任一侧改了帧格式/常量但忘记更新 schema（或反向）都会立刻红灯。

实现落点：
  - donkeycar/parts/actuator.py（Arduino 类：下行拼帧、上行解析、帧头白名单）
"""
import pathlib
import re
import sys

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SCHEMA_PATH = REPO_ROOT.parent / "protocol" / "mus4_serial_v1.yaml"
ACTUATOR_PATH = REPO_ROOT / "donkeycar" / "parts" / "actuator.py"

# 契约文件是两仓库共享的（当前以同级目录形式提供）；缺失时跳过而不是红，
# 避免单独 checkout 一个仓库做开发时被跨仓库依赖卡死。
if not SCHEMA_PATH.is_file():
    pytest.skip(
        f"共享协议契约未找到: {SCHEMA_PATH}（单独 clone 时可跳过）",
        allow_module_level=True,
    )

yaml = pytest.importorskip("yaml")

SCHEMA = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))
ACTUATOR_SRC = ACTUATOR_PATH.read_text(encoding="utf-8")


def _frame(name):
    for group in ("uplink", "downlink"):
        for frame in SCHEMA[group]:
            if frame["name"] == name:
                return frame
    raise AssertionError(f"schema 中找不到帧: {name}")


def _const(path):
    node = SCHEMA["constants"]
    for key in path.split("."):
        node = node[key]
    return node


# --- schema 自身完整性 -------------------------------------------------------

def test_schema_identity():
    assert SCHEMA["schema"] == "mus4_serial"
    assert SCHEMA["version"] == 1
    assert SCHEMA["baudrate"] == 115200


def test_all_frame_regexes_compile():
    for group in ("uplink", "downlink"):
        for frame in SCHEMA[group]:
            if "regex" in frame:
                re.compile(frame["regex"])


# --- 下行：pilot_control 拼帧（actuator.py） --------------------------------

def test_downlink_pilot_control_regex_accepts_all_documented_variants():
    pattern = re.compile(_frame("pilot_control")["regex"])

    assert pattern.match("0:0")
    assert pattern.match("50:-50")
    assert pattern.match("50:50:100")
    assert pattern.match("10:-10*14")
    assert pattern.match("20:-20:255*2B")

    # 注意：regex 层只做形状匹配，越界值（200:0）由上层 validation.out_of_range=reject
    # 拒收（见 schema 与 CommandParser.parseAndValidateCommand 的 t/s ∈ [-100,100] 校验），
    # 所以这里只断言形状非法的输入被 regex 挡下。
    assert pattern.match("200:0")           # 形状合法，越界靠 validation 层
    assert not pattern.match("abc:def")
    assert not pattern.match("")
    assert not pattern.match("1:2:3:4:5")


def test_downlink_mode_command_regex():
    pattern = re.compile(_frame("mode_command")["regex"])

    assert pattern.match("MODE 0")
    assert pattern.match("MODE 1")
    assert pattern.match("MODE 2")
    assert pattern.match("MODE:1")           # 固件 CommandDispatcher 双前缀（空格/冒号）
    assert not pattern.match("MODE 3")
    assert not pattern.match("MODEX1")


def test_mode_command_literal_present_in_actuator():
    assert '"MODE {mode}\\n"' in ACTUATOR_SRC or "MODE {mode}" in ACTUATOR_SRC


def test_car_mode_enum_matches_actuator_guard():
    """actuator.set_car_mode 只接受 0/1/2，与 schema car_mode 枚举一致。"""
    assert _const("car_mode") == {"manual": 0, "semi_auto": 1, "full_auto": 2}
    assert "if mode not in (0, 1, 2)" in ACTUATOR_SRC


def test_control_range_matches_schema():
    assert _const("throttle_range") == {"min": -100, "max": 100}
    assert _const("steering_range") == {"min": -100, "max": 100}
    # actuator 解析后 clamp 到 [-100,100]，映射到 [-1.0,1.0]
    assert "clamp(raw_throttle, -100, 100)" in ACTUATOR_SRC
    assert "clamp(raw_steering, -100, 100)" in ACTUATOR_SRC


# --- 上行：帧头白名单与解析（actuator.py _pop_line_from_buf） ----------------

def test_uplink_frame_prefixes_match_schema():
    prefixes = SCHEMA["uplink_frame_prefixes"]
    assert prefixes == ["$IMU", "T", "M"]
    for prefix in prefixes:
        assert f"startswith(b'{prefix}')" in ACTUATOR_SRC or (
            f'b\'{prefix}\'' in ACTUATOR_SRC
        )


def test_uplink_telemetry_regex_matches_firmware_literal():
    """T<t>S<s> 与 schema regex 双向一致：schema 样例必须能被 regex 匹配。"""
    pattern = re.compile(_frame("control_telemetry")["regex"])

    assert pattern.match("T0S0")
    assert pattern.match("T-100S100")
    assert pattern.match("T-5S-5")
    assert not pattern.match("T100S100X")
    assert not pattern.match("X0S0")


def test_uplink_mode_park_regex():
    pattern = re.compile(_frame("mode_park_status")["regex"])

    assert pattern.match("M0:P0")
    assert pattern.match("M2:P1")
    assert pattern.match("M3:P0")            # 形状合法，枚举越界由上层校验
    assert not pattern.match("M0P0")
    assert not pattern.match("M0:P0:1")


def test_uplink_mode_park_parsed_fields_match_schema():
    """actuator 解析 M 帧后产出 mode/park 两个字段，与 schema fields 同名。"""
    names = [f["name"] for f in _frame("mode_park_status")["fields"]]
    assert names == ["m", "p"]
    assert "self.mode_data = {'mode': mode, 'park': park}" in ACTUATOR_SRC


def test_uplink_imu_field_count_matches_schema():
    assert _const("imu_field_count") == 9
    assert "if len(parts) != 9" in ACTUATOR_SRC


def test_uplink_imu_regex_matches_firmware_literal():
    pattern = re.compile(_frame("imu_sample")["regex"])

    sample = "$IMU,12,34567,0.1234,-9.8000,0.0000,0.0010,-0.0020,0.0030"
    assert pattern.match(sample)

    # 少字段 / 多字段 / 含非数字 / 字段里夹 T/S 污染 → 都不该匹配
    assert not pattern.match("$IMU,12,34567,0.1234")
    assert not pattern.match(sample + ",1.0")
    assert not pattern.match("$IMU,12,34567,0.1T34,-9.8,0.0,0.0,0.0,0.0")
    assert not pattern.match("T12S34,1,2,3,4,5,6,7,8")


def test_uplink_imu_corruption_guards_present():
    """schema known_issues 里记录的两条防线必须真的存在于实现里。"""
    assert "丢弃被 T/S 控制帧污染的 $IMU 帧" in ACTUATOR_SRC
    assert "re.fullmatch(r'-?\\d+(\\.\\d+)?', p)" in ACTUATOR_SRC


def test_uplink_imu_units_match_schema():
    units = {f["name"]: f.get("unit") for f in _frame("imu_sample")["fields"]}
    assert units["ax"] == "m/s^2"
    assert units["gx"] == "rad/s"


# --- 频率常量 ---------------------------------------------------------------

def test_rate_constants_match_schema():
    assert _const("uplink_telemetry_rate_hz") == 60
    assert _const("uplink_imu_rate_hz") == 100
    assert _const("uplink_mode_heartbeat_rate_hz") == 1


# --- 契约元数据：固件侧必须有对应测试 ---------------------------------------

def test_sibling_firmware_contract_test_exists():
    """两仓库共享同一份 schema，固件侧也必须有对称的契约测试。"""
    sibling = REPO_ROOT.parent / "Firmware" / "MUS4_FW" / "tests" / "test_mus4_serial_contract.py"
    if not sibling.is_file():
        pytest.skip(f"固件侧契约测试尚未落地: {sibling}")
    assert sibling.is_file()
