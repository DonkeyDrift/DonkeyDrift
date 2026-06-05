import importlib
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def make_client(monkeypatch, tmp_path):
    connector = importlib.import_module("routers.connector")
    connector = importlib.reload(connector)
    monkeypatch.setattr(connector, "_get_config_path", lambda: tmp_path / "connector.json")
    app = FastAPI()
    app.include_router(connector.router, prefix="/api/connector")
    return TestClient(app), connector


def test_main_registers_connector_router():
    main = importlib.import_module("main")
    routes = {route.path for route in main.app.routes}
    assert "/api/connector/config" in routes
    assert "/api/connector/status" in routes


def test_config_round_trip(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)

    payload = {
        "host": "donkeycar.local",
        "user": "pi",
        "port": 22,
        "car_dir": "~/mycar",
        "key_path": "~/.ssh/id_rsa",
    }

    response = client.post("/api/connector/config", json=payload)

    assert response.status_code == 200
    assert response.json()["config"]["host"] == "donkeycar.local"

    loaded = client.get("/api/connector/config")
    assert loaded.status_code == 200
    assert loaded.json()["config"]["user"] == "pi"


def test_rejects_dangerous_remote_path():
    from remote_car_client import validate_remote_path

    with pytest.raises(ValueError):
        validate_remote_path("~/mycar; rm -rf ~")
    with pytest.raises(ValueError):
        validate_remote_path("~/mycar\nwhoami")


def test_build_pull_tub_command_uses_argument_array():
    from remote_car_client import ConnectorConfig, build_pull_tub_command

    config = ConnectorConfig(host="car.local", user="pi", car_dir="~/mycar")

    command = build_pull_tub_command(
        config=config,
        remote_tub="data",
        local_data_path="./data",
        create_new_dir=False,
    )

    assert command[:4] == ["rsync", "-rv", "--progress", "--partial"]
    assert command[-2] == "pi@car.local:~/mycar/data/"
    assert command[-1] == "./data"


def test_build_push_pilots_command_filters_selected_formats():
    from remote_car_client import ConnectorConfig, build_push_pilots_command

    config = ConnectorConfig(host="car.local", user="pi", car_dir="~/mycar")

    command = build_push_pilots_command(
        config=config,
        local_models_path="./models",
        formats=["tflite", "trt"],
    )

    assert "--include=database.json" in command
    assert "--include=*.tflite" in command
    assert "--include=*.trt/***" in command
    assert "--exclude=*" in command
    assert command[-2] == "./models/"
    assert command[-1] == "pi@car.local:~/mycar/models"


def test_build_remote_drive_start_command_rejects_invalid_bridge_url():
    from remote_car_client import ConnectorConfig, build_remote_drive_start_command

    config = ConnectorConfig(host="car.local", user="pi", car_dir="~/mycar")

    with pytest.raises(ValueError):
        build_remote_drive_start_command(config=config, bridge_server_url="http://127.0.0.1:8000/api/drive/ws")
    with pytest.raises(ValueError):
        build_remote_drive_start_command(config=config, bridge_server_url="ws://host/api/drive/ws;rm -rf ~")


def test_build_remote_drive_start_command_injects_bridge_url_safely():
    from remote_car_client import ConnectorConfig, build_remote_drive_start_command

    config = ConnectorConfig(host="car.local", user="pi", car_dir="~/mycar")

    command = build_remote_drive_start_command(
        config=config,
        model_type="tflite_linear",
        pilot="pilot.tflite",
        bridge_server_url="ws://192.168.1.2:8000/api/drive/ws",
    )

    remote_command = command[-1]
    assert command[:3] == ["ssh", "-p", "22"]
    assert "DRIVE_API_SERVER_URL=ws://192.168.1.2:8000/api/drive/ws" in remote_command
    assert "--type tflite_linear" in remote_command
    assert "--model '~/mycar/models/pilot.tflite'" in remote_command
    assert ".donkeycar_drive.pid" in remote_command
    assert "echo \"$pid\"" in remote_command


def test_build_remote_drive_stop_command_validates_process_before_kill():
    from remote_car_client import ConnectorConfig, build_remote_drive_stop_command

    config = ConnectorConfig(host="car.local", user="pi", car_dir="~/mycar")

    command = build_remote_drive_stop_command(config, 1234)
    remote_command = command[-1]

    assert ".donkeycar_drive.pid" in remote_command
    assert "ps -p \"$pid\" -o args=" in remote_command
    assert "manage.py drive" in remote_command
    assert "/proc/$pid/cwd" in remote_command
    assert "kill -SIGINT \"$pid\"" in remote_command



def test_build_remote_drive_stop_command_rejects_invalid_pid():
    from remote_car_client import ConnectorConfig, build_remote_drive_stop_command

    config = ConnectorConfig(host="car.local", user="pi", car_dir="~/mycar")

    with pytest.raises(ValueError, match="PID 无效"):
        build_remote_drive_stop_command(config, 0)



def test_build_remote_rsync_check_command_checks_remote_binary():
    from remote_car_client import ConnectorConfig, build_remote_rsync_check_command

    config = ConnectorConfig(host="car.local", user="pi", car_dir="~/mycar")

    command = build_remote_rsync_check_command(config)

    assert command[:3] == ["ssh", "-p", "22"]
    assert "command -v rsync" in command[-1]
    assert "车端缺少 rsync" in command[-1]



def test_invalid_config_file_returns_400(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)
    (tmp_path / "connector.json").write_text("{bad json")

    response = client.get("/api/connector/config")

    assert response.status_code == 400
    assert "Connector 配置文件无效" in response.json()["detail"]


def test_connection_status_handles_missing_ssh(monkeypatch):
    import subprocess
    from remote_car_client import ConnectorConfig, RemoteCarClient

    def raise_missing(*args, **kwargs):
        raise FileNotFoundError("ssh")

    monkeypatch.setattr(subprocess, "run", raise_missing)

    online, message = RemoteCarClient(ConnectorConfig(host="car.local", user="pi")).check_connection()

    assert online is False
    assert "ssh 命令不可用" in message


def test_connection_status_handles_timeout(monkeypatch):
    import subprocess
    from remote_car_client import ConnectorConfig, RemoteCarClient

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=8)

    monkeypatch.setattr(subprocess, "run", raise_timeout)

    online, message = RemoteCarClient(ConnectorConfig(host="car.local", user="pi")).check_connection()

    assert online is False
    assert "连接超时" in message


def test_status_uses_remote_client(monkeypatch, tmp_path):
    client, connector = make_client(monkeypatch, tmp_path)

    class FakeRemoteCarClient:
        def __init__(self, config):
            self.config = config

        def check_connection(self):
            return True, "Connected"

    monkeypatch.setattr(connector, "RemoteCarClient", FakeRemoteCarClient)
    client.post(
        "/api/connector/config",
        json={"host": "car.local", "user": "pi", "port": 22, "car_dir": "~/mycar"},
    )

    response = client.post("/api/connector/status")

    assert response.status_code == 200
    assert response.json() == {"online": True, "message": "Connected"}


def test_pull_tub_job_fails_when_command_building_fails():
    import asyncio

    from connector_engine import ConnectorJobManager
    from remote_car_client import ConnectorConfig

    async def run_job():
        manager = ConnectorJobManager()
        job = manager.create_job("pull_tub")

        await manager.run_pull_tub(
            job,
            ConnectorConfig(host="car.local", user="pi", car_dir="~/mycar"),
            "bad/name",
            "./data",
            False,
        )

        event = await job.log_queue.get()
        return job, event

    job, event = asyncio.run(run_job())

    assert job.status == "failed"
    assert "远端名称不能包含路径分隔符" in job.error_message
    assert event["type"] == "status"
    assert event["status"] == "failed"


def test_pull_tub_job_fails_when_local_rsync_is_missing(monkeypatch):
    import asyncio

    import connector_engine
    from connector_engine import ConnectorJobManager
    from remote_car_client import ConnectorConfig

    async def run_job():
        manager = ConnectorJobManager()
        job = manager.create_job("pull_tub")
        monkeypatch.setattr(connector_engine.shutil, "which", lambda name: None)

        await manager.run_pull_tub(
            job,
            ConnectorConfig(host="car.local", user="pi", car_dir="~/mycar"),
            "data",
            "./data",
            False,
        )

        event = await job.log_queue.get()
        return job, event

    job, event = asyncio.run(run_job())

    assert job.status == "failed"
    assert "本机缺少 rsync" in job.error_message
    assert event["status"] == "failed"



def test_drive_command_keeps_stopped_status(monkeypatch):
    import asyncio

    import connector_engine
    from connector_engine import ConnectorJobManager

    class FakeStdout:
        async def readline(self):
            return b""

    async def run_job():
        release_process = asyncio.Event()

        class FakeProcess:
            stdout = FakeStdout()
            returncode = 1

            async def wait(self):
                await release_process.wait()
                return self.returncode

        async def create_process(*args, **kwargs):
            return FakeProcess()

        manager = ConnectorJobManager()
        job = manager.create_job("drive_start")
        monkeypatch.setattr(connector_engine.asyncio, "create_subprocess_exec", create_process)

        task = asyncio.create_task(manager._run_drive_command(job, ["ssh", "car"], capture_pid=True))
        await asyncio.sleep(0)
        job.status = "stopped"
        release_process.set()
        await task

        event = await job.log_queue.get()
        return job, event

    job, event = asyncio.run(run_job())

    assert job.status == "stopped"
    assert event["type"] == "status"
    assert event["status"] == "stopped"



def test_drive_stop_failure_keeps_pid(monkeypatch):
    import asyncio

    import connector_engine
    from connector_engine import ConnectorJobManager
    from remote_car_client import ConnectorConfig

    class FakeStdout:
        def __init__(self):
            self.lines = ["拒绝停止\n".encode("utf-8"), b""]

        async def readline(self):
            return self.lines.pop(0)

    class FakeProcess:
        stdout = FakeStdout()
        returncode = 1

        async def wait(self):
            return self.returncode

    async def create_process(*args, **kwargs):
        return FakeProcess()

    async def run_job():
        manager = ConnectorJobManager()
        manager.drive_pid = 1234
        job = manager.create_job("drive_stop")
        monkeypatch.setattr(connector_engine.asyncio, "create_subprocess_exec", create_process)

        await manager.run_drive_stop(job, ConnectorConfig(host="car.local", user="pi", car_dir="~/mycar"), None)

        return manager, job

    manager, job = asyncio.run(run_job())

    assert job.status == "failed"
    assert manager.drive_pid == 1234
