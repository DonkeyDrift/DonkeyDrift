import json
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import mypc_history


def _build_client():
    from routers import trainer as trainer_router

    app = FastAPI()
    app.include_router(trainer_router.router, prefix="/api/trainer")
    return TestClient(app)


def _read_history_file() -> str:
    return Path(mypc_history._history_path()).read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# mypc_history.save_known_host / load_known_hosts
# ----------------------------------------------------------------------
def test_save_and_load_sorted_by_last_used_desc():
    mypc_history.save_known_host("host-a", "ua", "/bin/python")
    mypc_history.save_known_host("host-b", "ub")

    entries = mypc_history.load_known_hosts()

    assert [e["host"] for e in entries] == ["host-b", "host-a"]
    assert entries[1]["user"] == "ua"
    assert entries[1]["python_path"] == "/bin/python"
    assert entries[0]["last_used_at"] >= entries[1]["last_used_at"]


def test_save_upserts_by_host():
    mypc_history.save_known_host("host-a", "ua")
    mypc_history.save_known_host("host-b", "ub")
    mypc_history.save_known_host("host-a", "ua2")

    entries = mypc_history.load_known_hosts()

    assert len(entries) == 2
    assert entries[0]["host"] == "host-a"  # most recently used comes first
    assert entries[0]["user"] == "ua2"


def test_save_keeps_old_python_path_and_remote_dir_when_empty():
    mypc_history.save_known_host("host-a", "ua", "/usr/bin/python3", "~/projects")
    mypc_history.save_known_host("host-a", "ua")

    entry = mypc_history.load_known_hosts()[0]
    assert entry["python_path"] == "/usr/bin/python3"
    assert entry["remote_dir_base"] == "~/projects"

    mypc_history.save_known_host("host-a", "ua", "/custom/python", "~/work")
    entry = mypc_history.load_known_hosts()[0]
    assert entry["python_path"] == "/custom/python"
    assert entry["remote_dir_base"] == "~/work"


def test_save_caps_at_max_entries_dropping_oldest():
    for i in range(mypc_history.MAX_KNOWN_HOSTS + 2):
        mypc_history.save_known_host(f"host-{i:02d}", "u")

    entries = mypc_history.load_known_hosts()

    assert len(entries) == mypc_history.MAX_KNOWN_HOSTS
    hosts = [e["host"] for e in entries]
    assert "host-00" not in hosts  # oldest dropped first
    assert "host-01" not in hosts
    assert hosts[0] == f"host-{mypc_history.MAX_KNOWN_HOSTS + 1:02d}"


def test_save_is_atomic_and_survives_write_errors(tmp_path, monkeypatch):
    mypc_history.save_known_host("host-a", "ua")
    path = mypc_history._history_path()
    before = Path(path).read_text()

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(json, "dump", boom)
    # Must not raise, and the existing file must stay intact.
    mypc_history.save_known_host("host-b", "ub")

    assert Path(path).read_text() == before
    # No temp file left behind
    leftovers = [p for p in Path(path).parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
    assert [e["host"] for e in mypc_history.load_known_hosts()] == ["host-a"]


def test_save_creates_missing_directory(tmp_path, monkeypatch):
    nested = tmp_path / "a" / "b" / "mypc_known_hosts.json"
    monkeypatch.setattr(mypc_history, "_history_path", lambda: str(nested))

    mypc_history.save_known_host("host-a", "ua")

    assert nested.is_file()
    assert mypc_history.load_known_hosts()[0]["host"] == "host-a"


def test_load_returns_empty_on_missing_or_corrupt_file(tmp_path):
    assert mypc_history.load_known_hosts() == []

    path = Path(mypc_history._history_path())
    path.write_text("{ not json")
    assert mypc_history.load_known_hosts() == []

    path.write_text(json.dumps({"not": "a list"}))
    assert mypc_history.load_known_hosts() == []


def test_history_never_stores_password():
    """安全红线：写出的 JSON 永远不含 password；旧版文件残留的 password
    字段加载时丢弃、重写时彻底清掉。"""
    mypc_history.save_known_host("host-a", "ua", "/bin/python", "~/projects")

    raw = _read_history_file()
    assert "password" not in raw
    entry = mypc_history.load_known_hosts()[0]
    assert "password" not in entry

    # 旧版本文件里残留的 password 字段：加载丢弃 + 任何重写都清掉
    path = Path(mypc_history._history_path())
    path.write_text(json.dumps([{
        "host": "legacy-host", "user": "lu", "password": "testpass123",
        "python_path": "/legacy/python", "last_used_at": 1,
    }]))
    loaded = mypc_history.load_known_hosts()
    assert loaded[0]["host"] == "legacy-host"
    assert "password" not in loaded[0]

    mypc_history.save_known_host("host-b", "ub")
    assert "password" not in _read_history_file()


# ----------------------------------------------------------------------
# GET /api/trainer/mypc/known-hosts
# ----------------------------------------------------------------------
class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_known_hosts_endpoint_marks_reachability():
    mypc_history.save_known_host("offline-host", "u1", "/py/one")
    mypc_history.save_known_host("online-host", "u2", "/py/two", "~/projects")

    calls = []

    def fake_create_connection(address, timeout=None):
        calls.append((address, timeout))
        host, port = address
        assert port == 22
        if host == "offline-host":
            raise OSError("unreachable")
        return _FakeConn()

    with _build_client() as client, \
         patch("socket.create_connection", side_effect=fake_create_connection):
        resp = client.get("/api/trainer/mypc/known-hosts")

    assert resp.status_code == 200
    hosts = resp.json()["hosts"]
    # still sorted by last_used_at desc: online-host saved last
    assert [h["host"] for h in hosts] == ["online-host", "offline-host"]
    by_host = {h["host"]: h for h in hosts}
    assert by_host["online-host"]["reachable"] is True
    assert by_host["offline-host"]["reachable"] is False
    entry = by_host["online-host"]
    assert entry["user"] == "u2"
    assert entry["python_path"] == "/py/two"
    assert entry["remote_dir_base"] == "~/projects"
    assert "password" not in entry
    assert entry["last_used_at"] > 0
    assert calls and all(t == 1.5 for _, t in calls)


def test_known_hosts_endpoint_empty_history():
    with _build_client() as client:
        resp = client.get("/api/trainer/mypc/known-hosts")

    assert resp.status_code == 200
    assert resp.json() == {"hosts": []}


# ----------------------------------------------------------------------
# Save hooks wired into probe / train-start / resume routes
# ----------------------------------------------------------------------
def test_probe_route_saves_host_on_ssh_ok():
    from mypc_probe import ProbeCheck, ProbeResult

    def fake_probe(host, user, password, remote_dir_base="~/projects",
                   python_path="", port=22, key_path=""):
        return ProbeResult(
            ok=True,
            platform="linux",
            shell="posix",
            checks=[ProbeCheck(name="ssh", status="ok", message="connected")],
            python_path="/usr/bin/python3",
        )

    with _build_client() as client, \
         patch("routers.trainer.probe_mypc_environment", side_effect=fake_probe):
        resp = client.post("/api/trainer/mypc/probe", json={
            "host": "192.0.2.10", "user": "u", "password": "testpass123",
            "remote_dir_base": "~/work",
        })

    assert resp.status_code == 200
    entries = mypc_history.load_known_hosts()
    assert len(entries) == 1
    assert entries[0]["host"] == "192.0.2.10"
    assert entries[0]["python_path"] == "/usr/bin/python3"
    assert entries[0]["remote_dir_base"] == "~/work"
    assert "password" not in _read_history_file()


def test_probe_route_does_not_save_on_ssh_failure():
    from mypc_probe import ProbeCheck, ProbeResult

    def fake_probe(host, user, password, remote_dir_base="~/projects",
                   python_path="", port=22, key_path=""):
        return ProbeResult(
            ok=False,
            checks=[ProbeCheck(name="ssh", status="fail", message="refused")],
        )

    with _build_client() as client, \
         patch("routers.trainer.probe_mypc_environment", side_effect=fake_probe):
        resp = client.post("/api/trainer/mypc/probe", json={
            "host": "192.0.2.10", "user": "u", "password": "testpass123",
        })

    assert resp.status_code == 200
    assert mypc_history.load_known_hosts() == []


def test_start_mypc_train_saves_host():
    def fake_run_mypc(job, config_file="train_my_pc.conf", working_dir=None,
                      ssh_credentials=None, tub=None):
        pass

    with _build_client() as client, \
         patch("trainer_engine.job_manager.run_mypc", side_effect=fake_run_mypc):
        resp = client.post("/api/trainer/train/mypc", json={
            "ssh": {"host": "192.0.2.20", "user": "me", "password": "testpass123"},
        })

    assert resp.status_code == 200
    entries = mypc_history.load_known_hosts()
    assert len(entries) == 1
    assert entries[0]["host"] == "192.0.2.20"
    assert entries[0]["user"] == "me"
    assert "password" not in entries[0]
    assert "password" not in _read_history_file()


def test_start_mypc_resume_saves_host():
    def fake_run_resume(job, config_file="train_my_pc.conf", working_dir=None,
                        ssh_credentials=None, tub=None):
        pass

    with _build_client() as client, \
         patch("trainer_engine.job_manager.run_mypc_resume", side_effect=fake_run_resume):
        resp = client.post("/api/trainer/train/mypc/resume", json={
            "ssh": {"host": "192.0.2.21", "user": "me", "password": "testpass123"},
        })

    assert resp.status_code == 200
    entries = mypc_history.load_known_hosts()
    assert len(entries) == 1
    assert entries[0]["host"] == "192.0.2.21"
    assert "password" not in _read_history_file()


def test_start_mypc_train_without_ssh_saves_nothing():
    def fake_run_mypc(job, config_file="train_my_pc.conf", working_dir=None,
                      ssh_credentials=None, tub=None):
        pass

    with _build_client() as client, \
         patch("trainer_engine.job_manager.run_mypc", side_effect=fake_run_mypc):
        resp = client.post("/api/trainer/train/mypc", json={})

    assert resp.status_code == 200
    assert mypc_history.load_known_hosts() == []
