import asyncio
import importlib
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from conftest import collect_route_paths

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def make_client():
    app = FastAPI()
    simcollect = importlib.import_module("routers.simcollect")
    app.include_router(simcollect.router, prefix="/api/simcollect")
    return TestClient(app), simcollect


def test_main_registers_simcollect_router():
    main = importlib.import_module("main")
    routes = collect_route_paths(main.app.routes)
    assert "/api/simcollect/start" in routes
    assert "/api/simcollect/{job_id}/status" in routes


# --- 行解析纯函数 ---

def test_parse_step_line():
    from simcollect_engine import parse_step_line
    line = "[collect] step 123: steer=-0.55 thr=0.18 shape=(120, 160, 3) pos=(x) cte=1.024 speed=1.566"
    info = parse_step_line(line)
    assert info == {"step": 123, "cte": 1.024, "speed": 1.566}


def test_parse_step_line_negative_cte():
    from simcollect_engine import parse_step_line
    info = parse_step_line("[collect] step 5: steer=0.2 thr=0.3 cte=-2.305 speed=1.45")
    assert info["cte"] == -2.305
    assert info["step"] == 5


def test_parse_step_line_no_match():
    from simcollect_engine import parse_step_line
    assert parse_step_line("[mac-collect] SSH 连通: dkc-mac") is None
    assert parse_step_line("RESULT steps=100") is None


def test_parse_result_line():
    from simcollect_engine import parse_result_line
    line = "RESULT steps=1500 mean_cte=2.4094 max_cte=7.0614 crashed=0 out=/home/dkc/projects/mycar/sim_collect_x"
    res = parse_result_line(line)
    assert res == {
        "steps": 1500,
        "mean_cte": 2.4094,
        "max_cte": 7.0614,
        "crashed": False,
        "result_out": "/home/dkc/projects/mycar/sim_collect_x",
    }


def test_parse_result_line_crashed():
    from simcollect_engine import parse_result_line
    res = parse_result_line("RESULT steps=42 mean_cte=5.0 max_cte=8.0 crashed=1 out=/o")
    assert res["crashed"] is True


def test_parse_error_line():
    from simcollect_engine import parse_error_line
    assert parse_error_line("[mac-collect] 错误: 没找到模拟器") == "没找到模拟器"
    assert parse_error_line("[collect] step 1") is None


# --- 端到端（子进程 mock） ---

class _FakeStdout:
    def __init__(self, lines):
        self._lines = list(lines)

    async def readline(self):
        if not self._lines:
            return b""
        return self._lines.pop(0).encode("utf-8")


def _fake_process(lines, returncode=0):
    stdout = _FakeStdout(lines)

    class FakeProcess:
        def __init__(self):
            self.stdout = stdout
            self.returncode = returncode
            self.pid = 12345

        async def wait(self):
            return self.returncode

    return FakeProcess()


def test_start_and_done(monkeypatch):
    import simcollect_engine as se
    client, _ = make_client()

    # 重置单例，避免与其它测试串扰
    monkeypatch.setattr(se.simcollect_job_manager, "jobs", {})
    monkeypatch.setattr(se.simcollect_job_manager, "active_job_id", None)

    lines = [
        "[mac-collect] SSH 连通: dkc-mac (192.168.3.63)\n",
        "[collect] step 0: steer=0.0 thr=0.3 cte=0.0 speed=0.0\n",
        "[collect] step 1: steer=0.1 thr=0.3 cte=0.5 speed=1.2\n",
        "RESULT steps=2 mean_cte=0.25 max_cte=0.5 crashed=0 out=/x/sim\n",
    ]

    async def create_process(*args, **kwargs):
        return _fake_process(lines)

    monkeypatch.setattr(se.asyncio, "create_subprocess_exec", create_process)

    resp = client.post("/api/simcollect/start", json={"steps": 2})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    # 跑完（run 是后台任务，等它结束）
    async def drain():
        job = se.simcollect_job_manager.get_job(job_id)
        await se.simcollect_job_manager.run(job, steps=2, kp=0.55, kd=0.8,
                                            throttle=0.3, min_throttle=0.15,
                                            keep_sim=False)
    asyncio.run(drain())

    status = client.get(f"/api/simcollect/{job_id}/status").json()
    assert status["status"] == "done"
    assert status["step"] == 1
    assert status["steps_total"] == 2
    assert status["cte"] == 0.5
    assert status["result"]["steps"] == 2
    assert status["result"]["crashed"] is False
    assert any("RESULT" in line for line in status["logs"])


def test_start_conflict_when_running(monkeypatch):
    import simcollect_engine as se
    client, _ = make_client()

    # 预置一个 running 任务
    monkeypatch.setattr(se.simcollect_job_manager, "jobs", {})
    monkeypatch.setattr(se.simcollect_job_manager, "active_job_id", None)
    se.simcollect_job_manager.create_job(steps=10, kp=0.55, kd=0.8,
                                         throttle=0.3, min_throttle=0.15, keep_sim=False)
    resp = client.post("/api/simcollect/start", json={"steps": 10})
    assert resp.status_code == 409


def test_status_404():
    client, _ = make_client()
    assert client.get("/api/simcollect/nope/status").status_code == 404
    assert client.post("/api/simcollect/nope/stop").status_code == 404


def test_stop_marks_stopped(monkeypatch):
    import simcollect_engine as se
    client, _ = make_client()
    monkeypatch.setattr(se.simcollect_job_manager, "jobs", {})
    monkeypatch.setattr(se.simcollect_job_manager, "active_job_id", None)

    job = se.simcollect_job_manager.create_job(steps=10, kp=0.55, kd=0.8,
                                               throttle=0.3, min_throttle=0.15, keep_sim=False)
    job.status = "running"

    # process 不存在（None）时 stop 仍能把状态置为 stopped
    resp = client.post(f"/api/simcollect/{job.id}/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"


def test_run_error_on_nonzero_exit_without_result(monkeypatch):
    import simcollect_engine as se
    client, _ = make_client()
    monkeypatch.setattr(se.simcollect_job_manager, "jobs", {})
    monkeypatch.setattr(se.simcollect_job_manager, "active_job_id", None)

    lines = ["[mac-collect] 错误: 没找到模拟器\n"]
    async def create_process(*args, **kwargs):
        return _fake_process(lines, returncode=1)
    monkeypatch.setattr(se.asyncio, "create_subprocess_exec", create_process)

    resp = client.post("/api/simcollect/start", json={"steps": 5})
    job_id = resp.json()["job_id"]

    async def drain():
        job = se.simcollect_job_manager.get_job(job_id)
        await se.simcollect_job_manager.run(job, steps=5, kp=0.55, kd=0.8,
                                            throttle=0.3, min_throttle=0.15, keep_sim=False)
    asyncio.run(drain())

    status = client.get(f"/api/simcollect/{job_id}/status").json()
    assert status["status"] == "error"
    assert "没找到模拟器" in status["error"]
