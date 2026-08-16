# -*- coding: utf-8 -*-
"""Web UI 实例登记与复用（donkeycar/webui_instance.py，issue #127）的单元测试。

测试覆盖：
- 实例登记读写：write_instance 原子写入、read_instance 容错（缺失/损坏/
  字段类型不对）、remove_instance 的 only_pid 条件清除
- find_live_instance 判定链：登记缺失 → None；pid 不存活 → 清陈旧登记；
  后端/前端探测失败 → 清陈旧登记；探测全通 → 返回登记
- 车进程 PID 文件：read/write/remove 往返
- kill_previous_car_processes：cmdline 过滤只杀 manage.py drive 车进程，
  web 进程保留（mock /proc cmdline 与 os.kill）
- base.py Web.run 复用路径：已有存活实例时不再 Popen 新进程、直接返回；
  Drive.run 复用路径：已有实例时跳过 _launch_web_ui、车端环境变量指向
  已有后端端口（全部 mock，不起真实进程）
"""

import os
from unittest import mock

import pytest

from donkeycar import webui_instance
from donkeycar.webui_instance import (
    DRIVE_PID_FILE,
    WEBUI_INSTANCE_FILE,
    find_live_instance,
    kill_previous_car_processes,
    read_drive_pids,
    read_instance,
    remove_drive_pid_file,
    remove_instance,
    write_drive_pids,
    write_instance,
)


@pytest.fixture
def instance_file(tmp_path):
    """把实例登记文件与 PID 文件都指到临时目录。"""
    inst = tmp_path / "webui.json"
    pid = tmp_path / "drive.pid"
    pin = mock.patch.object(webui_instance, "WEBUI_INSTANCE_FILE", inst)
    pout = mock.patch.object(webui_instance, "DRIVE_PID_FILE", pid)
    with pin, pout:
        yield inst


# ===========================================================================
# 实例登记读写
# ===========================================================================

def test_write_and_read_instance(instance_file):
    payload = write_instance(8000, 5188, pid=123)
    assert payload == {
        "pid": 123,
        "backend_port": 8000,
        "frontend_port": 5188,
        "started_at": payload["started_at"],
    }
    assert read_instance(instance_file) == payload


def test_read_instance_missing_file(instance_file):
    assert read_instance(instance_file) is None


def test_read_instance_corrupt_file(instance_file):
    instance_file.write_text("{not json", encoding="utf-8")
    assert read_instance(instance_file) is None


def test_read_instance_bad_fields(instance_file):
    instance_file.write_text('{"pid": "x", "backend_port": 8000}', encoding="utf-8")
    assert read_instance(instance_file) is None


def test_remove_instance_unconditional(instance_file):
    write_instance(8000, 5188, pid=123)
    remove_instance()
    assert not instance_file.exists()


def test_remove_instance_only_pid_matches(instance_file):
    write_instance(8000, 5188, pid=123)
    remove_instance(only_pid=123)
    assert not instance_file.exists()


def test_remove_instance_only_pid_mismatch_keeps_file(instance_file):
    write_instance(8000, 5188, pid=123)
    # 他人后来覆盖写入了新登记（pid=456），旧持有者（123）退出时不得清除
    remove_instance(only_pid=456)
    assert read_instance(instance_file)["pid"] == 123


# ===========================================================================
# find_live_instance 判定链
# ===========================================================================

def _write_live(instance_file, pid=123):
    write_instance(8000, 5188, pid=pid, instance_file=instance_file)


def test_find_live_instance_no_file(instance_file):
    with mock.patch.object(webui_instance, "_pid_alive", return_value=True), \
         mock.patch.object(webui_instance, "_probe_http_ok", return_value=True):
        assert find_live_instance(instance_file) is None


def test_find_live_instance_dead_pid_clears_registration(instance_file):
    _write_live(instance_file, pid=123)
    with mock.patch.object(webui_instance, "_pid_alive", return_value=False):
        assert find_live_instance(instance_file) is None
    # 陈旧登记被清掉
    assert not instance_file.exists()


def test_find_live_instance_probe_fail_clears_registration(instance_file):
    _write_live(instance_file, pid=123)
    with mock.patch.object(webui_instance, "_pid_alive", return_value=True), \
         mock.patch.object(webui_instance, "_probe_http_ok", return_value=False):
        assert find_live_instance(instance_file) is None
    assert not instance_file.exists()


def test_find_live_instance_alive(instance_file):
    _write_live(instance_file, pid=123)
    probed = []

    def fake_probe(port, path="/", **kw):
        probed.append((port, path))
        return True

    with mock.patch.object(webui_instance, "_pid_alive", return_value=True), \
         mock.patch.object(webui_instance, "_probe_http_ok", side_effect=fake_probe):
        inst = find_live_instance(instance_file)
    assert inst == read_instance(instance_file)
    # 后端探测 /docs、前端探测 /
    assert (8000, "/docs") in probed
    assert (5188, "/") in probed


# ===========================================================================
# 车进程 PID 文件
# ===========================================================================

def test_drive_pid_file_roundtrip(instance_file):
    assert read_drive_pids() == []
    write_drive_pids([11, 22, 33])
    assert read_drive_pids() == [11, 22, 33]
    remove_drive_pid_file()
    assert read_drive_pids() == []


# ===========================================================================
# kill_previous_car_processes：只杀车进程
# ===========================================================================

def test_kill_only_car_processes(instance_file):
    pid_file = webui_instance.DRIVE_PID_FILE
    write_drive_pids([101, 202], pid_file=pid_file)

    cmdlines = {
        # 101 是 web 前/后端（保留），202 是车进程（杀掉）
        101: ["python", "-m", "uvicorn", "main:app"],
        202: ["python", "manage.py", "drive"],
    }
    killed = []

    def fake_cmdline(pid):
        return cmdlines.get(pid)

    def fake_kill(pid, sig):
        killed.append((pid, sig))

    with mock.patch.object(webui_instance, "_process_cmdline",
                           side_effect=fake_cmdline), \
         mock.patch.object(os, "kill", side_effect=fake_kill):
        kill_previous_car_processes(pid_file=pid_file)

    # 只有车进程 202 收到 SIGTERM/SIGKILL，web 进程 101 保留
    assert killed and all(pid == 202 for pid, _ in killed)
    # PID 文件被清理
    assert not pid_file.exists()


def test_kill_unreadable_cmdline_falls_back_to_kill_all(instance_file):
    """非 Linux / 无 /proc 时退化为按 PID 全杀（与旧行为一致）。"""
    pid_file = webui_instance.DRIVE_PID_FILE
    write_drive_pids([101, 202], pid_file=pid_file)
    killed = []

    with mock.patch.object(webui_instance, "_process_cmdline",
                           return_value=None), \
         mock.patch.object(os, "kill",
                           side_effect=lambda pid, sig: killed.append(pid)), \
         mock.patch.object(webui_instance, "threading"):
        kill_previous_car_processes(pid_file=pid_file)

    assert sorted(set(killed)) == [101, 202]


# ===========================================================================
# base.py Web.run / Drive.run 复用路径
# ===========================================================================

class _Args:
    path = "/nonexistent/web_ui"
    frontend_port = 5188
    backend_port = 8000
    backend_host = "127.0.0.1"
    install_deps = False
    open = False
    route = "/"
    debug = False
    # Drive 额外参数
    car = None
    model = None
    type = None
    js = False


def test_web_run_reuses_live_instance(instance_file, capsys):
    from donkeycar.management.base import Web

    _write_live(instance_file, pid=123)
    with mock.patch("donkeycar.management.base.find_live_instance",
                    return_value=read_instance(instance_file)), \
         mock.patch.object(Web, "_launch_web_ui") as launch_mock:
        Web().run([])
    # 复用：不拉起新的前后端进程
    launch_mock.assert_not_called()
    assert "复用已有实例" in capsys.readouterr().out


def test_web_run_launches_and_registers_when_no_instance(instance_file):
    from donkeycar.management.base import Web

    class _FakeProc:
        pid = 555

        def poll(self):
            return 0  # 立即退出，让监督循环结束

    launched = {}
    registrations = []
    real_write = webui_instance.write_instance

    def spy_write(backend_port, frontend_port, pid=None, instance_file=None):
        registrations.append((backend_port, frontend_port, pid))
        return real_write(backend_port, frontend_port, pid=pid,
                          instance_file=instance_file)

    def fake_launch(self, args):
        launched["called"] = True
        return _FakeProc(), _FakeProc(), 5188, 8000, "http://localhost:5188/"

    with mock.patch("donkeycar.management.base.find_live_instance",
                    return_value=None), \
         mock.patch.object(Web, "_launch_web_ui", fake_launch), \
         mock.patch.object(Web, "_wait_for_port_ready", return_value=True), \
         mock.patch.object(Web, "_supervise_processes"), \
         mock.patch.object(Web, "_terminate_process"), \
         mock.patch("donkeycar.management.base.write_instance",
                    side_effect=spy_write):
        Web().run([])

    assert launched.get("called") is True
    # 启动成功后登记了实例（端口与 pid），run 退出时 finally 清除属于
    # 本进程的登记，因此用 spy 验证写入内容
    assert registrations == [(8000, 5188, os.getpid())]
    assert not instance_file.exists()


def test_drive_run_reuses_live_instance(instance_file, capsys, tmp_path):
    from donkeycar.management.base import Drive

    # 车目录需要 manage.py
    (tmp_path / "manage.py").write_text("# fake\n", encoding="utf-8")

    _write_live(instance_file, pid=123)
    inst = read_instance(instance_file)

    class _FakeProc:
        pid = 777

        def poll(self):
            return 0

    popen_cmds = []

    def fake_popen(cmd, **kw):
        popen_cmds.append(list(cmd))
        return _FakeProc()

    with mock.patch("donkeycar.management.base.find_live_instance",
                    return_value=inst), \
         mock.patch.object(Drive, "_launch_web_ui") as launch_mock, \
         mock.patch("donkeycar.management.base.kill_previous_car_processes"), \
         mock.patch("subprocess.Popen", side_effect=fake_popen), \
         mock.patch.object(Drive, "_supervise_processes"), \
         mock.patch.object(Drive, "_terminate_process"):
        with mock.patch.object(os, "getcwd", return_value=str(tmp_path)):
            Drive().run([])

    # 复用：不新起 Web UI
    launch_mock.assert_not_called()
    # 只起了车进程
    assert len(popen_cmds) == 1
    assert popen_cmds[0][1:3] == ["manage.py", "drive"]
    out = capsys.readouterr().out
    assert "复用已有实例" in out
    assert "8000" in out


def test_drive_run_env_points_to_reused_backend(instance_file, tmp_path):
    """复用实例时车端 DRIVE_API_SERVER_URL 应指向已有后端端口。"""
    from donkeycar.management.base import Drive

    (tmp_path / "manage.py").write_text("# fake\n", encoding="utf-8")
    _write_live(instance_file, pid=123)
    inst = read_instance(instance_file)

    class _FakeProc:
        pid = 777

        def poll(self):
            return 0

    captured_env = {}
    pid_writes = []

    def fake_popen(cmd, **kw):
        if "manage.py" in cmd:
            captured_env.update(kw.get("env") or {})
        return _FakeProc()

    def spy_write_pids(pids, pid_file=None):
        pid_writes.append(list(pids))

    with mock.patch("donkeycar.management.base.find_live_instance",
                    return_value=inst), \
         mock.patch.object(Drive, "_launch_web_ui"), \
         mock.patch("donkeycar.management.base.kill_previous_car_processes"), \
         mock.patch("subprocess.Popen", side_effect=fake_popen), \
         mock.patch("donkeycar.management.base.write_drive_pids",
                    side_effect=spy_write_pids), \
         mock.patch.object(Drive, "_supervise_processes"), \
         mock.patch.object(Drive, "_terminate_process"), \
         mock.patch.object(os, "getcwd", return_value=str(tmp_path)):
        Drive().run([])

    assert captured_env.get("DRIVE_API_SERVER_URL") == \
        "ws://127.0.0.1:8000/api/drive/ws"
    # 复用时 PID 文件只记车进程（run 退出时 finally 会清文件，故捕获写入）
    assert pid_writes == [[777]]
