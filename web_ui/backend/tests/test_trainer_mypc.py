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

    def fake_run_mypc(job, config_file="train_my_pc.conf", working_dir=None, ssh_credentials=None):
        captured["job"] = job
        captured["config_file"] = config_file
        captured["working_dir"] = working_dir
        captured["ssh_credentials"] = ssh_credentials

    with _build_client() as client, \
         patch("trainer_engine.job_manager.run_mypc", side_effect=fake_run_mypc):
        resp = client.post("/api/trainer/train/mypc", json={
            "config_file": "train_my_pc.conf",
            "working_dir": "/tmp/mycar",
            "ssh": {"host": "192.168.1.10", "user": "me", "password": "secret"},
        })

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    job: TrainingJob = captured["job"]
    assert job.id == body["job_id"]
    assert job.mode == "mypc"
    assert captured["config_file"] == "train_my_pc.conf"
    assert captured["working_dir"] == "/tmp/mycar"
    assert captured["ssh_credentials"]["host"] == "192.168.1.10"
    assert captured["ssh_credentials"]["user"] == "me"
    assert captured["ssh_credentials"]["password"] == "secret"


def test_mypc_route_defaults():
    captured = {}

    def fake_run_mypc(job, config_file="train_my_pc.conf", working_dir=None, ssh_credentials=None):
        captured["config_file"] = config_file
        captured["working_dir"] = working_dir
        captured["ssh_credentials"] = ssh_credentials

    with _build_client() as client, \
         patch("trainer_engine.job_manager.run_mypc", side_effect=fake_run_mypc):
        resp = client.post("/api/trainer/train/mypc", json={})

    assert resp.status_code == 200
    assert captured["config_file"] == "train_my_pc.conf"
    assert captured["working_dir"] is None
    assert captured["ssh_credentials"] is None


def test_mypc_probe_route():
    from mypc_probe import ProbeCheck, ProbeResult

    def fake_probe(host, user, password, remote_dir_base="~/projects",
                   python_path="", port=22):
        return ProbeResult(
            ok=True,
            platform="linux",
            shell="posix",
            checks=[ProbeCheck(name="ssh", status="ok", message="connected")],
            python_path="/usr/bin/python3",
            suggestions=["环境就绪，可以开始局域网主机训练。"],
        )

    with _build_client() as client, \
         patch("routers.trainer.probe_mypc_environment", side_effect=fake_probe):
        resp = client.post("/api/trainer/mypc/probe", json={
            "host": "192.168.1.10",
            "user": "u",
            "password": "p",
            "remote_dir_base": "~/projects",
            "python_path": "",
        })

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["platform"] == "linux"
    assert body["python_path"] == "/usr/bin/python3"
    assert body["checks"][0]["name"] == "ssh"
    assert body["suggestions"]


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


def test_config_endpoint_does_not_write_password(tmp_path):
    import configparser

    conf = tmp_path / "train.conf"

    with _build_client() as client:
        resp = client.post(
            "/api/trainer/config",
            json={
                "host": "example.com",
                "user": "ubuntu",
                "remote_dir_base": "~/projects",
                "model_name": "model",
                "python_path": "python",
            },
            params={"config_file": str(conf)},
        )

    assert resp.status_code == 200
    parser = configparser.ConfigParser()
    parser.read(str(conf))
    assert "password" not in parser["Remote"]
    assert "dkc@2026" not in conf.read_text()


def test_get_config_returns_empty_password(tmp_path):
    import configparser

    conf = tmp_path / "train.conf"
    parser = configparser.ConfigParser()
    parser["Remote"] = {"host": "example.com", "user": "ubuntu"}
    with open(conf, "w") as f:
        parser.write(f)

    with _build_client() as client:
        resp = client.get("/api/trainer/config", params={"config_file": str(conf)})

    assert resp.status_code == 200
    assert resp.json()["password"] == ""


def test_get_config_auto_creates_without_plaintext_credentials(tmp_path):
    conf = tmp_path / "train_new.conf"

    with _build_client() as client:
        resp = client.get("/api/trainer/config", params={"config_file": str(conf)})

    assert resp.status_code == 200
    body = resp.json()
    assert body["password"] == ""
    assert body["host"] == ""
    content = conf.read_text()
    assert "dkc@2026" not in content
    assert "haowenpi.com" not in content
