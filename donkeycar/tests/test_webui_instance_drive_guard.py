# -*- coding: utf-8 -*-
"""drive 单实例守护（acquire/release_drive_instance_lock）测试。"""

import json
import os
import subprocess
import sys
import time

import pytest

from donkeycar.webui_instance import (
    DriveAlreadyRunning,
    _proc_start_time,
    acquire_drive_instance_lock,
    release_drive_instance_lock,
)


def test_acquire_writes_record_and_release_removes(tmp_path):
    f = tmp_path / "drive_instance.json"
    rec = acquire_drive_instance_lock(f)
    assert rec["pid"] == os.getpid()
    assert json.loads(f.read_text(encoding="utf-8"))["pid"] == os.getpid()
    release_drive_instance_lock(f)
    assert not f.exists()


def test_acquire_is_idempotent_for_same_process(tmp_path):
    f = tmp_path / "drive_instance.json"
    first = acquire_drive_instance_lock(f)
    second = acquire_drive_instance_lock(f)
    assert first == second
    release_drive_instance_lock(f)


def test_acquire_rejects_alive_foreign_drive(tmp_path):
    """登记的 pid 存活且启动时钟一致 → 拒绝启动并给出指引。"""
    f = tmp_path / "drive_instance.json"
    parent = os.getppid()
    started = _proc_start_time(parent)
    if started is None:
        pytest.skip("非 Linux 无 /proc，启动时钟校验不可用")
    f.write_text(json.dumps({"pid": parent, "started_at": started}),
                 encoding="utf-8")
    with pytest.raises(DriveAlreadyRunning) as exc:
        acquire_drive_instance_lock(f)
    assert str(parent) in str(exc.value)
    # 拒绝时不得覆盖原登记
    assert json.loads(f.read_text(encoding="utf-8"))["pid"] == parent


def test_acquire_overwrites_dead_or_stale_entries(tmp_path):
    f = tmp_path / "drive_instance.json"
    # pid 已死（通常不存在的 999999）→ 视为陈旧，直接接管
    f.write_text(json.dumps({"pid": 999999, "started_at": "1"}),
                 encoding="utf-8")
    assert acquire_drive_instance_lock(f)["pid"] == os.getpid()
    # pid 存活但启动时钟不符（PID 复用指纹）→ 同样视为陈旧
    parent = os.getppid()
    if _proc_start_time(parent) is not None:
        f.write_text(json.dumps({"pid": parent, "started_at": "0"}),
                     encoding="utf-8")
        assert acquire_drive_instance_lock(f)["pid"] == os.getpid()
    # 损坏 JSON → 覆盖
    f.write_text("not-json", encoding="utf-8")
    assert acquire_drive_instance_lock(f)["pid"] == os.getpid()


def test_release_only_removes_own_record(tmp_path):
    f = tmp_path / "drive_instance.json"
    other = {"pid": 999999, "started_at": "1"}
    f.write_text(json.dumps(other), encoding="utf-8")
    release_drive_instance_lock(f)
    # 登记 pid 不是当前进程：保持不动
    assert json.loads(f.read_text(encoding="utf-8")) == other


def _winerr87():
    exc = OSError(87, "参数错误")
    exc.winerror = 87
    return exc


def test_pid_alive_does_not_kill_target():
    """回归：探活绝不能杀进程。

    Windows 上 os.kill 对 0 以外的任意 sig 都走 TerminateProcess，早年
    _pid_alive 用 os.kill(pid, 0) 探活 → 每次 find_live_instance 都把在跑的
    Web UI 杀掉（uvicorn 变孤儿 + 登记陈旧 → TUI 再起一个后端 → 双后端、
    页面连不到车端）。现改为 OpenProcess，必须证明目标进程活得好好的。
    """
    from donkeycar import webui_instance

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert webui_instance._pid_alive(proc.pid) is True
        time.sleep(0.3)
        assert proc.poll() is None, "探活把目标进程杀掉了"
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_pid_alive_false_for_dead_pid():
    from donkeycar import webui_instance

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=10)
    assert webui_instance._pid_alive(proc.pid) is False


def test_pid_gone_error_recognises_wrapped_and_plain_winerror87(monkeypatch):
    """POSIX 分支的兜底：winerror=87 无论是原生 OSError 还是被包成
    SystemError，都要判为「进程不存在」而不是冒泡。"""
    from donkeycar import webui_instance

    def fake_kill(_pid, _sig):
        raise SystemError(
            "<built-in function kill> returned a result with an exception set"
        ) from _winerr87()

    monkeypatch.setattr(webui_instance, "os", type("O", (), {"name": "posix", "kill": fake_kill}))
    assert webui_instance._pid_alive(424242) is False
