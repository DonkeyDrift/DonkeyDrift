"""真实模型集成测试（opt-in）：需要本机存在 mycar 工程与 DKG-1 模型。

运行方式（默认跳过，不污染常规套件）：
    cd web_ui/backend && ARENA_INTEGRATION=1 python -m pytest tests/integration/test_arena_real_model.py -v
"""
import importlib
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

MYCAR = Path(os.environ.get("MYCAR_DIR", "/home/dkc/projects/mycar"))
MODEL = MYCAR / "models" / "DKG-1.tflite"

pytestmark = pytest.mark.skipif(
    os.environ.get("ARENA_INTEGRATION") != "1" or not MODEL.is_file(),
    reason="opt-in 集成测试：需 ARENA_INTEGRATION=1 且存在真实 mycar 工程与 DKG-1 模型",
)


def test_real_model_predict_latency_and_config_cache(caplog, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    arena = importlib.import_module("routers.arena")
    app = FastAPI()
    app.include_router(arena.router, prefix="/api/arena")
    client = TestClient(app)

    # 计数真实 load_config；图像与记录用按配置形状的占位数据
    real_load_config = arena.load_config
    calls = {"count": 0}

    def counting_load_config(config_file):
        calls["count"] += 1
        return real_load_config(config_file)

    # 先装计数器再取 cfg：让「全程仅 1 次 load_config」包含这次预取编译
    monkeypatch.setattr(arena, "load_config", counting_load_config)

    cfg = arena.load_car_config(str(MYCAR))
    monkeypatch.setattr(
        arena,
        "load_record_image",
        lambda record: np.zeros(
            (cfg.IMAGE_H, cfg.IMAGE_W, getattr(cfg, "IMAGE_DEPTH", 3)), dtype=np.uint8
        ),
    )
    monkeypatch.setattr(
        arena.tub_router,
        "current_records",
        [
            {
                "_index": i,
                "cam/image_array": f"{i}_cam_image_array_.jpg",
                "user/angle": 0.0,
                "user/throttle": 0.0,
            }
            for i in range(20)
        ],
    )
    monkeypatch.setattr(arena.tub_router, "current_tub_path", str(MYCAR))

    load_response = client.post(
        "/api/arena/pilots/load",
        json={
            "model_path": str(MODEL),
            "model_type": "tflite_linear",
            "config_path": str(MYCAR),
        },
    )
    assert load_response.status_code == 200, load_response.text
    pilot_id = load_response.json()["pilot"]["id"]

    def predict(index):
        return client.post(
            f"/api/arena/pilots/{pilot_id}/predict",
            json={"record_index": index, "config_path": str(MYCAR)},
        )

    with caplog.at_level(logging.INFO, logger="donkeycar.config"):
        for i in range(3):  # 预热（index 0..2）
            response = predict(i)
            assert response.status_code == 200, response.text

        start = time.perf_counter()
        for i in range(3, 20):  # 测量段：index 3..19，每帧都是真实模型 invoke
            response = predict(i)
            assert response.status_code == 200, response.text
        mean_ms = (time.perf_counter() - start) / 17 * 1000

    config_log_lines = [r for r in caplog.records if "loading config" in r.getMessage()]
    assert config_log_lines == [], f"predict 期间 config 日志刷屏：{len(config_log_lines)} 条"
    assert calls["count"] == 1, f"load_config 实际执行 {calls['count']} 次（应为 1 次）"
    assert mean_ms < 30, f"热缓存单帧 predict {mean_ms:.1f}ms，超出 30ms 预算"

    assert client.delete(f"/api/arena/pilots/{pilot_id}").status_code == 200
