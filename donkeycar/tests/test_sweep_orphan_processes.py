# -*- coding: utf-8 -*-
"""孤儿栈进程清扫（sweep_orphan_processes 及其扫描函数）测试。

背景（2026-11-09 macOS 线上复现）：手工 nohup 裸起的车端/uvicorn 不在
drive.pid 与 webui.json 任何登记里，既有清理均触及不到——无登记 uvicorn
被 find_live_instance 判「无实例」再起一套 → 双后端（页面无画面、摇杆
无效）；无登记车端被单实例守护拒绝启动。macOS 无 /proc，扫描走 ps 快照。
"""

import os

import pytest

from donkeycar import webui_instance as wi


def _proc(pid, ppid, command):
    return {"pid": pid, "ppid": ppid, "command": command}


# ── _run_ps_snapshot ────────────────────────────────────────────────

def test_run_ps_snapshot_parses_pid_ppid_command(monkeypatch):
    out = (
        "    1      0 launchd\n"
        " 81427  81234 python -u manage.py drive\n"
        "  89354  89202 .venv/bin/python -m uvicorn main:app --host 0.0.0.0\n"
        "  99999  88888\n"  # 无命令行的行（内核态等），应跳过
        "not-a-number  1 x\n"  # 解析失败行，应跳过
    )

    class FakeCompleted:
        stdout = out

    def fake_run(*args, **kwargs):
        return FakeCompleted()

    monkeypatch.setattr(wi.subprocess, "run", fake_run)
    snapshot = wi._run_ps_snapshot()
    assert snapshot == [
        _proc(1, 0, "launchd"),
        _proc(81427, 81234, "python -u manage.py drive"),
        _proc(89354, 89202,
              ".venv/bin/python -m uvicorn main:app --host 0.0.0.0"),
    ]


def test_run_ps_snapshot_swallows_ps_failure(monkeypatch):
    def fake_run(*args, **kwargs):
        raise OSError("ps not found")

    monkeypatch.setattr(wi.subprocess, "run", fake_run)
    assert wi._run_ps_snapshot() == []


# ── python 首词判定（防 bash -c 包装器误杀）─────────────────────────

def test_is_python_proc():
    assert wi._is_python_proc(".venv/bin/python -u manage.py drive")
    assert wi._is_python_proc("python -m uvicorn main:app")
    assert wi._is_python_proc("python3.11 manage.py drive")
    # bash/zsh 包装器：命令文本含特征词也不是车端/后端
    assert not wi._is_python_proc(
        '/bin/zsh -c "pgrep -lf \'uvicorn main:app|manage.py drive\'"')
    assert not wi._is_python_proc("tail -f drive.log")
    assert not wi._is_python_proc("")


# ── find_car_processes 的 ps fallback（macOS 无 /proc）──────────────

def test_find_car_processes_falls_back_to_ps_snapshot(monkeypatch, tmp_path):
    """proc_dir 不存在（macOS）时经 ps 快照匹配 manage.py drive。

    bash 包装器（首词非 python）即便命令文本含特征词也不命中——否则
    排查命令里带 grep/pgrep 特征词会误杀执行清扫的 shell 自己
    （2026-11-09 真机复现：heredoc 排查命令把外层 bash 杀了）。
    """
    monkeypatch.setattr(wi, "_run_ps_snapshot", lambda: [
        _proc(101, 1, "/bin/zsh -c nohup python manage.py drive"),
        _proc(102, 101, "python -u manage.py drive"),
        _proc(103, 1, "python -m uvicorn main:app"),
        _proc(104, 1, "python manage.py"),  # 含 manage.py 无 drive
        _proc(105, 1, "python drive.log viewer"),  # 含 drive 无 manage.py
    ])
    pids = wi.find_car_processes(proc_dir=str(tmp_path / "no-proc"))
    assert pids == [102]


def test_find_car_processes_excludes_given_pids(monkeypatch, tmp_path):
    monkeypatch.setattr(wi, "_run_ps_snapshot", lambda: [
        _proc(201, 1, "python manage.py drive"),
        _proc(202, 1, "python manage.py drive"),
    ])
    pids = wi.find_car_processes(exclude_pids=[201],
                                 proc_dir=str(tmp_path / "no-proc"))
    assert pids == [202]


# ── web_ui 后端识别 ─────────────────────────────────────────────────

@pytest.mark.parametrize("cwd,expected", [
    ("/Users/hwp/Dev/DKC/DonkeyDrift/web_ui/backend", True),
    ("/home/pi/projects/other/web_ui/backend", True),
    ("/Users/hwp/Dev/DKC/mycar", False),
    ("/Users/hwp/Dev/DKC/DonkeyDrift/web_ui", False),
    ("/Users/hwp/backend", False),
    ("", False),
    (None, False),
])
def test_is_webui_backend_cwd(cwd, expected):
    assert wi._is_webui_backend_cwd(cwd) is expected


def test_find_webui_backend_processes_filters_by_cwd(monkeypatch):
    monkeypatch.setattr(wi, "_run_ps_snapshot", lambda: [
        _proc(301, 1, "python -m uvicorn main:app --port 8000"),   # 本仓库孤儿
        _proc(302, 1, "python -m uvicorn main:app --port 9000"),   # 别的 FastAPI 项目
        _proc(303, 1, "python -m uvicorn main:app --port 9001"),   # cwd 未知
        _proc(304, 1, "python -m uvicorn other:app"),              # 非 web_ui app
        _proc(305, 1, "grep uvicorn main:app"),                    # 无关进程
        _proc(os.getpid(), 1, "python -m uvicorn main:app"),       # 自己，排除
    ])
    cwd_by_pid = {
        301: "/repo/web_ui/backend",
        302: "/home/user/blog-fastapi",
        303: None,
        os.getpid(): "/repo/web_ui/backend",
    }
    monkeypatch.setattr(wi, "_process_cwd", lambda pid: cwd_by_pid.get(pid))
    assert wi.find_webui_backend_processes() == [301]


def test_find_webui_backend_processes_respects_protected(monkeypatch):
    monkeypatch.setattr(wi, "_run_ps_snapshot", lambda: [
        _proc(401, 1, "python -m uvicorn main:app"),
        _proc(402, 1, "python -m uvicorn main:app"),
    ])
    monkeypatch.setattr(
        wi, "_process_cwd", lambda pid: "/repo/web_ui/backend")
    pids = wi.find_webui_backend_processes(protected_pids=[401])
    assert pids == [402]


# ── 进程树 ──────────────────────────────────────────────────────────

def test_descendant_pids_walks_tree():
    snapshot = [
        _proc(1, 0, "launchd"),
        _proc(50, 1, "donkey drive"),        # 根
        _proc(51, 50, "uvicorn main:app"),   # 直接子
        _proc(52, 51, "uvicorn --reload worker"),  # 间接子
        _proc(53, 1, "unrelated"),
    ]
    assert wi._descendant_pids(50, snapshot) == [51, 52]


# ── sweep_orphan_processes 编排 ─────────────────────────────────────

def test_sweep_without_live_instance_kills_all_backends(monkeypatch):
    """无存活登记实例：uvicorn 全是孤儿，连同车端一并终止。"""
    monkeypatch.setattr(wi, "find_live_instance", lambda: None)
    monkeypatch.setattr(wi, "takeover_car_processes", lambda: [111])
    monkeypatch.setattr(wi, "find_webui_backend_processes", lambda protected_pids=None: [222])
    killed = {}
    monkeypatch.setattr(
        wi, "_terminate_processes",
        lambda pids, grace_s: killed.setdefault("pids", []).extend(pids))
    report = wi.sweep_orphan_processes()
    assert report == {"car_pids": [111], "backend_pids": [222]}
    assert killed["pids"] == [222]  # 车端由 takeover 终止，sweep 只补杀后端


def test_sweep_protects_live_instance_tree(monkeypatch):
    """有存活登记实例：其进程树作为 protected 传入后端扫描（绝不能误杀）。"""
    inst = {"pid": 50, "backend_port": 8000, "frontend_port": 8000}
    monkeypatch.setattr(wi, "find_live_instance", lambda: inst)
    monkeypatch.setattr(wi, "takeover_car_processes", lambda: [])
    snapshot = [
        _proc(1, 0, "launchd"),
        _proc(50, 1, "donkey drive"),
        _proc(51, 50, "uvicorn main:app"),
        _proc(60, 1, "uvicorn main:app"),  # 真孤儿
    ]
    monkeypatch.setattr(wi, "_run_ps_snapshot", lambda: snapshot)
    captured = {}

    def fake_find(protected_pids=None):
        captured["protected"] = protected_pids
        return [60]

    monkeypatch.setattr(wi, "find_webui_backend_processes", fake_find)
    monkeypatch.setattr(wi, "_terminate_processes",
                        lambda pids, grace_s: None)
    report = wi.sweep_orphan_processes()
    assert report == {"car_pids": [], "backend_pids": [60]}
    # 登记进程及其 uvicorn 子进程都被保护
    assert sorted(captured["protected"]) == [50, 51]


def test_sweep_clean_stack_is_noop(monkeypatch):
    monkeypatch.setattr(wi, "find_live_instance", lambda: None)
    monkeypatch.setattr(wi, "takeover_car_processes", lambda: [])
    monkeypatch.setattr(wi, "find_webui_backend_processes",
                        lambda protected_pids=None: [])
    killed = {}
    monkeypatch.setattr(wi, "_terminate_processes",
                        lambda pids, grace_s: killed.setdefault("called", True))
    assert wi.sweep_orphan_processes() == {
        "car_pids": [], "backend_pids": []}
    assert not killed  # 无孤儿时不发任何终止信号
