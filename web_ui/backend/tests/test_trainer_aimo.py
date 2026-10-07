"""AIMO cloud NPU conversion endpoints (POST /train/aimo, GET /aimo/key-status)."""
import sys
from pathlib import Path

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


def test_start_aimo_convert_creates_job():
    with _build_client() as client:
        resp = client.post("/api/trainer/train/aimo", json={
            "model_path": "./models/pilot.tflite",
            "working_dir": "/tmp",
        })

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("pending", "running")
    job_id = body["job_id"]

    from trainer_engine import job_manager
    job = job_manager.get_job(job_id)
    assert job is not None
    assert job.mode == "aimo"
    # 子进程会很快失败退出（/tmp 下没有 ./models/pilot.tflite 转换 SDK），
    # 只断言命令行组装不实际等待其结束
    assert job.process is not None or job.status in ("running", "pending", "failed")


def test_start_aimo_convert_rejects_blank_model_path():
    with _build_client() as client:
        resp = client.post("/api/trainer/train/aimo", json={"model_path": "   "})

    assert resp.status_code == 400


def test_start_aimo_convert_rejects_bad_precision():
    with _build_client() as client:
        resp = client.post("/api/trainer/train/aimo", json={
            "model_path": "./models/pilot.tflite",
            "precision": "INT4",
        })

    assert resp.status_code == 400


def test_key_status_shape_and_never_leaks_key(monkeypatch):
    monkeypatch.setenv("AIMO_API_KEY", "secret-key-value")
    with _build_client() as client:
        resp = client.get("/api/trainer/aimo/key-status")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"sdk", "key", "keySource"}
    assert body["key"] is True
    assert body["keySource"] == "env"
    assert "secret-key-value" not in resp.text


def test_key_status_reports_missing(monkeypatch):
    monkeypatch.delenv("AIMO_API_KEY", raising=False)
    monkeypatch.delenv("AIMO_KEY_FILE", raising=False)
    # 指向不存在的密钥文件，避免开发机上的真实凭据影响断言
    monkeypatch.setenv("AIMO_KEY_FILE", "/nonexistent/aimo_api_key")
    with _build_client() as client:
        resp = client.get("/api/trainer/aimo/key-status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] is False
    assert body["keySource"] is None
    # sdk 是否可用取决于机器环境，只要求字段存在且为布尔
    assert isinstance(body["sdk"], bool)


def test_job_status_includes_result_path():
    from trainer_engine import job_manager, TrainingJob

    job = TrainingJob(id="aimo-res", mode="aimo", status="completed")
    job.result_path = "/tmp/models/pilot.aidem"
    job_manager.jobs[job.id] = job
    try:
        with _build_client() as client:
            resp = client.get("/api/trainer/train/aimo-res/status")
    finally:
        job_manager.jobs.pop(job.id, None)

    assert resp.status_code == 200
    assert resp.json()["result_path"] == "/tmp/models/pilot.aidem"


def test_parse_aimo_line_stages_and_result():
    from trainer_engine import TrainingJob, job_manager

    job = TrainingJob(id="aimo-parse", mode="aimo")
    parse = job_manager._parse_aimo_line

    parse(job, "[0/5] 源模型类型: SourceModelType.TensorFlow_Lite  (pilot.tflite)")
    assert job.progress.global_percent == 0.0
    parse(job, "[2.5/5] 校准集已上传: 100 张 -> 1 个 URL")
    assert job.progress.global_percent == 50.0
    parse(job, "[3/5] 已提交，轮询中（间隔 15s，上限 3600s）...")
    assert job.progress.global_percent == 60.0
    assert job.result_path is None

    parse(job, "[5/5] 已下载到: /home/me/models/pilot.ctx.bin.aidem")
    assert job.result_path == "/home/me/models/pilot.ctx.bin.aidem"
    assert job.progress.global_percent == 100.0

    # 非阶段行不应影响进度
    parse(job, "      [  30s] Pending  conversion queued")
    assert job.progress.global_percent == 100.0
