"""验证 complete.py 模板给 DonkeyGymEnv 注册的 inputs 与 run_threaded 签名按位置对齐。

Vehicle 主循环按位置解包 run_threaded(*inputs)（donkeycar/vehicle.py），
validate_input_arity 只校验输入个数 ≤ 参数个数，查不出语义错位——
曾经 complete.py 漏接 'brake'，导致 reconnect_simulator 落进 brake、
reset_car 落进 reconnect：按复位按钮变成整场景重载（load_scene），
重连信号被 brake 吞掉。本测试用 AST 取出模板中 V.add(gym, inputs=...)
的列表，与 DonkeyGymEnv.run_threaded 的 inspect.signature 参数名做
逐位置比对，防止同类错位复发。
"""
import ast
import inspect
from pathlib import Path

from donkeycar.parts.dgym import DonkeyGymEnv

TEMPLATE = Path(__file__).resolve().parents[2] / "donkeycar" / "templates" / "complete.py"

# 通道名 -> run_threaded 参数名的语义映射。除 reconnect_simulator 外，
# 其余驾驶通道名与参数名一致（恒等映射）。
CHANNEL_TO_PARAM = {
    "reconnect_simulator": "reconnect",
}


def _gym_inputs() -> list:
    """从 complete.py 解析 V.add(gym, inputs=inputs, ...) 实际使用的 inputs 列表。"""
    source = TEMPLATE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignments = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            try:
                assignments.setdefault(node.targets[0].id, []).append(
                    (node.lineno, ast.literal_eval(node.value)))
            except (ValueError, SyntaxError):
                pass
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add"):
            continue
        if not (node.args and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "gym"):
            continue
        for kw in node.keywords:
            if kw.arg != "inputs":
                continue
            try:
                return ast.literal_eval(kw.value)
            except (ValueError, SyntaxError):
                # ast.walk 是 BFS，assignments 不保证按行号有序，必须显式排序
                prior = sorted(v for ln, v in assignments.get(kw.value.id, [])
                               if ln < node.lineno)
                if prior:
                    return prior[-1]
        raise AssertionError("V.add(gym, ...) 缺少 inputs 参数")
    raise AssertionError("complete.py 中找不到 V.add(gym, ...)")


def _run_threaded_param_names() -> list:
    """DonkeyGymEnv.run_threaded 的位置参数名（不含 self）。"""
    params = list(inspect.signature(DonkeyGymEnv.run_threaded).parameters.values())
    return [p.name for p in params if p.name != "self"]


def test_gym_inputs_align_with_run_threaded_signature():
    """inputs 逐个位置与签名参数名语义对齐（防 reconnect/reset 错位复发）。"""
    inputs = _gym_inputs()
    param_names = _run_threaded_param_names()
    assert inputs, "complete.py 未给 DonkeyGymEnv 注册 inputs"
    assert len(inputs) <= len(param_names), (
        f"inputs 数量({len(inputs)})超过 run_threaded 参数数量({len(param_names)})，"
        f"validate_input_arity 会拒绝启动: {inputs} vs {param_names}"
    )
    for idx, channel in enumerate(inputs):
        expected_param = CHANNEL_TO_PARAM.get(channel, channel)
        assert idx < len(param_names), f"inputs[{idx}]={channel!r} 越界: {param_names}"
        actual_param = param_names[idx]
        assert actual_param == expected_param, (
            f"inputs 位置错位: inputs[{idx}]={channel!r} 会落入参数 {actual_param!r}，"
            f"期望落入 {expected_param!r}（inputs={inputs}，签名={param_names}）"
        )


def test_reconnect_simulator_wired_to_reconnect_param():
    """'reconnect_simulator' 通道必须对位 run_threaded 的 reconnect 参数。"""
    inputs = _gym_inputs()
    param_names = _run_threaded_param_names()
    assert "reconnect_simulator" in inputs, f"inputs 缺少 reconnect_simulator: {inputs}"
    idx = inputs.index("reconnect_simulator")
    assert param_names[idx] == "reconnect", (
        f"reconnect_simulator 落在参数 {param_names[idx]!r}，重连信号到不了 reconnect"
    )


def test_reset_car_wired_to_reset_car_param():
    """'reset_car' 通道必须对位 run_threaded 的 reset_car 参数（就近复位）。"""
    inputs = _gym_inputs()
    param_names = _run_threaded_param_names()
    assert "reset_car" in inputs, f"inputs 缺少 reset_car: {inputs}"
    idx = inputs.index("reset_car")
    assert param_names[idx] == "reset_car", (
        f"reset_car 落在参数 {param_names[idx]!r}，复位按钮会触发错误的参数路径"
    )


def test_brake_channel_present_before_reconnect():
    """brake 通道必须显式占位，否则后续信号整体前移一位（错位根因）。"""
    inputs = _gym_inputs()
    assert "brake" in inputs, (
        f"inputs 缺少 'brake' 占位通道: {inputs}。run_threaded 第 3 位是 brake，"
        f"缺位会让 reconnect_simulator 落进 brake、reset_car 落进 reconnect"
    )
