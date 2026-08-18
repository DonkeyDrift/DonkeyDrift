import sys
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _build_client():
    from routers import trainer as trainer_router

    app = FastAPI()
    app.include_router(trainer_router.router, prefix="/api/trainer")
    return TestClient(app)


def test_mypc_route_creates_mypc_job():
    from trainer_engine import TrainingJob

    captured = {}

    def fake_run_mypc(job, config_file="train_my_pc.conf", working_dir=None):
        captured["job"] = job
        captured["config_file"] = config_file
        captured["working_dir"] = working_dir

    with _build_client() as client, \
         patch("trainer_engine.job_manager.run_mypc", side_effect=fake_run_mypc):
        resp = client.post("/api/trainer/train/mypc", json={
            "config_file": "train_my_pc.conf",
            "working_dir": "/tmp/mycar",
        })

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    job: TrainingJob = captured["job"]
    assert job.id == body["job_id"]
    assert job.mode == "mypc"
    assert captured["config_file"] == "train_my_pc.conf"
    assert captured["working_dir"] == "/tmp/mycar"


def test_mypc_route_defaults():
    captured = {}

    def fake_run_mypc(job, config_file="train_my_pc.conf", working_dir=None):
        captured["config_file"] = config_file
        captured["working_dir"] = working_dir

    with _build_client() as client, \
         patch("trainer_engine.job_manager.run_mypc", side_effect=fake_run_mypc):
        resp = client.post("/api/trainer/train/mypc", json={})

    assert resp.status_code == 200
    assert captured["config_file"] == "train_my_pc.conf"
    assert captured["working_dir"] is None


def test_stop_mypc_job_sets_stop_event():
    import asyncio
    import threading
    from trainer_engine import job_manager

    job = job_manager.create_job("mypc")
    job.status = "running"
    # run_online creates the stop event when the SSH pipeline starts;
    # simulate that state here.
    job.stop_event = threading.Event()

    async def _stop():
        job_manager.stop_job(job.id)

    asyncio.run(_stop())

    assert job.status == "stopped"
    assert job.stop_event.is_set()
