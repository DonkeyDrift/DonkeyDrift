import asyncio
import queue
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import mypc_installer
from mypc_installer import build_install_command


# ----------------------------------------------------------------------
# Fakes for the paramiko SSH layer
# ----------------------------------------------------------------------
class FakeChannel:
    def __init__(self, data: bytes, exit_code: int):
        self._data = data
        self.exit_code = exit_code
        self.closed = False

    def recv_ready(self):
        return len(self._data) > 0

    def recv(self, n):
        chunk, self._data = self._data[:n], self._data[n:]
        return chunk

    def exit_status_ready(self):
        return len(self._data) == 0

    def recv_exit_status(self):
        return self.exit_code

    def close(self):
        self.closed = True


class FakeStdout:
    def __init__(self, channel):
        self.channel = channel


class FakeSsh:
    def __init__(self, data: bytes = b"", exit_code: int = 0):
        self.channel = FakeChannel(data, exit_code)
        self.commands = []
        self.closed = False

    def exec_command(self, command, get_pty=False, timeout=None):
        self.commands.append(command)
        return None, FakeStdout(self.channel), None

    def close(self):
        self.closed = True


def _install(ssh, **kwargs):
    """Run install_mypc_environment with a fake SSH client and log queue."""
    logs = queue.Queue()
    defaults = dict(
        host="192.168.1.10",
        user="u",
        password="p",
        python_path="/usr/bin/python3",
        log_queue=logs,
    )
    defaults.update(kwargs)
    with patch.object(mypc_installer, "_open_ssh", return_value=ssh):
        code = mypc_installer.install_mypc_environment(**defaults)
    drained = []
    while not logs.empty():
        drained.append(logs.get())
    return code, drained


# ----------------------------------------------------------------------
# Command construction
# ----------------------------------------------------------------------
def test_build_install_command_quotes_python_and_extra():
    cmd = build_install_command("/opt/my python/bin/python3")
    assert cmd == '"/opt/my python/bin/python3" -m pip install --upgrade "donkeydrifter[pc]"'


def test_build_install_command_default_package_is_pc_extra():
    cmd = build_install_command("python3")
    assert "-m pip install --upgrade" in cmd
    assert "donkeydrifter[pc]" in cmd


# ----------------------------------------------------------------------
# Installer behaviour
# ----------------------------------------------------------------------
def test_install_success_streams_lines_and_closes_ssh():
    ssh = FakeSsh(b"Collecting donkeydrifter\nInstalling collected packages\n", exit_code=0)
    code, logs = _install(ssh)

    assert code == 0
    assert ssh.closed is True
    assert len(ssh.commands) == 1
    assert '"donkeydrifter[pc]"' in ssh.commands[0]
    assert "/usr/bin/python3" in ssh.commands[0]
    lines = [e["line"] for e in logs]
    assert "Collecting donkeydrifter" in lines
    assert "Installing collected packages" in lines
    assert any(e.get("level") == "success" and "安装完成" in e["line"] for e in logs)


def test_install_pip_failure_returns_exit_code_and_error_log():
    ssh = FakeSsh(b"ERROR: Could not find a version\n", exit_code=1)
    code, logs = _install(ssh)

    assert code == 1
    assert any("退出码: 1" in e["line"] for e in logs)
    assert not any(e.get("level") == "success" for e in logs)


def test_install_missing_python_path_raises():
    with pytest.raises(ValueError):
        _install(FakeSsh(), python_path="  ")


def test_install_ssh_failure_propagates():
    def _boom(*args, **kwargs):
        raise ConnectionError("connection refused")

    with patch.object(mypc_installer, "_open_ssh", side_effect=_boom), \
         pytest.raises(ConnectionError):
        mypc_installer.install_mypc_environment(
            host="h", user="u", password="p", python_path="/usr/bin/python3")


def test_install_cleans_ansi_and_progress_carriage():
    ssh = FakeSsh(b"\x1b[32mDownloading...\rDownloading 50%\n", exit_code=0)
    code, logs = _install(ssh)

    assert code == 0
    lines = [e["line"] for e in logs]
    assert "Downloading 50%" in lines
    assert all("\x1b" not in line for line in lines)


# ----------------------------------------------------------------------
# Job engine: run_mypc_install bridges worker logs into the job queue
# ----------------------------------------------------------------------
def _run_engine(install_result=0, install_exc=None):
    from trainer_engine import TrainingJob, TrainingJobManager

    def fake_install(**kwargs):
        q = kwargs["log_queue"]
        q.put({"type": "log", "line": "Collecting donkeydrifter", "level": "info"})
        if install_exc:
            raise install_exc
        return install_result

    manager = TrainingJobManager()
    job = TrainingJob(id="test1234", mode="mypc_install")

    async def run():
        with patch.object(mypc_installer, "install_mypc_environment", side_effect=fake_install):
            await manager.run_mypc_install(job, host="h", user="u", password="p",
                                           python_path="/usr/bin/python3")

    asyncio.run(run())
    return job


def test_run_mypc_install_success_completes_job():
    job = _run_engine(install_result=0)

    assert job.status == "completed"
    assert "Collecting donkeydrifter" in job.logs


def test_run_mypc_install_pip_failure_fails_job():
    job = _run_engine(install_result=1)

    assert job.status == "failed"
    assert "退出码" in (job.error_message or "")


def test_run_mypc_install_exception_fails_job():
    job = _run_engine(install_exc=ConnectionError("connection refused"))

    assert job.status == "failed"
    assert "connection refused" in (job.error_message or "")


# ----------------------------------------------------------------------
# Router contract
# ----------------------------------------------------------------------
def _build_client():
    from routers import trainer as trainer_router

    app = FastAPI()
    app.include_router(trainer_router.router, prefix="/api/trainer")
    return TestClient(app)


def test_install_route_requires_python_path():
    client = _build_client()
    resp = client.post("/api/trainer/mypc/install", json={
        "host": "192.168.1.10", "user": "u", "password": "p", "python_path": "",
    })
    assert resp.status_code == 400
    assert "检测" in resp.json()["detail"]


def test_install_route_creates_job_and_forwards_args():
    client = _build_client()
    captured = {}

    from trainer_engine import TrainingJob

    def fake_create_job(mode):
        captured["mode"] = mode
        return TrainingJob(id="abc12345", mode=mode)

    async def fake_run(job, host, user, password, python_path, port=22, key_path=""):
        captured.update(job=job, host=host, user=user, password=password,
                        python_path=python_path, port=port, key_path=key_path)

    with patch("trainer_engine.job_manager.create_job", side_effect=fake_create_job), \
         patch("trainer_engine.job_manager.run_mypc_install", side_effect=fake_run):
        resp = client.post("/api/trainer/mypc/install", json={
            "host": "192.168.1.10", "user": "u", "password": "p",
            "python_path": "/usr/bin/python3", "port": 22,
        })

    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == "abc12345"
    assert captured["mode"] == "mypc_install"
    assert captured["python_path"] == "/usr/bin/python3"
    assert captured["host"] == "192.168.1.10"
