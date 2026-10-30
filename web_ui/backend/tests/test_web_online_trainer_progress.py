# -*- coding: utf-8 -*-
"""WebOnlineTrainer 进度事件（#490）：仅含 loss 的行不得把百分比打回 0。"""
import queue
import sys
from pathlib import Path
from unittest.mock import Mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _make_trainer(tmp_path, monkeypatch, log_queue):
    from web_online_trainer import WebOnlineTrainer

    monkeypatch.chdir(tmp_path)
    trainer = WebOnlineTrainer(config_file="train_test.conf", log_queue=log_queue)
    trainer.ssh_client = Mock()
    # 与 _stream_remote_training 相同的进度状态重置
    trainer.current_epoch = 0
    trainer.total_epochs = 0
    trainer._last_global_percent = 0.0
    return trainer


def _progress_events(log_queue):
    events = []
    while True:
        try:
            item = log_queue.get_nowait()
        except queue.Empty:
            return events
        if item.get("type") == "progress":
            events.append(item["data"])


def test_loss_only_line_keeps_last_percent(tmp_path, monkeypatch):
    log_queue = queue.Queue()
    trainer = _make_trainer(tmp_path, monkeypatch, log_queue)

    trainer._parse_training_output_web("Epoch 1/4")
    trainer._parse_training_output_web("1/10 [====>......] loss: 0.5")
    trainer._parse_training_output_web("val_loss: 0.42")

    events = _progress_events(log_queue)
    percents = [e["globalPercent"] for e in events]
    assert len(percents) == 2
    assert percents[0] > 0  # Epoch1/4 步 1/10 → 2.5%
    # 第二条（仅 loss）沿用最近百分比而不是 0
    assert percents[1] == percents[0]


def test_percent_resets_between_runs(tmp_path, monkeypatch):
    """新一轮 _stream_remote_training 前的重置把百分比清零。"""
    log_queue = queue.Queue()
    trainer = _make_trainer(tmp_path, monkeypatch, log_queue)

    trainer._parse_training_output_web("Epoch 2/2")
    trainer._parse_training_output_web("5/5 [====] loss: 0.1")
    first = _progress_events(log_queue)
    assert first[-1]["globalPercent"] > 50

    # 模拟新一轮训练开始（_stream_remote_training 的重置逻辑）
    trainer.current_epoch = 0
    trainer.total_epochs = 0
    trainer._last_global_percent = 0.0
    trainer._parse_training_output_web("Epoch 1/2")
    trainer._parse_training_output_web("loss: 0.9")
    second = _progress_events(log_queue)
    # 无步数信息且从未有过步数 → 0（而不是上一轮的残留值）
    assert second[-1]["globalPercent"] == 0
