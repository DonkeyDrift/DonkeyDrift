"""纪律红线回归:stop_sim 绝不跨端口误杀(2026-11-02 事故复盘)。

事故:eval-gate 停自己的 9095 sim 时未传 port,旧实现默认 port=9091 并在
子进程路径后仍跑「端口确认释放」兜底 → 杀了 9091 上的训练 sim。
本测试守住:① 子进程路径不触碰任何端口扫描;② 外部路径无 port 必须抛。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import _sim_proc  # noqa: E402


class _DeadProc:
    """已退出的假子进程:terminate 抛 ProcessLookupError。"""

    pid = 424242

    def terminate(self):
        raise ProcessLookupError

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class _LiveProc:
    """活着→terminate 后立刻退出的假子进程。"""

    pid = 434343

    def __init__(self):
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def test_child_path_never_scans_ports(monkeypatch):
    calls = []
    monkeypatch.setattr(_sim_proc, "_pids_listening_on",
                        lambda port: calls.append(port) or [])
    monkeypatch.setattr(_sim_proc, "_kill_pids", lambda *a, **k: calls.append(("kill", a)))
    rec = _sim_proc.stop_sim(proc=_LiveProc())
    assert rec["mode"] == "child_pid"
    assert rec["pids"] == [434343]
    assert calls == [], "子进程路径不得触发任何按端口扫描/杀进程"


def test_child_path_dead_proc_is_noop(monkeypatch):
    calls = []
    monkeypatch.setattr(_sim_proc, "_pids_listening_on",
                        lambda port: calls.append(port) or [])
    rec = _sim_proc.stop_sim(proc=_DeadProc())
    assert rec["mode"] == "child_pid"
    assert calls == []


def test_external_path_requires_explicit_port():
    with pytest.raises(ValueError, match="必须显式传 port"):
        _sim_proc.stop_sim(proc=None)


def test_external_path_only_targets_given_port(monkeypatch):
    seen = []
    killed = []
    monkeypatch.setattr(_sim_proc, "_pids_listening_on",
                        lambda port: (seen.append(port), [777] if not killed else [])[1])
    monkeypatch.setattr(_sim_proc, "_kill_pids",
                        lambda pids, t=6.0: killed.append(list(pids)))
    rec = _sim_proc.stop_sim(port=9095)
    assert rec["mode"] == "by_port" and rec["port"] == 9095
    assert set(seen) == {9095}, "只允许扫描指定端口"
    assert killed and killed[0] == [777]


def test_pids_listening_on_filters_self_and_non_sim(monkeypatch):
    """lsof 返回 自身 pid + 非 sim pid + sim pid,只保留 sim pid。"""
    import subprocess

    me = os.getpid()

    class _R:
        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(cmd, **kw):
        if cmd[0] == "lsof":
            return _R(f"{me}\n1234\n5678\n")
        if cmd[0] == "ps":
            pid = int(cmd[2])
            return _R("donkey_sim" if pid == 5678 else "python3.11")
        raise AssertionError(cmd)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _sim_proc._pids_listening_on(9091) == [5678]
