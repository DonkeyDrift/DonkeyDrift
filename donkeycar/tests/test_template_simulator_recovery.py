"""验证 simulator.py 模板正确连接了重连标志与模拟器连接状态。

DriveApiBridge.run_threaded 返回 7 元组
(angle, throttle, mode, recording, buttons, reconnect, car_mode_cmd)，
Vehicle/Memory 按位置把 ctr 的 outputs 键与返回值一一配对。
若 outputs 数量不足或键名与 cam(DonkeyGymEnv) 的 inputs 不匹配，
重连请求会被静默丢弃（issue 004 根因 C）。

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


_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "donkeycar" / "templates"
_BRIDGE = Path(__file__).resolve().parents[2] / "donkeycar" / "parts" / "drive_api_bridge.py"

EXPECTED_CTR_OUTPUTS = [
    'user/angle', 'user/throttle', 'user/mode', 'recording',
    'web/buttons', 'reconnect_simulator', 'car/mode_cmd',
]


def _v_add_kwargs(source: str, part_name: str, after_lineno: int = 0) -> dict:
    """从模板源码中解析 V.add(<part_name>, ...) 的关键字参数（仅支持字面量）。

    after_lineno 用于区分同一变量名的多个 V.add（如 ctr 在手柄分支和
    DriveApiBridge 分支各有一次）。
    """
    tree = ast.parse(source)
    # 收集 name = <字面量列表> 赋值，用于解析 inputs=inputs 这类间接引用
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
        if node.lineno <= after_lineno:
            continue
        if not (node.args and isinstance(node.args[0], ast.Name)
                and node.args[0].id == part_name):
            continue
        kwargs = {}
        for kw in node.keywords:
            try:
                kwargs[kw.arg] = ast.literal_eval(kw.value)
            except (ValueError, SyntaxError):
                if isinstance(kw.value, ast.Name):
                    prior = [v for ln, v in assignments.get(kw.value.id, [])
                             if ln < node.lineno]
                    if prior:
                        kwargs[kw.arg] = prior[-1]
        return kwargs
    raise AssertionError(f"模板中找不到 V.add({part_name}, ...)")


def _assignment_lineno(source: str, target: str, value_call: str) -> int:
    """找到 `target = value_call(...)` 赋值所在行号。"""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == target for t in node.targets):
            if (isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == value_call):
                return node.lineno
    raise AssertionError(f"模板中找不到 {target} = {value_call}(...)")


_SOURCE = (_TEMPLATES_DIR / "simulator.py").read_text(encoding="utf-8")
_CTR_LINE = _assignment_lineno(_SOURCE, "ctr", "DriveApiBridge")


def _bridge_return_arity() -> int:
    """解析 DriveApiBridge.run_threaded 最终 return 元组的长度。"""
    tree = ast.parse(_BRIDGE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run_threaded":
            returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)
                       and isinstance(n.value, ast.Tuple)]
            assert returns, "run_threaded 没有返回元组"
            # 取最后一个 return 元组（主返回路径）
            return len(returns[-1].value.elts)
    raise AssertionError("drive_api_bridge.py 中找不到 run_threaded")


def test_ctr_outputs_match_bridge_return_tuple():
    """ctr outputs 必须与 7 元组返回值一一对应，第 6 位是重连标志。"""
    outputs = _v_add_kwargs(_SOURCE, "ctr", after_lineno=_CTR_LINE).get("outputs")

    assert outputs == EXPECTED_CTR_OUTPUTS, (
        f"ctr outputs 应为 {EXPECTED_CTR_OUTPUTS}，实际为 {outputs}"
    )
    assert len(outputs) == _bridge_return_arity(), \
        "ctr outputs 数量必须与 DriveApiBridge.run_threaded 返回元组长度一致"


def test_reconnect_signal_reaches_gym_env():
    """重连输出键必须与 DonkeyGymEnv(cam) 的输入键完全一致。"""
    ctr_outputs = _v_add_kwargs(_SOURCE, "ctr", after_lineno=_CTR_LINE).get("outputs") or []
    cam_inputs = _v_add_kwargs(_SOURCE, "cam").get("inputs") or []

    assert 'reconnect_simulator' in ctr_outputs
    assert 'reconnect_simulator' in cam_inputs, \
        "cam(DonkeyGymEnv) 的 inputs 必须包含 reconnect_simulator"


def test_sim_connected_state_wired_to_telemetry():
    """sim/connected 必须有生产者（SimConnectionState）且接到 ctr 遥测输入末尾。"""
    tree = ast.parse(_SOURCE)
    all_outputs = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add"):
            continue
        for kw in node.keywords:
            if kw.arg != "outputs":
                continue
            try:
                all_outputs.extend(ast.literal_eval(kw.value))
            except (ValueError, SyntaxError):
                pass

    ctr_inputs = _v_add_kwargs(_SOURCE, "ctr", after_lineno=_CTR_LINE).get("inputs") or []

    assert 'sim/connected' in all_outputs, \
        "应有 part 输出 sim/connected（模拟器连接状态）"
    assert ctr_inputs and ctr_inputs[-1] == 'sim/connected', \
        "ctr inputs 末尾必须接 sim/connected（与 run_threaded 签名末位对齐）"

