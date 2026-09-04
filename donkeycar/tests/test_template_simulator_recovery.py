"""验证 simulator.py 模板正确连接了重连标志与模拟器连接状态。

不要只做字符串存在性检查（那样形同虚设），而是用 AST 解析每个
`V.add(...)` 的 inputs/outputs 列表，逐一核对键名与数量，确保
DriveApiBridge 的 7 元组返回值、DonkeyGymEnv 的重连输入、以及
SimConnectionState -> bridge 的 sim/connected 链路真正对上。
"""
import ast
from pathlib import Path

TEMPLATE = Path("donkeycar/templates/simulator.py")


def _parse():
    tree = ast.parse(TEMPLATE.read_text(encoding="utf-8"))
    calls = []
    assigns = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "V"
            and node.func.attr == "add"
        ):
            calls.append(node)
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, (ast.List, ast.Tuple))
        ):
            try:
                value = ast.literal_eval(node.value)
            except Exception:
                continue
            assigns.setdefault(node.targets[0].id, []).append((node.lineno, value))
    return calls, assigns


def _first_arg_name(call):
    arg = call.args[0]
    if isinstance(arg, ast.Name):
        return arg.id
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
        return arg.func.id
    return None


def _resolve(value_node, assigns):
    if isinstance(value_node, (ast.List, ast.Tuple)):
        return ast.literal_eval(value_node)
    if isinstance(value_node, ast.Name):
        candidates = assigns.get(value_node.id, [])
        best = None
        for lineno, value in candidates:
            if lineno < value_node.lineno:
                best = value
        return best
    return None


def _kw(call, name, assigns):
    for kw in call.keywords:
        if kw.arg == name:
            return _resolve(kw.value, assigns)
    return None


def _call_for(name):
    calls, _ = _parse()
    for call in calls:
        if _first_arg_name(call) == name:
            return call
    raise AssertionError(f"未找到 V.add({name}, ...)")


def _bridge_call(calls, assigns):
    """定位 DriveApiBridge 的 V.add(ctr, ...)，而非 JoystickController 的 ctr。"""
    for c in calls:
        if _first_arg_name(c) != "ctr":
            continue
        outputs = _kw(c, "outputs", assigns)
        if outputs and "reconnect_simulator" in outputs:
            return c
    raise AssertionError("未找到 DriveApiBridge 的 V.add(ctr, ...)")


def test_bridge_outputs_align_with_seven_tuple():
    """DriveApiBridge.run_threaded 返回 7 元组，模板 outputs 必须一一对应。"""
    calls, assigns = _parse()
    ctr = _bridge_call(calls, assigns)
    outputs = _kw(ctr, "outputs", assigns)
    assert outputs == [
        "user/angle",
        "user/throttle",
        "user/mode",
        "recording",
        "web/buttons",
        "reconnect_simulator",
        "car/mode_cmd",
    ], f"ctr outputs 未与 7 元组返回值对齐: {outputs}"


def test_bridge_inputs_include_sim_connected():
    """DriveApiBridge 需接收 sim/connected 以透传模拟器连接状态。"""
    calls, assigns = _parse()
    ctr = _bridge_call(calls, assigns)
    inputs = _kw(ctr, "inputs", assigns)
    assert "sim/connected" in inputs, f"ctr inputs 缺少 sim/connected: {inputs}"


def test_cam_inputs_include_reconnect_simulator():
    """DonkeyGymEnv 需接收 reconnect_simulator 以响应强制重连请求。"""
    calls, assigns = _parse()
    cam = next(c for c in calls if _first_arg_name(c) == "cam")
    inputs = _kw(cam, "inputs", assigns)
    assert "reconnect_simulator" in inputs, f"cam inputs 缺少 reconnect_simulator: {inputs}"


def test_sim_connection_state_publishes_sim_connected():
    """SimConnectionState 发布 sim/connected，供遥测透传到前端。"""
    calls, assigns = _parse()
    sim_state = next(c for c in calls if _first_arg_name(c) == "SimConnectionState")
    outputs = _kw(sim_state, "outputs", assigns)
    assert outputs == ["sim/connected"], f"SimConnectionState outputs 错误: {outputs}"
