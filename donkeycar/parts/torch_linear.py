#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PyTorch linear 行为克隆模型 —— TensorFlow-free 的训练与推理（去 TF 迁移）。

结构逐层复刻 `parts/keras.py` 的 `default_n_linear()` / `core_cnn_layers()`
（valid padding、每层 conv 后 Dropout(0.2)、Dense 100/50、双线性输出头），
训练口径对齐 KerasLinear：输入 /255 float32（normalize_image）、输出原始
(angle, throttle)、MSE。与 keras 版仅初始化分布不同，收敛行为等价。

本模块顶层不 import tensorflow，可在只装 torch 的 python（.venv-npu/3.12）下
完成「训练 → 导出 → 上车」全流程：

产物（同一 stem，兼容 web 训练器传 .tflite/.h5 等任意扩展名，取其 stem）：
  <stem>.ckpt        torch 权重+元数据；`torch_linear` 模型类型可热加载上车（CPU 推理）
  <stem>.onnx        NHWC [1,H,W,3] float32 /255 输入，供 AIMO 云转 .aidem 上 NPU
  <stem>.png         train/val loss 曲线（Web Trainer 页展示）
  <stem>_meta.json   final/best loss（Web Trainer 页展示）

ONNX 输入保持 NHWC 是刻意的：与 Sim01 tflite 源、qnn_model_info.json 及
车端 preprocess 的既有约定一致，云转后输入仍是 [1,120,160,3]。
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

from donkeycar.utils import normalize_image, train_test_split

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 1) 网络：复刻 default_n_linear / core_cnn_layers
# ─────────────────────────────────────────────────────────────────────────────
class TorchLinear(nn.Module):
    """输入 [N,H,W,C] float32(/255)，输出 (angle[N,1], throttle[N,1])。

    forward 内部 permute 到 NCHW 供 conv 使用；导出 ONNX 时保持 NHWC 接口。
    Flatten 维度用 LazyLinear 惰性推断，避免手算。
    """

    def __init__(self, input_shape: Tuple[int, int, int] = (120, 160, 3),
                 drop: float = 0.2):
        super().__init__()
        h, w, d = input_shape
        self.input_shape = (h, w, d)
        # conv2d(filters, kernel, strides) —— keras 默认 valid padding = torch padding=0
        self.features = nn.Sequential(
            nn.Conv2d(d, 24, 5, stride=2), nn.ReLU(inplace=True), nn.Dropout(drop),
            nn.Conv2d(24, 32, 5, stride=2), nn.ReLU(inplace=True), nn.Dropout(drop),
            nn.Conv2d(32, 64, 5, stride=2), nn.ReLU(inplace=True), nn.Dropout(drop),
            nn.Conv2d(64, 64, 3, stride=1), nn.ReLU(inplace=True), nn.Dropout(drop),
            nn.Conv2d(64, 64, 3, stride=1), nn.ReLU(inplace=True), nn.Dropout(drop),
            nn.Flatten(),
        )
        self.head = nn.Sequential(
            nn.LazyLinear(100), nn.ReLU(inplace=True), nn.Dropout(drop),
            nn.LazyLinear(50), nn.ReLU(inplace=True), nn.Dropout(drop),
        )
        self.angle_out = nn.LazyLinear(1)
        self.throttle_out = nn.LazyLinear(1)

    def forward(self, x_nhwc: torch.Tensor):
        z = self.features(x_nhwc.permute(0, 3, 1, 2).contiguous())
        z = self.head(z)
        return self.angle_out(z), self.throttle_out(z)


# ─────────────────────────────────────────────────────────────────────────────
# 2) 推理 pilot：鸭子类型对齐 NpuLinearPilot / KerasLinear 的行车接口
# ─────────────────────────────────────────────────────────────────────────────
class TorchLinearPilot:
    """`torch_linear` 模型类型：加载 .ckpt 在 CPU 上推理（无需 TF/aidlite）。

    NPU 路径（.aidem）仍是首选；本类用于训练后未云转时的直接上车与 Arena 预览。
    """

    def __init__(self, cfg=None, input_shape=None):
        if input_shape is None:
            input_shape = (getattr(cfg, 'IMAGE_H', 120),
                           getattr(cfg, 'IMAGE_W', 160),
                           getattr(cfg, 'IMAGE_DEPTH', 3))
        self.input_shape = tuple(input_shape)
        self.net: Optional[TorchLinear] = None
        self.num_outputs = 2
        self.input_keys = ["img_in"]
        self.output_keys = ["n_outputs0", "n_outputs1"]

    def load(self, model_path: str) -> None:
        if not model_path.endswith('.ckpt'):
            raise ValueError(f"torch_linear 需 .ckpt 模型: {model_path}")
        blob = torch.load(model_path, map_location='cpu', weights_only=False)
        shape = tuple(blob.get('input_shape', self.input_shape))
        net = TorchLinear(shape)
        net.load_state_dict(blob['state_dict'])
        net.eval()
        self.net = net
        self.input_shape = shape
        logger.info("TorchLinear 已加载 %s in=%s (final_loss=%s)",
                    os.path.basename(model_path), shape,
                    blob.get('meta', {}).get('final_loss'))

    def run(self, img_arr: np.ndarray, *other_arr) -> tuple:
        """行车循环入口：uint8 RGB 帧 → (angle, throttle)。其余输入忽略。"""
        x = normalize_image(np.asarray(img_arr)).astype(np.float32)
        t = torch.from_numpy(x)[None, ...]          # [1,H,W,C]
        with torch.no_grad():
            a, th = self.net(t)
        return float(a.item()), float(th.item())

    def get_input_shape(self, input_name="img_in"):
        return self.input_shape

    def shutdown(self) -> None:
        self.net = None

    def summary(self) -> str:
        return f"TorchLinear(CPU) in={self.input_shape}"

    def __str__(self) -> str:
        return type(self).__name__


# ─────────────────────────────────────────────────────────────────────────────
# 3) 训练器：tub → TorchLinear，产物 .ckpt/.onnx/.png/_meta.json
# ─────────────────────────────────────────────────────────────────────────────
class _TubDataset(Dataset):
    """(image /255 float32 HWC, [angle, throttle]) 对；与 KerasLinear 口径一致"""

    def __init__(self, records):
        self.records = records

    def __len__(self):
        return len(self.records)

    def __getitem__(self, idx):
        r = self.records[idx]
        img = r.image(as_nparray=True).astype(np.float32) / 255.0
        y = np.array([r.underlying['user/angle'],
                      r.underlying['user/throttle']], np.float32)
        return torch.from_numpy(img), torch.from_numpy(y)


def train_torch_linear(cfg, tub_paths: str, model_output_path: str,
                       comment: Optional[str] = None,
                       max_epochs: Optional[int] = None) -> dict:
    """训练并落盘四件套；返回 meta（含 final/best loss）。

    tub_paths 逗号分隔；model_output_path 取 stem（Web 端可能传 .tflite 名字）。
    """
    from donkeycar.pipeline.types import TubDataset

    stem = os.path.splitext(os.path.expanduser(model_output_path))[0]
    os.makedirs(os.path.dirname(stem) or '.', exist_ok=True)
    tubs = [os.path.expanduser(t) for t in tub_paths.split(',')]
    epochs = max_epochs or getattr(cfg, 'MAX_EPOCHS', 100)
    batch = getattr(cfg, 'BATCH_SIZE', 128)
    lr = getattr(cfg, 'LEARNING_RATE', 1e-3)
    split = getattr(cfg, 'TRAIN_TEST_SPLIT', 0.8)

    dataset = TubDataset(config=cfg, tub_paths=tubs)
    records = dataset.get_records()
    if not records:
        raise RuntimeError(f"tub 无记录: {tubs}")
    train_records, val_records = train_test_split(
        records, shuffle=True, test_size=(1. - split))
    logger.info("训练记录 %d / 验证 %d（tub: %s）",
                len(train_records), len(val_records), tubs)

    device = torch.device('cpu')
    net = TorchLinear((getattr(cfg, 'IMAGE_H', 120),
                       getattr(cfg, 'IMAGE_W', 160),
                       getattr(cfg, 'IMAGE_DEPTH', 3))).to(device)
    opt = torch.optim.Adam(net.parameters(), lr=lr)
    mse = nn.MSELoss()
    train_loader = DataLoader(_TubDataset(train_records), batch_size=batch,
                              shuffle=True, num_workers=0)
    val_loader = DataLoader(_TubDataset(val_records), batch_size=batch,
                            shuffle=False, num_workers=0)

    history = {'loss': [], 'val_loss': []}
    best_val, best_state = float('inf'), None
    t0 = time.time()
    for epoch in range(epochs):
        net.train()
        running, n = 0.0, 0
        for x, y in train_loader:
            opt.zero_grad()
            a, th = net(x.to(device))
            # Keras 多输出 loss = 各输出 loss 之和（loss_weights 默认 1）
            loss = mse(a, y[:, :1]) + mse(th, y[:, 1:])
            loss.backward()
            opt.step()
            running += loss.item() * x.size(0)
            n += x.size(0)
        train_loss = running / max(n, 1)

        net.eval()
        vrunning, vn = 0.0, 0
        with torch.no_grad():
            for x, y in val_loader:
                a, th = net(x.to(device))
                vloss = mse(a, y[:, :1]) + mse(th, y[:, 1:])
                vrunning += vloss.item() * x.size(0)
                vn += x.size(0)
        val_loss = vrunning / max(vn, 1)
        history['loss'].append(train_loss)
        history['val_loss'].append(val_loss)
        if val_loss < best_val:
            best_val = val_loss
            best_state = {k: v.clone() for k, v in net.state_dict().items()}
        print(f"epoch {epoch + 1}/{epochs} - loss: {train_loss:.5f} - "
              f"val_loss: {val_loss:.5f}", flush=True)

    elapsed = time.time() - t0
    if best_state is not None:
        net.load_state_dict(best_state)
    net.eval()

    meta = {
        'final_loss': history['val_loss'][-1],
        'best_loss': best_val,
        'epochs': epochs,
        'elapsed_s': round(elapsed, 1),
        'train_records': len(train_records),
        'val_records': len(val_records),
        'framework': 'pytorch',
        'comment': comment or '',
    }

    # .ckpt（最优权重）
    torch.save({'state_dict': net.state_dict(),
                'input_shape': net.input_shape, 'meta': meta}, stem + '.ckpt')

    # .onnx（NHWC /255 输入；先跑一次 dummy 让 LazyLinear 物化）
    h, w, d = net.input_shape
    with torch.no_grad():
        net(torch.zeros(1, h, w, d))
    torch.onnx.export(
        net, torch.zeros(1, h, w, d), stem + '.onnx',
        input_names=['img_in'], output_names=['n_outputs0', 'n_outputs1'],
        opset_version=13, do_constant_folding=True)

    # .png + _meta.json（Web Trainer 页的 loss 图与指标）
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        plt.figure(1)
        plt.plot(history['loss'])
        plt.plot(history['val_loss'])
        plt.title('model loss')
        plt.ylabel('loss')
        plt.xlabel('epoch')
        plt.legend(['train', 'validate'], loc='upper right')
        plt.savefig(stem + '.png')
        plt.close()
    except Exception as ex:
        print(f"problems with loss graph: {ex}")

    with open(stem + '_meta.json', 'w') as f:
        json.dump(meta, f, indent=2)
    print(f"////////// Finished training in: {elapsed:.1f} sec //////////")
    print(f"saved: {stem}.ckpt / {stem}.onnx / {stem}.png / {stem}_meta.json")
    return meta


# ── 独立自检 ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    net = TorchLinear()
    with torch.no_grad():
        a, t = net(torch.zeros(2, 120, 160, 3))
    print("前向 OK: angle", tuple(a.shape), "throttle", tuple(t.shape))
    p = TorchLinearPilot()
    img = np.full((120, 160, 3), 128, np.uint8)
    if p.net is None and os.environ.get("TORCH_CKPT"):
        p.load(os.environ["TORCH_CKPT"])
        print("推理 OK:", p.run(img))
