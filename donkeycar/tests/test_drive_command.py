"""`donkey drive` 命令的单元测试。

阶段1.2：验证 donkey drive 一键拉起 web_ui 前后端 + 本机 manage.py drive，
并自动注入 DRIVE_API_SERVER_URL。
"""
import sys

import pytest

from donkeycar.management.base import Drive


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------

def test_drive_command_parses_car_options():
    args = Drive().parse_args(
        ["--car", "/tmp/mycar", "--model", "m.h5", "--type", "linear", "--js"]
    )

    assert args.car == "/tmp/mycar"
    assert args.model == "m.h5"
    assert args.type == "linear"
    assert args.js is True


def test_drive_command_defaults_route_to_drive_page():
    args = Drive().parse_args([])

    # 默认打开 drive 页面
    assert args.route == "/drive"


# ---------------------------------------------------------------------------
# 车辆子进程命令构造（纯函数，无需启动进程）
# ---------------------------------------------------------------------------

def test_build_car_command_includes_manage_py_drive():
    args = Drive().parse_args([])

    cmd = Drive()._build_car_command(args)

    assert cmd[:3] == [sys.executable, "manage.py", "drive"]


def test_build_car_command_passes_model_and_type():
    args = Drive().parse_args(["--model", "m.h5", "--type", "linear"])

    cmd = Drive()._build_car_command(args)

    assert "--model" in cmd and "m.h5" in cmd
    assert "--type" in cmd and "linear" in cmd


def test_build_car_command_passes_js_flag():
    args = Drive().parse_args(["--js"])

    cmd = Drive()._build_car_command(args)

    assert "--js" in cmd


# ---------------------------------------------------------------------------
# 环境变量注入
# ---------------------------------------------------------------------------

def test_build_car_env_injects_drive_api_server_url():
    env = Drive()._build_car_env(backend_port=8000)

    assert env["DRIVE_API_SERVER_URL"] == "ws://127.0.0.1:8000/api/drive/ws"


def test_build_car_env_uses_actual_backend_port():
    env = Drive()._build_car_env(backend_port=8123)

    assert env["DRIVE_API_SERVER_URL"] == "ws://127.0.0.1:8123/api/drive/ws"


# ---------------------------------------------------------------------------
# 端到端编排：三进程拉起 + env 注入 + 信号终止
# ---------------------------------------------------------------------------

class _FakeProcess:
    """模拟子进程：按预设返回码序列推进 poll()。"""

    def __init__(self, return_codes):
        self.return_codes = iter(return_codes)
        self.returncode = None

    def poll(self):
        try:
            self.returncode = next(self.return_codes)
        except StopIteration:
            pass
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode or 0


def _setup_web_ui_tree(tmp_path):
    """构造最小 web_ui 目录树与车目录。"""
    web_ui = tmp_path / "web_ui"
    (web_ui / "frontend").mkdir(parents=True)
    (web_ui / "backend").mkdir(parents=True)
    car_dir = tmp_path / "mycar"
    car_dir.mkdir()
    (car_dir / "manage.py").write_text("# stub")
    return web_ui, car_dir


def test_drive_run_spawns_three_processes_and_injects_env(monkeypatch, tmp_path):
    web_ui, car_dir = _setup_web_ui_tree(tmp_path)
    popen_calls = []

    # backend / frontend / car 三个进程；backend 在第二次 poll 时退出以结束监督循环
    processes = [
        _FakeProcess([None, None, None]),  # backend
        _FakeProcess([None, None, None]),  # frontend
        _FakeProcess([None, 0]),           # car 先退出 → 触发终止
    ]

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        return processes.pop(0)

    monkeypatch.setattr("donkeycar.management.base.shutil.which", lambda name: "npm")
    monkeypatch.setattr(Drive, "_choose_available_port", lambda self, host, p: p)
    monkeypatch.setattr(Drive, "_wait_for_backend_ready", lambda self, port, timeout=30.0: True)
    monkeypatch.setattr("donkeycar.management.base.subprocess.Popen", fake_popen)
    monkeypatch.setattr("donkeycar.management.base.webbrowser.open", lambda _url: None)
    monkeypatch.setattr("donkeycar.management.base.time.sleep", lambda _s: None)

    with pytest.raises(SystemExit):
        Drive().run([
            "--path", str(web_ui),
            "--car", str(car_dir),
            "--backend-port", "8000",
        ])

    # 应拉起三个子进程：uvicorn 后端、npm 前端、manage.py drive
    assert len(popen_calls) == 3

    car_cmd, car_kwargs = popen_calls[2]
    assert car_cmd[:3] == [sys.executable, "manage.py", "drive"]
    assert car_kwargs["cwd"] == str(car_dir)
    assert car_kwargs["env"]["DRIVE_API_SERVER_URL"] == "ws://127.0.0.1:8000/api/drive/ws"


def test_drive_run_rejects_missing_manage_py(monkeypatch, tmp_path):
    web_ui, car_dir = _setup_web_ui_tree(tmp_path)
    # 删除 manage.py，使其不像一个车目录
    (car_dir / "manage.py").unlink()

    monkeypatch.setattr("donkeycar.management.base.shutil.which", lambda name: "npm")
    monkeypatch.setattr(Drive, "_choose_available_port", lambda self, host, p: p)

    with pytest.raises(SystemExit):
        Drive().run(["--path", str(web_ui), "--car", str(car_dir)])
