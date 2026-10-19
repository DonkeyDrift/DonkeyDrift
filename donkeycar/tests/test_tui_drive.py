import sys

import pytest

from donkeycar.management import tui


@pytest.fixture(autouse=True)
def _isolate_process_registry(monkeypatch):
    """隔离进程登记副作用，默认走"无存活实例"路径。

    实例登记与车进程 PID 文件在本机真实 home 目录（~/.donkeycar/），
    测试若不隔离：会误杀正在运行的真实车进程、误删/误写 PID 记录，
    且本机有存活 Web UI 实例时"新起实例"断言会被复用路径顶掉。
    需要复用路径的用例自行再 patch tui.find_live_instance。
    """
    monkeypatch.setattr(tui, "find_live_instance", lambda: None)
    monkeypatch.setattr(tui, "kill_previous_car_processes", lambda: None)
    monkeypatch.setattr(tui, "takeover_car_processes", lambda: None)
    monkeypatch.setattr(tui, "write_drive_pids", lambda pids: None)
    monkeypatch.setattr(tui, "remove_drive_pid_file", lambda: None)
    # 局域网探测在测试环境不确定，默认固定 localhost；LAN 行为有专测
    monkeypatch.setattr(tui, "_lan_host", lambda: "localhost")
    # Drive 流程不应再出现交互 Confirm（时延探针提问已移除，开关走 env）；
    # 此 patch 是回归护栏：若有人加回提问，测试环境也不会卡在读 stdin
    monkeypatch.setattr(tui.Confirm, "ask", lambda *args, **kwargs: False)


class FakeProcess:
    returncode = 0
    pid = 12345

    def __init__(self):
        self.terminated = False
        self.killed = False

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def send_signal(self, signal_value):
        self.terminated = True

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class ProcessingStreamWithoutFileno:
    def write(self, value):
        return len(value)

    def flush(self):
        pass


def test_drive_command_opens_web_console_drive_page(monkeypatch, tmp_path):
    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "myconfig.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cmd = tui.DriveCommand().get_command_line({})

    assert cmd[:2] == ["donkey", "web"]
    assert "--install-deps" in cmd
    assert "--path" in cmd
    assert "--open" in cmd
    assert cmd[cmd.index("--route") + 1] == "/drive"
    assert "manage.py" not in cmd


def test_drive_command_starts_web_console_and_car_process(monkeypatch, tmp_path):
    popen_calls = []
    prompts = iter(["y", ""])

    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "myconfig.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(tui.console, "clear", lambda: None)
    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: next(prompts))
    monkeypatch.setattr(tui.DriveCommand, "choose_available_backend_port", lambda self, preferred_port=8100: 8000)

    def fake_popen(cmd_list, **kwargs):
        popen_calls.append((cmd_list, kwargs))
        return FakeProcess()

    monkeypatch.setattr(tui.subprocess, "Popen", fake_popen)

    tui.DriveCommand().execute()

    assert len(popen_calls) == 2
    web_cmd, web_kwargs = popen_calls[0]
    car_cmd, car_kwargs = popen_calls[1]

    assert web_cmd[:2] == ["donkey", "web"]
    assert "--install-deps" in web_cmd
    assert "--route" in web_cmd
    assert web_cmd[web_cmd.index("--route") + 1] == "/drive"

    assert car_cmd == [sys.executable, "manage.py", "drive"]
    assert car_kwargs["cwd"] == tmp_path
    assert car_kwargs["env"]["DRIVE_API_SERVER_URL"].endswith(":8000/api/drive/ws")
    assert all("DRIVE_API_SERVER_URL=" not in str(cmd) for cmd, _ in popen_calls)


def test_drive_command_sets_car_url_to_chosen_backend_port(monkeypatch, tmp_path):
    popen_calls = []
    prompts = iter(["y", ""])

    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "myconfig.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(tui.console, "clear", lambda: None)
    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: next(prompts))
    monkeypatch.setattr(tui.DriveCommand, "choose_available_backend_port", lambda self, preferred_port=8100: 8001)

    def fake_popen(cmd_list, **kwargs):
        popen_calls.append((cmd_list, kwargs))
        return FakeProcess()

    monkeypatch.setattr(tui.subprocess, "Popen", fake_popen)

    tui.DriveCommand().execute()

    web_cmd, _ = popen_calls[0]
    _, car_kwargs = popen_calls[1]

    assert "--backend-port" in web_cmd
    assert "--install-deps" in web_cmd
    assert web_cmd[web_cmd.index("--backend-port") + 1] == "8001"
    assert car_kwargs["env"]["DRIVE_API_SERVER_URL"] == "ws://localhost:8001/api/drive/ws"


def test_drive_command_uses_full_server_url_environment_override(monkeypatch):
    monkeypatch.setenv("DRIVE_API_SERVER_URL", "ws://192.168.3.96:8000/api/drive/ws")

    assert tui.DriveCommand().get_drive_api_server_url() == "ws://192.168.3.96:8000/api/drive/ws"


def test_drive_command_uses_public_host_environment_override(monkeypatch):
    monkeypatch.delenv("DRIVE_API_SERVER_URL", raising=False)
    monkeypatch.setenv("DRIVE_API_PUBLIC_HOST", "192.168.3.96")

    assert tui.DriveCommand().get_drive_api_server_url() == "ws://192.168.3.96:8100/api/drive/ws"


def test_drive_command_does_not_use_sim_host_as_backend_host(monkeypatch):
    monkeypatch.delenv("DRIVE_API_SERVER_URL", raising=False)
    monkeypatch.delenv("DRIVE_API_PUBLIC_HOST", raising=False)

    assert tui.DriveCommand().get_drive_api_server_url() == "ws://localhost:8100/api/drive/ws"


def test_drive_command_defaults_to_localhost(monkeypatch):
    monkeypatch.delenv("DRIVE_API_SERVER_URL", raising=False)
    monkeypatch.delenv("DRIVE_API_PUBLIC_HOST", raising=False)

    assert tui.DriveCommand().get_drive_api_server_url() == "ws://localhost:8100/api/drive/ws"


def test_drive_command_inherits_stdio_without_requiring_fileno(monkeypatch, tmp_path):
    popen_calls = []
    prompts = iter(["y", ""])

    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "myconfig.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(tui.console, "clear", lambda: None)
    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: next(prompts))
    monkeypatch.setattr(tui.sys, "stdout", ProcessingStreamWithoutFileno())
    monkeypatch.setattr(tui.sys, "stderr", ProcessingStreamWithoutFileno())

    def fake_popen(cmd_list, **kwargs):
        popen_calls.append((cmd_list, kwargs))
        return FakeProcess()

    monkeypatch.setattr(tui.subprocess, "Popen", fake_popen)

    tui.DriveCommand().execute()

    assert len(popen_calls) == 2
    for _, popen_kwargs in popen_calls:
        assert popen_kwargs.get("stdout") is None
        assert popen_kwargs.get("stderr") is None


def test_drive_command_does_not_start_without_manage_py(monkeypatch, tmp_path):
    popen_calls = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tui.console, "clear", lambda: None)
    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: "")
    monkeypatch.setattr(tui.subprocess, "Popen", lambda *args, **kwargs: popen_calls.append((args, kwargs)))

    tui.DriveCommand().execute()

    # 无 manage.py：车进程（manage.py drive）绝不启动；Web Console 属
    # 一键启动范围，默认模式会正常拉起
    assert not any("manage.py" in cmd for cmd, _ in popen_calls)


class PollingProcess(FakeProcess):
    def __init__(self, states):
        super().__init__()
        self.states = list(states)

    def poll(self):
        if len(self.states) > 1:
            return self.states.pop(0)
        return self.states[0]


def test_drive_command_keeps_web_console_when_car_process_exits(monkeypatch):
    web_process = PollingProcess([None, 0])
    car_process = PollingProcess([1, 1])

    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(tui.time, "sleep", lambda *args, **kwargs: None)

    tui.DriveCommand().monitor_processes(web_process, car_process)

    assert web_process.terminated is False
    assert web_process.killed is False


def test_drive_command_reusing_live_instance_opens_browser(monkeypatch, tmp_path):
    """复用存活实例时：只起车进程，并由 TUI 打开实例前端端口的 Drive 页。"""
    popen_calls = []
    opened_urls = []
    prompts = iter(["y", ""])

    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "myconfig.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    inst = {"pid": 4242, "backend_port": 8000, "frontend_port": 8000}
    monkeypatch.setattr(tui, "find_live_instance", lambda: dict(inst))
    monkeypatch.setattr(tui.console, "clear", lambda: None)
    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: next(prompts))
    monkeypatch.setattr(tui.webbrowser, "open", opened_urls.append)
    monkeypatch.delenv("DRIVE_API_SERVER_URL", raising=False)
    monkeypatch.delenv("DRIVE_API_PUBLIC_HOST", raising=False)
    monkeypatch.delenv("DRIVE_WEB_CONSOLE_URL", raising=False)

    def fake_popen(cmd_list, **kwargs):
        popen_calls.append((cmd_list, kwargs))
        return FakeProcess()

    monkeypatch.setattr(tui.subprocess, "Popen", fake_popen)
    # 复用路径 web_process 为 None，monitor 循环只认 ESC，测试里直接短路
    monkeypatch.setattr(tui.DriveCommand, "monitor_processes", lambda self, w, c: None)

    tui.DriveCommand().execute()

    assert len(popen_calls) == 1
    car_cmd, car_kwargs = popen_calls[0]
    assert car_cmd == [sys.executable, "manage.py", "drive"]
    assert car_kwargs["env"]["DRIVE_API_SERVER_URL"] == "ws://localhost:8000/api/drive/ws"
    assert car_kwargs["env"]["DRIVE_WEB_CONSOLE_URL"] == "http://localhost:8000"
    assert opened_urls == ["http://localhost:8000/#/drive"]


def test_drive_command_new_instance_leaves_browser_to_web_open(monkeypatch, tmp_path):
    """新起实例时：浏览器由 `donkey web --open` 打开，TUI 不重复打开。"""
    popen_calls = []
    opened_urls = []
    prompts = iter(["y", ""])

    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "myconfig.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(tui.console, "clear", lambda: None)
    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: next(prompts))
    monkeypatch.setattr(tui.DriveCommand, "choose_available_backend_port", lambda self, preferred_port=8100: 8000)
    monkeypatch.setattr(tui.webbrowser, "open", opened_urls.append)
    monkeypatch.delenv("DRIVE_WEB_CONSOLE_URL", raising=False)

    def fake_popen(cmd_list, **kwargs):
        popen_calls.append((cmd_list, kwargs))
        return FakeProcess()

    monkeypatch.setattr(tui.subprocess, "Popen", fake_popen)

    tui.DriveCommand().execute()

    assert len(popen_calls) == 2
    _, car_kwargs = popen_calls[1]
    assert opened_urls == []
    # 生产模式前端由后端托管，提示 URL 端口即后端端口
    assert car_kwargs["env"]["DRIVE_WEB_CONSOLE_URL"] == "http://localhost:8000"


def test_drive_command_respects_user_drive_web_console_url(monkeypatch, tmp_path):
    """用户已显式设置 DRIVE_WEB_CONSOLE_URL 时，车进程环境变量不被覆盖。"""
    popen_calls = []
    prompts = iter(["y", ""])

    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "myconfig.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    inst = {"pid": 4242, "backend_port": 8000, "frontend_port": 8000}
    monkeypatch.setattr(tui, "find_live_instance", lambda: dict(inst))
    monkeypatch.setattr(tui.console, "clear", lambda: None)
    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: next(prompts))
    monkeypatch.setattr(tui.webbrowser, "open", lambda _url: None)
    monkeypatch.setenv("DRIVE_WEB_CONSOLE_URL", "http://192.0.2.10:8000")

    def fake_popen(cmd_list, **kwargs):
        popen_calls.append((cmd_list, kwargs))
        return FakeProcess()

    monkeypatch.setattr(tui.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(tui.DriveCommand, "monitor_processes", lambda self, w, c: None)

    tui.DriveCommand().execute()

    _, car_kwargs = popen_calls[0]
    assert car_kwargs["env"]["DRIVE_WEB_CONSOLE_URL"] == "http://192.0.2.10:8000"


def test_drive_command_uses_lan_ip_for_remote_terminal(monkeypatch, tmp_path):
    """局域网探测有结果时：Drive 页面地址与车进程提示 URL 都用局域网 IP。"""
    popen_calls = []
    opened_urls = []
    prompts = iter(["y", ""])

    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "myconfig.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    inst = {"pid": 4242, "backend_port": 8000, "frontend_port": 8000}
    monkeypatch.setattr(tui, "find_live_instance", lambda: dict(inst))
    monkeypatch.setattr(tui, "_lan_host", lambda: "192.168.3.103")
    monkeypatch.setattr(tui.console, "clear", lambda: None)
    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: next(prompts))
    monkeypatch.setattr(tui.webbrowser, "open", opened_urls.append)
    monkeypatch.delenv("DRIVE_API_SERVER_URL", raising=False)
    monkeypatch.delenv("DRIVE_API_PUBLIC_HOST", raising=False)
    monkeypatch.delenv("DRIVE_WEB_CONSOLE_URL", raising=False)

    def fake_popen(cmd_list, **kwargs):
        popen_calls.append((cmd_list, kwargs))
        return FakeProcess()

    monkeypatch.setattr(tui.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(tui.DriveCommand, "monitor_processes", lambda self, w, c: None)

    tui.DriveCommand().execute()

    _, car_kwargs = popen_calls[0]
    assert car_kwargs["env"]["DRIVE_WEB_CONSOLE_URL"] == "http://192.168.3.103:8000"
    assert opened_urls == ["http://192.168.3.103:8000/#/drive"]


def test_drive_command_takeover_kills_other_car_processes(monkeypatch, tmp_path):
    """执行前调用接管清理（takeover_car_processes），杀掉其它在跑车进程。"""
    popen_calls = []
    prompts = iter(["y", ""])
    takeover_calls = []

    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "myconfig.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(tui.console, "clear", lambda: None)
    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: next(prompts))
    monkeypatch.setattr(
        tui, "takeover_car_processes",
        lambda: takeover_calls.append("called") or [171399])

    def fake_popen(cmd_list, **kwargs):
        popen_calls.append((cmd_list, kwargs))
        return FakeProcess()

    monkeypatch.setattr(tui.subprocess, "Popen", fake_popen)

    tui.DriveCommand().execute()

    assert takeover_calls == ["called"]


# ---------------- WebRTC 时延探针集成（TUI 不再提问，开关走 env） ----------------

def _drive_with_probe_env(monkeypatch, tmp_path, probe_env):
    popen_calls = []
    prompts = iter(["y", ""])

    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "myconfig.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(tui.console, "clear", lambda: None)
    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: next(prompts))
    if probe_env is None:
        monkeypatch.delenv("DRIVE_WEBRTC_LATENCY_PROBE", raising=False)
    else:
        monkeypatch.setenv("DRIVE_WEBRTC_LATENCY_PROBE", probe_env)
    monkeypatch.setattr(
        tui.DriveCommand, "choose_available_backend_port",
        lambda self, preferred_port=8100: 8000)

    def fake_popen(cmd_list, **kwargs):
        popen_calls.append((cmd_list, kwargs))
        return FakeProcess()

    monkeypatch.setattr(tui.subprocess, "Popen", fake_popen)
    tui.DriveCommand().execute()
    return popen_calls


def test_drive_command_probe_env_on_sets_env_one(monkeypatch, tmp_path):
    popen_calls = _drive_with_probe_env(monkeypatch, tmp_path, "1")
    car_kwargs = popen_calls[1][1]
    assert car_kwargs["env"]["DRIVE_WEBRTC_LATENCY_PROBE"] == "1"


def test_drive_command_probe_env_true_normalized(monkeypatch, tmp_path):
    popen_calls = _drive_with_probe_env(monkeypatch, tmp_path, "true")
    car_kwargs = popen_calls[1][1]
    assert car_kwargs["env"]["DRIVE_WEBRTC_LATENCY_PROBE"] == "1"


def test_drive_command_probe_env_unset_sets_env_zero(monkeypatch, tmp_path):
    # 未显式开启时归一化置 0：车端子进程拿到的取值确定，不靠继承链上的空缺
    popen_calls = _drive_with_probe_env(monkeypatch, tmp_path, None)
    car_kwargs = popen_calls[1][1]
    assert car_kwargs["env"]["DRIVE_WEBRTC_LATENCY_PROBE"] == "0"


def test_get_preview_command_probe_env():
    cmd = tui.DriveCommand()
    base = cmd.get_preview_command(
        ["donkey", "web"], ["python", "manage.py", "drive"],
        "ws://localhost:8000/api/drive/ws")
    on = cmd.get_preview_command(
        ["donkey", "web"], ["python", "manage.py", "drive"],
        "ws://localhost:8000/api/drive/ws", probe=True)
    assert "DRIVE_WEBRTC_LATENCY_PROBE" not in base
    assert "DRIVE_WEBRTC_LATENCY_PROBE=1" in on
    # 前缀顺序：URL 在前，探针 env 跟随，随后是车命令本身
    assert on.index("DRIVE_API_SERVER_URL=") < on.index("DRIVE_WEBRTC_LATENCY_PROBE=1")
    assert "manage.py" in on


# ---------------- 一键启动与 -v/--verbose 确认 ----------------

def _run_drive(monkeypatch, tmp_path, answers, verbose=False):
    """跑一次 Drive 流程，answers 依序喂给 Prompt.ask。

    默认（非 verbose）只剩"按回车键返回菜单"一次交互；verbose=True 时
    首个应答是执行确认页的 y/n/c。返回 (popen_calls, asks)。
    """
    popen_calls = []
    asks = []

    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "myconfig.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(tui.console, "clear", lambda: None)
    monkeypatch.setattr(tui.console, "print", lambda *args, **kwargs: None)
    answers = iter(answers)
    monkeypatch.setattr(
        tui.Prompt, "ask",
        lambda *args, **kwargs: asks.append(args[0] if args else "")
        or next(answers))
    # 取消路径有 time.sleep(1)，测试里跳过
    monkeypatch.setattr(tui.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        tui.DriveCommand, "choose_available_backend_port",
        lambda self, preferred_port=8100: 8000)

    def fake_popen(cmd_list, **kwargs):
        popen_calls.append((cmd_list, kwargs))
        return FakeProcess()

    monkeypatch.setattr(tui.subprocess, "Popen", fake_popen)
    tui.DriveCommand(verbose=verbose).execute()
    return popen_calls, asks


def test_drive_command_default_launches_without_confirm(monkeypatch, tmp_path):
    # 默认一键启动：无命令预览/确认交互，选中即拉起 web + 车进程
    popen_calls, asks = _run_drive(monkeypatch, tmp_path, [""])
    assert len(asks) == 1
    assert "按回车" in asks[0]
    assert len(popen_calls) == 2


def test_drive_command_verbose_confirms_before_launch(monkeypatch, tmp_path):
    popen_calls, asks = _run_drive(
        monkeypatch, tmp_path, ["y", ""], verbose=True)
    assert len(asks) == 2
    assert "请选择操作" in asks[0]
    assert len(popen_calls) == 2


def test_drive_command_verbose_cancel_skips_launch(monkeypatch, tmp_path):
    popen_calls, asks = _run_drive(
        monkeypatch, tmp_path, ["n"], verbose=True)
    assert "请选择操作" in asks[0]
    assert popen_calls == []


def test_tui_cli_verbose_flag_and_menu_wiring():
    from donkeycar.management.base import Tui

    assert Tui().parse_args(["-v"]).verbose is True
    assert Tui().parse_args(["--verbose"]).verbose is True
    assert Tui().parse_args([]).verbose is False

    # verbose 从 CLI 一路传到菜单里的 DriveCommand
    assert tui.MenuSystem(verbose=True).commands["驾驶"][0].verbose is True
    assert tui.MenuSystem().commands["驾驶"][0].verbose is False
