# -*- coding: utf-8 -*-
"""drive 单实例守护（acquire/release_drive_instance_lock）测试。"""

import json
import os

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
