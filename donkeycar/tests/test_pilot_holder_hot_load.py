"""PilotHolder 热加载与 DriveApiBridge load_model 消息的单测（issue #003）。

不加载真实 TensorFlow 模型：monkeypatch donkeycar.utils.get_model_by_type
返回假 pilot，专注验证「原子替换 / 空容器输出 / 失败保留旧模型 / ACK 回传」。
"""
import asyncio

import pytest

from donkeycar.parts.drive_api_bridge import DriveApiBridge
from donkeycar.parts.pilot_holder import PilotHolder


class FakePilot:
    def __init__(self, tag: str):
        self.tag = tag
        self.loaded_path = None
        self.shutdown_called = False

    def load(self, model_path):
        self.loaded_path = model_path

    def run(self, img_arr, *other):
        return (0.1, 0.2)

    def shutdown(self):
        self.shutdown_called = True


class FakeCfg:
    DEFAULT_MODEL_TYPE = "linear"
    TRAIN_LOCALIZER = False


def _patch_models(monkeypatch, created):
    import donkeycar.utils as dk_utils

    def fake_get_model_by_type(model_type, cfg):
        pilot = FakePilot(model_type)
        created.append(pilot)
        return pilot

    monkeypatch.setattr(dk_utils, "get_model_by_type", fake_get_model_by_type)


def test_empty_holder_returns_none_outputs(monkeypatch):
    created = []
    _patch_models(monkeypatch, created)
    holder = PilotHolder(FakeCfg(), output_count=2)

    assert holder.run("img") == (None, None)
    holder3 = PilotHolder(FakeCfg(), output_count=3)
    assert holder3.run("img") == (None, None, None)


def test_load_swaps_pilot_and_reports_type(monkeypatch):
    created = []
    _patch_models(monkeypatch, created)
    holder = PilotHolder(FakeCfg(), output_count=2)

    holder.load("/tmp/a.tflite", "tflite_linear")

    assert holder.run("img") == (0.1, 0.2)
    assert holder.model_path == "/tmp/a.tflite"
    assert holder.model_type == "tflite_linear"
    assert created[0].loaded_path == "/tmp/a.tflite"


def test_load_replaces_old_pilot_and_shuts_it_down(monkeypatch):
    created = []
    _patch_models(monkeypatch, created)
    holder = PilotHolder(FakeCfg(), output_count=2)
    holder.load("/tmp/a.h5")
    first = created[0]

    holder.load("/tmp/b.tflite", "tflite_linear")

    assert first.shutdown_called is True
    assert holder.model_path == "/tmp/b.tflite"


def test_failed_load_keeps_previous_pilot(monkeypatch):
    created = []
    _patch_models(monkeypatch, created)
    holder = PilotHolder(FakeCfg(), output_count=2)
    holder.load("/tmp/good.h5")

    import donkeycar.utils as dk_utils

    def boom(model_type, cfg):
        raise RuntimeError("bad model")

    monkeypatch.setattr(dk_utils, "get_model_by_type", boom)
    with pytest.raises(RuntimeError):
        holder.load("/tmp/bad.h5")

    assert holder.run("img") == (0.1, 0.2)
    assert holder.model_path == "/tmp/good.h5"


def test_initial_pilot_is_replaced_by_hot_load(monkeypatch):
    created = []
    _patch_models(monkeypatch, created)
    replay = FakePilot("replay")
    holder = PilotHolder(FakeCfg(), initial_pilot=replay)

    assert holder.current() is replay
    holder.load("/tmp/model.tflite", "tflite_linear")

    assert replay.shutdown_called is True
    assert holder.current() is created[0]
    assert holder.run("img") == (0.1, 0.2)


def test_legacy_json_uses_json_interpreter(monkeypatch):
    class FakeInterpreter:
        def __init__(self):
            self.loaded_path = None

        def load_json(self, model_path):
            self.loaded_path = model_path

    pilot = FakePilot("linear")
    pilot.interpreter = FakeInterpreter()

    import donkeycar.utils as dk_utils
    monkeypatch.setattr(dk_utils, "get_model_by_type", lambda *_: pilot)
    holder = PilotHolder(FakeCfg())

    holder.load("/tmp/legacy.json", "linear")

    assert pilot.interpreter.loaded_path == "/tmp/legacy.json"
    assert pilot.loaded_path is None
    assert holder.model_path == "/tmp/legacy.json"


class FakeLoader:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def load(self, model_path, model_type=None):
        self.calls.append((model_path, model_type))
        if self.fail:
            raise RuntimeError("load failed")


def _bridge_with_loader(loader):
    bridge = DriveApiBridge(auto_start=False)
    bridge.model_loader = loader
    sent = []
    bridge._send_json = sent.append
    return bridge, sent


def test_handle_load_model_sends_success_ack(tmp_path):
    model_file = tmp_path / "m.tflite"
    model_file.write_bytes(b"x")
    loader = FakeLoader()
    bridge, sent = _bridge_with_loader(loader)

    bridge._handle_message({
        "type": "load_model",
        "request_id": "r1",
        "model_path": str(model_file),
        "model_type": "tflite_linear",
    })

    assert loader.calls == [(str(model_file), "tflite_linear")]
    ack = [m for m in sent if m.get("type") == "model_loaded"]
    assert len(ack) == 1
    assert ack[0]["success"] is True
    assert ack[0]["request_id"] == "r1"


def test_handle_load_model_missing_file_reports_error(tmp_path):
    loader = FakeLoader()
    bridge, sent = _bridge_with_loader(loader)

    bridge._handle_message({
        "type": "load_model",
        "request_id": "r2",
        "model_path": str(tmp_path / "missing.tflite"),
    })

    assert loader.calls == []
    assert sent[-1]["success"] is False
    assert "不存在" in sent[-1]["error"]


def test_handle_load_model_without_loader_reports_error(tmp_path):
    model_file = tmp_path / "m.tflite"
    model_file.write_bytes(b"x")
    bridge, sent = _bridge_with_loader(None)

    bridge._handle_message({
        "type": "load_model",
        "request_id": "r3",
        "model_path": str(model_file),
    })

    assert sent[-1]["success"] is False


def test_handle_load_model_loader_exception_reports_error(tmp_path):
    model_file = tmp_path / "m.tflite"
    model_file.write_bytes(b"x")
    loader = FakeLoader(fail=True)
    bridge, sent = _bridge_with_loader(loader)

    bridge._handle_message({
        "type": "load_model",
        "request_id": "r4",
        "model_path": str(model_file),
    })

    assert sent[-1]["success"] is False
    assert "load failed" in sent[-1]["error"]


def test_restart_with_model_alias_hot_loads(tmp_path):
    model_file = tmp_path / "m.tflite"
    model_file.write_bytes(b"x")
    loader = FakeLoader()
    bridge, sent = _bridge_with_loader(loader)

    bridge._handle_message({"type": "restart_with_model", "model_path": str(model_file)})

    assert loader.calls == [(str(model_file), None)]
    assert sent[-1]["success"] is True


# ── 推理可观测性：周期日志默认关闭、PILOT_OBSERVE_INTERVAL 控制、冻结告警常开 ──

class _ObsCfg(FakeCfg):
    """带 PILOT_OBSERVE_INTERVAL 的配置基类。"""


def _observe_holder(monkeypatch, caplog, interval_value):
    """构造已加载假 pilot 的 holder，返回 (holder, frame)。"""
    created = []
    _patch_models(monkeypatch, created)

    cfg = _ObsCfg()
    if interval_value is not None:
        cfg.PILOT_OBSERVE_INTERVAL = interval_value
    holder = PilotHolder(cfg, output_count=2)
    holder.load("/fake/m.tflite", "linear")
    import numpy as np
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    return holder, frame


def test_observe_log_disabled_by_default(monkeypatch, caplog):
    """缺省（无配置键）时不打周期观测日志。"""
    import logging
    holder, frame = _observe_holder(monkeypatch, caplog, None)
    with caplog.at_level(logging.INFO, logger="donkeycar.parts.pilot_holder"):
        holder._obs_last_log -= 10.0  # 模拟早过了日志间隔
        holder._observe(frame, (0.05, 0.21))
    assert not any("pilot 观测" in r.message for r in caplog.records)


def test_observe_log_disabled_with_zero(monkeypatch, caplog):
    """PILOT_OBSERVE_INTERVAL = 0 时同样不打周期观测日志。"""
    import logging
    holder, frame = _observe_holder(monkeypatch, caplog, 0)
    with caplog.at_level(logging.INFO, logger="donkeycar.parts.pilot_holder"):
        holder._obs_last_log -= 10.0
        holder._observe(frame, (0.05, 0.21))
    assert not any("pilot 观测" in r.message for r in caplog.records)


def test_observe_log_enabled_by_interval(monkeypatch, caplog):
    """PILOT_OBSERVE_INTERVAL = 5 且到点时打印「pilot 观测」。"""
    import logging
    holder, frame = _observe_holder(monkeypatch, caplog, 5)
    with caplog.at_level(logging.INFO, logger="donkeycar.parts.pilot_holder"):
        holder._obs_last_log -= 10.0
        holder._observe(frame, (0.05, 0.21))
    assert any("pilot 观测" in r.message for r in caplog.records)


def test_freeze_warning_fires_even_when_log_disabled(monkeypatch, caplog):
    """周期日志关闭时帧冻结告警仍然生效（安全网常开）。"""
    import logging
    from donkeycar.parts.pilot_holder import _OBS_FREEZE_WARN_S
    holder, frame = _observe_holder(monkeypatch, caplog, 0)
    with caplog.at_level(logging.WARNING, logger="donkeycar.parts.pilot_holder"):
        holder._observe(frame, (0.05, 0.21))  # 登记对象 id
        holder._obs_fresh_since -= (_OBS_FREEZE_WARN_S + 0.5)
        holder._observe(frame, (0.05, 0.21))  # 同一对象且超时 → 告警
    assert any("冻结" in r.message for r in caplog.records)
