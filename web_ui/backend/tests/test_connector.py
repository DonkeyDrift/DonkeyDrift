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
    assert "echo $!" in remote_command


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
