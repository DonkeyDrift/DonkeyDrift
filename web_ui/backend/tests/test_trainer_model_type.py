"""远程训练（mypc/online）模型类型 model_type 的传递与持久化。

覆盖三处：
1. run_remote_training 的训练命令 --type 取 conf 的 model_type（缺省 linear）；
2. run_resume 续训命令同样取 conf 的 model_type；
3. /api/trainer/config GET/POST 对 model_type 的读写与缺省值。
"""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _write_conf(tmp_path, extra=""):
    conf = tmp_path / "train_test.conf"
    conf.write_text(
        "[Remote]\n"
        "host = h\n"
        "user = u\n"
        "remote_dir_base = ~/projects\n"
        "model_name = mymodel\n"
        "python_path = /usr/bin/python\n"
        + extra,
        encoding="utf-8",
    )
    return conf


def _make_trainer(tmp_path, monkeypatch, extra=""):
    from web_online_trainer import WebOnlineTrainer
    monkeypatch.chdir(tmp_path)
    _write_conf(tmp_path, extra)
    return WebOnlineTrainer(config_file="train_test.conf", working_dir=str(tmp_path))


class _FakeChannel:
    def recv_exit_status(self):
        return 0


class _FakeStream:
    def __init__(self, text=""):
        self._text = text
        self.channel = _FakeChannel()

    def read(self):
        return self._text.encode()


class _FakeSSH:
    """exec_command 依次返回 scripted 中的 (stdout_text)；默认 exit 0、空输出。"""

    def __init__(self, scripted=None):
        self.scripted = list(scripted or [])
        self.commands = []

    def exec_command(self, cmd):
        self.commands.append(cmd)
        text = self.scripted.pop(0) if self.scripted else ""
        return (None, _FakeStream(text), _FakeStream())


def _run_remote_training(trainer, monkeypatch):
    captured = {}
    monkeypatch.setattr(trainer, "_resolve_remote_path", lambda p: p, raising=False)
    monkeypatch.setattr(trainer, "_check_remote_resources", lambda d: None, raising=False)
    monkeypatch.setattr(trainer, "_stream_remote_training", lambda cmd: captured.__setitem__("cmd", cmd))
    trainer.remote_work_dir = "/remote/dir"
    trainer.ssh_client = _FakeSSH()
    trainer.run_remote_training("/remote/dir/data.tar.gz")
    return captured["cmd"]


def test_run_remote_training_uses_configured_model_type(tmp_path, monkeypatch):
    trainer = _make_trainer(tmp_path, monkeypatch, extra="model_type = categorical\n")
    cmd = _run_remote_training(trainer, monkeypatch)
    assert "--type categorical" in cmd


def test_run_remote_training_defaults_to_linear(tmp_path, monkeypatch):
    trainer = _make_trainer(tmp_path, monkeypatch)
    cmd = _run_remote_training(trainer, monkeypatch)
    assert "--type linear" in cmd


def test_run_resume_uses_configured_model_type(tmp_path, monkeypatch):
    trainer = _make_trainer(tmp_path, monkeypatch, extra="model_type = rnn\n")
    captured = {}

    monkeypatch.setattr(trainer, "connect_ssh", lambda: None)
    monkeypatch.setattr(trainer, "_resolve_remote_path", lambda p: p, raising=False)
    monkeypatch.setattr(trainer, "_generate_unique_model_name", lambda n: n + "_r1", raising=False)
    monkeypatch.setattr(
        trainer, "_stream_remote_training",
        lambda cmd: captured.__setitem__("cmd", cmd))
    monkeypatch.setattr(trainer, "download_model", lambda name: None)

    # exec_command 依次：目录检查（exit 0）、ls -dt 找检查点（返回一个 SavedModel 目录）
    trainer.ssh_client = _FakeSSH(scripted=["", "/remote/dir/models/mymodel\n"])
    trainer.sftp_client = type("FakeSFTP", (), {"put": staticmethod(lambda l, r: None)})()

    session = {"remote_work_dir": "/remote/dir", "model_name": "mymodel",
               "tub": "./data", "host": "h"}
    trainer.run_resume(session)

    assert "--type rnn" in captured["cmd"]
    assert "--transfer /remote/dir/models/mymodel" in captured["cmd"]


def test_config_endpoint_roundtrips_model_type(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers import trainer as trainer_router

    monkeypatch.chdir(tmp_path)
    app = FastAPI()
    app.include_router(trainer_router.router, prefix="/api/trainer")

    with TestClient(app) as client:
        resp = client.post("/api/trainer/config", params={"config_file": "train_test.conf"}, json={
            "host": "h", "user": "u", "remote_dir_base": "~/projects",
            "model_name": "mymodel", "python_path": "/usr/bin/python",
            "model_type": "categorical",
        })
        assert resp.status_code == 200
        assert "model_type = categorical" in (tmp_path / "train_test.conf").read_text(encoding="utf-8")

        resp = client.get("/api/trainer/config", params={"config_file": "train_test.conf"})
        assert resp.status_code == 200
        assert resp.json()["model_type"] == "categorical"


def test_config_endpoint_defaults_model_type_to_linear(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers import trainer as trainer_router

    monkeypatch.chdir(tmp_path)
    _write_conf(tmp_path)  # 无 model_type 键的旧配置

    app = FastAPI()
    app.include_router(trainer_router.router, prefix="/api/trainer")
    with TestClient(app) as client:
        resp = client.get("/api/trainer/config", params={"config_file": "train_test.conf"})
        assert resp.status_code == 200
        assert resp.json()["model_type"] == "linear"
