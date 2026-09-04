import queue
import sys
from pathlib import Path
from unittest.mock import Mock, patch

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import mypc_probe


class FakeSsh:
    def close(self):
        pass


def _echo_executable(command):
    """Pretend the invoked interpreter resolves sys.executable to itself."""
    return (0, command.split(" -c ", 1)[0] + "\n", "")


def _donkeycar_only_under(path_fragment):
    """find_spec('donkeycar') succeeds only for interpreters under a path."""
    def _run(command):
        return (0, "", "") if path_fragment in command else (1, "", "")
    return _run


def _make_dispatcher(commands, calls=None):
    """Return a fake _run_remote that dispatches on the command string
    (same pattern as test_trainer_mypc_probe.py)."""
    def _run(ssh, command, timeout=20):
        if calls is not None:
            calls.append(command)
        for key, result in commands.items():
            if key in command:
                return result(command) if callable(result) else result
        return (0, "", "")
    return _run


# ----------------------------------------------------------------------
# find_donkeycar_python
# ----------------------------------------------------------------------
def test_find_donkeycar_python_uses_configured_first():
    calls = []
    cmds = {
        "/custom/python -c \"import sys; print(sys.executable)\"": (0, "/custom/python\n", ""),
        "find_spec('donkeycar')": (0, "", ""),
    }
    with patch.object(mypc_probe, "_run_remote", side_effect=_make_dispatcher(cmds, calls)):
        found = mypc_probe.find_donkeycar_python(FakeSsh(), "/custom/python")

    assert found == "/custom/python"
    # 配置路径排在候选首位，找到即返回（发现层同 _detect_python 一样先行执行）


def test_find_donkeycar_python_falls_back_to_discovery():
    # 配置路径不存在（exit 1），发现层（常见根目录 glob）给出真实安装位置
    cmds = {
        "~/miniconda3/envs/donkey/bin/python": (1, "", "no such file or directory"),
        "conda env list": (0, "", ""),
        "for b in": (0, "/opt/miniconda3/envs/donkey/bin/python3\n", ""),
        "command -v donkey": (0, "", ""),
        "import sys; print(sys.executable)": _echo_executable,
        "find_spec('donkeycar')": _donkeycar_only_under("/opt/miniconda3"),
    }
    with patch.object(mypc_probe, "_run_remote", side_effect=_make_dispatcher(cmds)):
        found = mypc_probe.find_donkeycar_python(
            FakeSsh(), "~/miniconda3/envs/donkey/bin/python")

    assert found == "/opt/miniconda3/envs/donkey/bin/python3"


def test_find_donkeycar_python_returns_empty_when_nothing_found():
    def _run(ssh, command, timeout=20):
        if "import sys; print(sys.executable)" in command:
            return (1, "", "no such file or directory")
        return (0, "", "")  # 发现层全部空手而归

    with patch.object(mypc_probe, "_run_remote", side_effect=_run):
        found = mypc_probe.find_donkeycar_python(FakeSsh(), "/missing/python")

    assert found == ""


# ----------------------------------------------------------------------
# WebOnlineTrainer._ensure_remote_python
# ----------------------------------------------------------------------
def _make_trainer(tmp_path, monkeypatch, log_queue=None):
    """chdir 到 tmp_path 后用相对 conf 名让 OnlineTrainer.__init__ 自建默认
    conf（参照 test_web_online_trainer_run_converts_systemexit_to_real_reason）。"""
    from web_online_trainer import WebOnlineTrainer

    monkeypatch.chdir(tmp_path)
    trainer = WebOnlineTrainer(config_file="train_test.conf", log_queue=log_queue)
    trainer.ssh_client = Mock()
    return trainer


def _drain(log_queue):
    """取空队列，返回事件 dict 列表。"""
    events = []
    while True:
        try:
            events.append(log_queue.get_nowait())
        except queue.Empty:
            return events


def test_ensure_remote_python_corrects_config(tmp_path, monkeypatch):
    log_queue = queue.Queue()
    trainer = _make_trainer(tmp_path, monkeypatch, log_queue)
    # 让 ~ 展开可断言：默认配置 ~/miniconda3/... 展开后仍与 found 不同
    monkeypatch.setattr(trainer, "_resolve_remote_path", lambda p: p.replace("~", "/home/u"))
    monkeypatch.setattr(
        mypc_probe, "find_donkeycar_python",
        lambda ssh, configured="": "/opt/miniconda3/envs/donkey/bin/python3")

    trainer._ensure_remote_python()

    assert trainer.get_config_value("python_path") == "/opt/miniconda3/envs/donkey/bin/python3"
    lines = [e["line"] for e in _drain(log_queue)]
    assert any("已自动修正远程 Python 路径" in line for line in lines)


def test_ensure_remote_python_keeps_config_when_not_found(tmp_path, monkeypatch):
    log_queue = queue.Queue()
    trainer = _make_trainer(tmp_path, monkeypatch, log_queue)
    before = trainer.get_config_value("python_path")
    monkeypatch.setattr(mypc_probe, "find_donkeycar_python", lambda ssh, configured="": "")

    trainer._ensure_remote_python()

    assert trainer.get_config_value("python_path") == before
    events = _drain(log_queue)
    assert any(e["level"] == "warning" and "未在远程找到" in e["line"] for e in events)


def test_ensure_remote_python_swallows_exceptions(tmp_path, monkeypatch):
    log_queue = queue.Queue()
    trainer = _make_trainer(tmp_path, monkeypatch, log_queue)
    before = trainer.get_config_value("python_path")

    def _boom(ssh, configured=""):
        raise RuntimeError("ssh exploded")

    monkeypatch.setattr(mypc_probe, "find_donkeycar_python", _boom)

    trainer._ensure_remote_python()  # 不得向外抛

    assert trainer.get_config_value("python_path") == before
    events = _drain(log_queue)
    assert any(e["level"] == "warning" and "auto-detection failed" in e["line"]
               for e in events)
