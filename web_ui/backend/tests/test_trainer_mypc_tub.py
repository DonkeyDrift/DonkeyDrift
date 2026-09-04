import asyncio
import sys
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest
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


def test_run_online_systemexit_marks_job_failed(monkeypatch):
    """A trainer thread dying via sys.exit(1) (SystemExit is not an Exception
    subclass) must surface as a failed job instead of a silent 'completed'."""
    import trainer_engine
    from trainer_engine import job_manager

    captured = {}

    class FakeTrainer:
        def __init__(self, config_file="train_online.conf", log_queue=None,
                     working_dir=None, ssh_credentials=None, tub=None):
            captured["tub"] = tub

        def run(self, no_interactive=True):
            raise SystemExit(1)

    monkeypatch.setattr(trainer_engine, "WebOnlineTrainer", FakeTrainer)

    job = job_manager.create_job("mypc")
    asyncio.run(job_manager.run_online(job, working_dir="/tmp", tub="./data/tub_x"))

    assert job.status == "failed"
    assert job.error_message
    assert captured["tub"] == "./data/tub_x"


def test_run_online_systemexit_zero_stays_completed(monkeypatch):
    """sys.exit(0) / bare SystemExit is a normal exit and must not fail the job."""
    import trainer_engine
    from trainer_engine import job_manager

    class FakeTrainer:
        def __init__(self, **kwargs):
            pass

        def run(self, no_interactive=True):
            raise SystemExit(0)

    monkeypatch.setattr(trainer_engine, "WebOnlineTrainer", FakeTrainer)

    job = job_manager.create_job("online")
    asyncio.run(job_manager.run_online(job, working_dir="/tmp"))

    assert job.status == "completed"
    assert job.error_message is None


def test_run_online_runtime_error_surfaces_real_reason(monkeypatch):
    """trainer.run() 抛 RuntimeError 时，job 必须 failed 且 error_message
    是真实失败原因（而不是笼统的 exit code）。"""
    import trainer_engine
    from trainer_engine import job_manager

    class FakeTrainer:
        def __init__(self, **kwargs):
            pass

        def run(self, no_interactive=True):
            raise RuntimeError("创建远程目录失败: donkey 不存在")

    monkeypatch.setattr(trainer_engine, "WebOnlineTrainer", FakeTrainer)

    job = job_manager.create_job("mypc")
    asyncio.run(job_manager.run_online(job, working_dir="/tmp"))

    assert job.status == "failed"
    assert "创建远程目录失败" in job.error_message


def test_web_online_trainer_run_converts_systemexit_to_real_reason(tmp_path, monkeypatch):
    """父类 run() 的失败路径（_log('Process failed: ...', success=False) 后
    sys.exit(1)）必须被 WebOnlineTrainer.run 转成 RuntimeError，message 为
    去掉 'Process failed: ' 前缀后的真实原因。"""
    import donkeycar.management.train_online as train_online
    from web_online_trainer import WebOnlineTrainer

    # OnlineTrainer.__init__ 在 cwd 下自动创建默认 conf
    monkeypatch.chdir(tmp_path)

    def fake_parent_run(self, no_interactive=False):
        self._log("Process failed: 远程爆炸", success=False)
        sys.exit(1)

    monkeypatch.setattr(train_online.OnlineTrainer, "run", fake_parent_run)

    trainer = WebOnlineTrainer(config_file="train_test.conf")

    with pytest.raises(RuntimeError) as exc_info:
        trainer.run()
    assert str(exc_info.value) == "远程爆炸"


def test_mypc_route_passes_tub():
    captured = {}

    def fake_run_mypc(job, config_file="train_my_pc.conf", working_dir=None,
                      ssh_credentials=None, tub=None):
        captured["tub"] = tub

    with _build_client() as client, \
         patch("trainer_engine.job_manager.run_mypc", side_effect=fake_run_mypc):
        resp = client.post("/api/trainer/train/mypc", json={
            "config_file": "train_my_pc.conf",
            "tub": "./data/tub_x",
        })

    assert resp.status_code == 200
    assert captured["tub"] == "./data/tub_x"


def test_mypc_route_tub_defaults_to_none():
    captured = {}

    def fake_run_mypc(job, config_file="train_my_pc.conf", working_dir=None,
                      ssh_credentials=None, tub=None):
        captured["tub"] = tub

    with _build_client() as client, \
         patch("trainer_engine.job_manager.run_mypc", side_effect=fake_run_mypc):
        resp = client.post("/api/trainer/train/mypc", json={})

    assert resp.status_code == 200
    assert captured["tub"] is None


def test_online_route_passes_tub():
    captured = {}

    def fake_run_online(job, config_file="train_online.conf", working_dir=None,
                        ssh_credentials=None, tub=None):
        captured["tub"] = tub

    with _build_client() as client, \
         patch("trainer_engine.job_manager.run_online", side_effect=fake_run_online):
        resp = client.post("/api/trainer/train/online", json={
            "tub": "./data/tub_y",
        })

    assert resp.status_code == 200
    assert captured["tub"] == "./data/tub_y"


def test_package_data_uses_custom_data_dir(tmp_path, monkeypatch):
    """package_data must pack trainer.data_dir (a selected tub) while keeping
    the tar arcname rooted at 'data' so the remote layout stays unchanged."""
    from donkeycar.management.train_online import OnlineTrainer

    monkeypatch.chdir(tmp_path)

    tub_dir = tmp_path / "data" / "tub_x"
    tub_dir.mkdir(parents=True)
    (tub_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (tub_dir / "catalog_0.catalog").write_text("dummy", encoding="utf-8")

    trainer = OnlineTrainer(config_file="train_test.conf")
    trainer.data_dir = "./data/tub_x"

    tar_path, _ = trainer.package_data()

    assert Path(tar_path).is_file()
    with tarfile.open(tar_path, "r:gz") as tar:
        names = tar.getnames()
    assert "data" in names
    assert "data/manifest.json" in names
    assert "data/catalog_0.catalog" in names
