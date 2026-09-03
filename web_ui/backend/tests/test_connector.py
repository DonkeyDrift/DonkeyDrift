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



def make_client(monkeypatch, tmp_path):
    connector = importlib.import_module("routers.connector")
    connector = importlib.reload(connector)
    monkeypatch.setattr(connector, "_get_config_path", lambda: tmp_path / "connector.json")
    app = FastAPI()
    app.include_router(connector.router, prefix="/api/connector")
    return TestClient(app), connector


def test_main_registers_connector_router():
    main = importlib.import_module("main")
    routes = collect_route_paths(main.app.routes)
    assert "/api/connector/config" in routes
    assert "/api/connector/status" in routes
    assert "/api/connector/local_ips" in routes
    assert "/api/connector/discover_console" in routes


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
    # 增量同步：--update 跳过本地已存在文件，--stats 输出传输统计
    assert "--update" in command
    assert "--stats" in command
    assert command[-2] == "pi@car.local:~/mycar/data/"
    assert command[-1] == "./data"


def test_parse_rsync_stats_extracts_transfer_summary():
    from remote_car_client import parse_rsync_stats

    lines = [
        "Number of files: 12 (reg: 10, dir: 2)",
        "Number of regular files transferred: 8",
        "Total file size: 1,024,576 bytes",
        "Total transferred file size: 512,000 bytes",
    ]

    stats = parse_rsync_stats(lines)

    assert stats.total_files == 12
    assert stats.transferred_files == 8
    assert stats.total_size == 1024576
    assert stats.transferred_bytes == 512000
    assert "8/12" in stats.summary()


def test_parse_rsync_stats_supports_legacy_transferred_size_wording():
    from remote_car_client import parse_rsync_stats

    # 老版 rsync 输出 "Total transferred size"（无 file 一词），也应正确解析
    stats = parse_rsync_stats(["Total transferred size: 300 bytes"])

    assert stats.transferred_bytes == 300


def test_parse_rsync_stats_handles_empty_output():
    from remote_car_client import parse_rsync_stats

    stats = parse_rsync_stats([])

    assert stats.transferred_files == 0
    assert stats.total_files == 0


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
    assert response.json()["online"] is True
    assert response.json()["message"] == "Connected"


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


def test_local_ips_endpoint(monkeypatch, tmp_path):
    client, connector = make_client(monkeypatch, tmp_path)

    def fake_get_local_ips():
        return [
            {"ip": "192.168.1.10", "interface": "eth0", "priority": 0},
            {"ip": "10.0.0.5", "interface": "wlan0", "priority": 0},
        ]

    monkeypatch.setattr(connector, "get_local_ips", fake_get_local_ips)

    response = client.get("/api/connector/local_ips")

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert data["ips"][0]["ip"] == "192.168.1.10"


def test_discover_console_endpoint_finds_console(monkeypatch, tmp_path):
    client, connector = make_client(monkeypatch, tmp_path)
    async def fake_discover_hosts(port, timeout=0.4, max_concurrent=64):
        return [{"ip": "192.168.3.46", "port": port, "latency_ms": 1.2, "reachable": True}], 256
    async def fake_check(ip):
        if ip == "192.168.3.46":
            return {"ip": ip, "port": 80, "reachable": True}
        return None
    monkeypatch.setattr(connector, "discover_hosts", fake_discover_hosts)
    monkeypatch.setattr(connector, "_check_drifter_console", fake_check)
    response = client.post("/api/connector/discover_console")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] is True
    assert data["count"] == 1
    assert data["found"][0]["ip"] == "192.168.3.46"


def test_discover_console_endpoint_empty(monkeypatch, tmp_path):
    client, connector = make_client(monkeypatch, tmp_path)
    async def fake_discover_hosts(port, timeout=0.4, max_concurrent=64):
        return [], 256
    async def fake_check(ip):
        return None
    monkeypatch.setattr(connector, "discover_hosts", fake_discover_hosts)
    monkeypatch.setattr(connector, "_check_drifter_console", fake_check)
    response = client.post("/api/connector/discover_console")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0


def _install_auto_sync_fakes(monkeypatch, connector):
    """为自动同步测试打桩：记录 run_auto_sync 触发情况，不让真实任务跑起来。"""
    triggered = []

    async def fake_run_auto_sync(key, config, remote_tub, local_data_path, on_finished=None):
        triggered.append({"key": key, "remote_tub": remote_tub})

    monkeypatch.setattr(connector.connector_job_manager, "run_auto_sync", fake_run_auto_sync)
    return triggered


def test_status_auto_sync_triggers_once_when_online(monkeypatch, tmp_path):
    client, connector = make_client(monkeypatch, tmp_path)
    triggered = _install_auto_sync_fakes(monkeypatch, connector)

    class FakeRemoteCarClient:
        def __init__(self, config):
            self.config = config

        def check_connection(self):
            return True, "Connected"

    monkeypatch.setattr(connector, "RemoteCarClient", FakeRemoteCarClient)
    client.post(
        "/api/connector/config",
        json={"host": "car.local", "user": "pi", "port": 22, "car_dir": "~/mycar", "auto_sync": True},
    )

    # 第一次状态检查：连接成功 + auto_sync 开启 → 触发一次自动同步
    response = client.post("/api/connector/status")
    assert response.status_code == 200
    data = response.json()
    assert data["online"] is True
    assert data["auto_sync"] == {"enabled": True, "triggered": True}
    assert data["last_sync"] == {"at": None, "result": None}

    # 第二次状态检查：同一连接防抖，不再重复触发
    response = client.post("/api/connector/status")
    data = response.json()
    assert data["auto_sync"]["triggered"] is False
    assert len(triggered) == 1
    assert triggered[0]["remote_tub"] == "data"


def test_status_auto_sync_not_triggered_when_disabled_or_offline(monkeypatch, tmp_path):
    client, connector = make_client(monkeypatch, tmp_path)
    triggered = _install_auto_sync_fakes(monkeypatch, connector)

    class FakeRemoteCarClient:
        def __init__(self, config):
            self.config = config

        def check_connection(self):
            return False, "unreachable"

    monkeypatch.setattr(connector, "RemoteCarClient", FakeRemoteCarClient)
    client.post(
        "/api/connector/config",
        json={"host": "car.local", "user": "pi", "port": 22, "car_dir": "~/mycar", "auto_sync": True},
    )

    # 离线：即使 auto_sync 开启也不触发
    response = client.post("/api/connector/status")
    assert response.json()["auto_sync"]["triggered"] is False
    assert len(triggered) == 0


def test_status_auto_sync_skipped_when_pull_job_running(monkeypatch, tmp_path):
    client, connector = make_client(monkeypatch, tmp_path)
    _install_auto_sync_fakes(monkeypatch, connector)

    class FakeRemoteCarClient:
        def __init__(self, config):
            self.config = config

        def check_connection(self):
            return True, "Connected"

    monkeypatch.setattr(connector, "RemoteCarClient", FakeRemoteCarClient)
    client.post(
        "/api/connector/config",
        json={"host": "car.local", "user": "pi", "port": 22, "car_dir": "~/mycar", "auto_sync": True},
    )

    # 已有 pull 任务在跑 → 不自动入队
    manager = connector.connector_job_manager
    existing = manager.create_job("pull_tub")
    try:
        response = client.post("/api/connector/status")
        assert response.json()["auto_sync"]["triggered"] is False
    finally:
        manager.jobs.pop(existing.id, None)


def test_try_begin_auto_sync_debounce_and_end():
    import connector_engine

    manager = connector_engine.ConnectorJobManager()
    manager.auto_sync_keys = set()
    manager.jobs = {}

    # 同一 key 第二次触发被防抖拒绝
    assert manager.try_begin_auto_sync("pi@car:22:~/mycar") is True
    assert manager.try_begin_auto_sync("pi@car:22:~/mycar") is False

    # 结束后可再次触发
    manager.end_auto_sync("pi@car:22:~/mycar")
    assert manager.try_begin_auto_sync("pi@car:22:~/mycar") is True
    manager.end_auto_sync("pi@car:22:~/mycar")

    # 有 pull 任务在跑时拒绝
    job = manager.create_job("pull_tub")
    try:
        assert manager.try_begin_auto_sync("other") is False
    finally:
        manager.jobs.pop(job.id, None)


def test_run_auto_sync_records_stats_and_calls_callback(monkeypatch):
    import asyncio

    import connector_engine
    from connector_engine import ConnectorJobManager
    from remote_car_client import ConnectorConfig

    class FakeStatsStdout:
        def __init__(self):
            self.lines = [
                b"Number of files: 5 (reg: 4, dir: 1)",
                b"Number of regular files transferred: 2",
                b"Total file size: 1000 bytes",
                b"Total transferred file size: 400 bytes",
                b"",
            ]

        async def readline(self):
            return self.lines.pop(0)

    class FakeStatsProcess:
        stdout = FakeStatsStdout()
        returncode = 0

        async def wait(self):
            return 0

    async def create_process(*args, **kwargs):
        return FakeStatsProcess()

    async def fake_ensure_rsync(job, config):
        return True

    results = []

    async def run_job():
        manager = ConnectorJobManager()
        monkeypatch.setattr(connector_engine.asyncio, "create_subprocess_exec", create_process)
        monkeypatch.setattr(manager, "_ensure_rsync_available", fake_ensure_rsync)

        job = await manager.run_auto_sync(
            "pi@car:22:~/mycar",
            ConnectorConfig(host="car.local", user="pi", car_dir="~/mycar"),
            "data",
            "./data",
            on_finished=lambda j: results.append((j.status, j.transfer_stats)),
        )
        return manager, job

    manager, job = asyncio.run(run_job())

    assert job.status == "completed"
    assert job.transfer_stats == {
        "transferred_files": 2,
        "total_files": 5,
        "transferred_bytes": 400,
        "total_size": 1000,
    }
    assert results == [("completed", job.transfer_stats)]
    # 自动同步结束后防抖 key 已释放
    assert "pi@car:22:~/mycar" not in manager.auto_sync_keys


def test_auto_sync_endpoint_round_trip(monkeypatch, tmp_path):
    client, _ = make_client(monkeypatch, tmp_path)

    # 默认关闭
    loaded = client.get("/api/connector/config")
    assert loaded.json()["config"]["auto_sync"] is False

    # 打开开关
    response = client.post("/api/connector/auto_sync", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["auto_sync"]["enabled"] is True
    assert response.json()["last_sync"] == {"at": None, "result": None}

    # 开关状态随配置持久化
    loaded = client.get("/api/connector/config")
    assert loaded.json()["config"]["auto_sync"] is True

    # 关闭开关
    response = client.post("/api/connector/auto_sync", json={"enabled": False})
    assert response.json()["auto_sync"]["enabled"] is False


def test_record_last_sync_persists_result(monkeypatch, tmp_path):
    from connector_engine import ConnectorJobManager

    client, connector = make_client(monkeypatch, tmp_path)
    client.post(
        "/api/connector/config",
        json={"host": "car.local", "user": "pi", "port": 22, "car_dir": "~/mycar"},
    )

    manager = ConnectorJobManager()
    job = manager.create_job("pull_tub")
    job.status = "completed"
    job.transfer_stats = {"transferred_files": 3, "total_files": 4, "transferred_bytes": 100, "total_size": 200}
    connector._record_last_sync(job)

    loaded = client.get("/api/connector/config").json()["config"]
    assert loaded["last_sync_at"] is not None
    assert "同步成功" in loaded["last_sync_result"]
    assert "3/4" in loaded["last_sync_result"]

    failed = manager.create_job("pull_tub")
    failed.status = "failed"
    failed.error_message = "rsync 退出码: 23"
    connector._record_last_sync(failed)
    loaded = client.get("/api/connector/config").json()["config"]
    assert "同步失败" in loaded["last_sync_result"]
    assert "rsync 退出码: 23" in loaded["last_sync_result"]
