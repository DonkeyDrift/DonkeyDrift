# -*- coding: utf-8 -*-
"""latency_bench 冒烟测试。

自建一个小的 KerasLinear → TFLite 模型，验证基准函数能跑通且指标合理，
不依赖 mycar 真实工程或相机硬件，因此默认纳入常规套件。
"""
import numpy as np
import pytest

from donkeycar.parts.interpreter import keras_to_tflite
from donkeycar.parts.keras import KerasLinear, KerasInterpreter
from donkeycar.benchmarks import latency_bench as lb


@pytest.fixture(scope="module")
def tflite_model(tmp_path_factory) -> str:
    """构造一个 120x160x3 的 KerasLinear 并导出为 tflite。"""
    path = tmp_path_factory.mktemp("latency_bench") / "model.tflite"
    interpreter = KerasInterpreter()
    KerasLinear(interpreter=interpreter)
    keras_to_tflite(interpreter.model, str(path))
    return str(path)


def test_model_type_for_path():
    assert lb.model_type_for_path("a/b/model.tflite") == "tflite_linear"
    assert lb.model_type_for_path("model.TRT") == "tensorrt_linear"
    assert lb.model_type_for_path("model.h5") == "linear"
    assert lb.model_type_for_path("model.unknown") is None


def test_percentile_stats_ordering():
    stats = lb.percentile_stats([1.0, 2.0, 3.0, 4.0, 100.0])
    assert stats["n"] == 5
    assert stats["min"] == 1.0
    assert stats["max"] == 100.0
    assert stats["p50"] <= stats["p95"] <= stats["p99"] <= stats["max"]
    assert stats["fps"] == pytest.approx(1000.0 / stats["mean"])


def test_percentile_stats_rejects_empty():
    with pytest.raises(ValueError):
        lb.percentile_stats([])


def test_bench_inference(tflite_model):
    cfg = lb.make_cfg(width=160, height=120, depth=3)
    res = lb.bench_inference(tflite_model, "tflite_linear", cfg=cfg,
                             iterations=30, warmup=5)
    assert res["type"] == "tflite_linear"
    assert res["input_shape"] == (120, 160, 3)
    assert res["load_ms"] > 0
    assert res["n"] == 30
    assert res["p50"] > 0
    assert res["p95"] >= res["p50"]
    assert res["max"] >= res["p95"]


def test_bench_inference_uses_given_image(tflite_model):
    cfg = lb.make_cfg(width=160, height=120, depth=3)
    img = np.zeros((120, 160, 3), dtype=np.uint8)
    res = lb.bench_inference(tflite_model, "tflite_linear", cfg=cfg, image=img,
                             iterations=10, warmup=2)
    assert res["n"] == 10
    assert res["p50"] > 0


def test_bench_drive_loop(tflite_model):
    cfg = lb.make_cfg(width=320, height=240, depth=3)
    rate, iters = 30, 30
    res = lb.bench_drive_loop(tflite_model, "tflite_linear", cfg=cfg,
                              rate_hz=rate, iterations=iters)
    assert res["count"] == iters
    assert res["total_s"] > 0
    # 主循环受 1/rate 节拍约束，达成频率不应超过目标（留 10% 抖动余量），
    # 也不应慢到离谱（极宽松下界，避免在负载高的 CI 上误报）
    assert rate * 0.2 < res["achieved_hz"] <= rate * 1.1
    assert "PilotHolder" in res["parts"]
    holder = res["parts"]["PilotHolder"]
    assert holder["p50"] > 0
    assert holder["max"] >= holder["p50"]


def test_format_helpers(tflite_model):
    cfg = lb.make_cfg(width=160, height=120, depth=3)
    text = lb.format_inference(
        lb.bench_inference(tflite_model, cfg=cfg, iterations=5, warmup=1))
    assert "p95" in text and "fps" in text

    loop = lb.bench_drive_loop(tflite_model, cfg=cfg, rate_hz=30, iterations=10)
    assert "实测" in lb.format_loop(loop)
