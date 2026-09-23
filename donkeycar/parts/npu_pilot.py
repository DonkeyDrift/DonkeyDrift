#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AidLite 推理部件 —— 不依赖 TensorFlow 的解释器与 LinearPilot。

两种后端，共用同一套 AidLite 引擎：
  * `.aidem`（AIMO 云转 QNN context binary）→ QNN240 + HTP/DSP = **NPU**
  * `.tflite`（训练直接产物）→ aidlite 内建 TFLite + CPU（无需系统装 TF，
    实测 invoke ~3.8ms，精度与 TF 完全一致——同引擎同模型）

配合模型文件在 Qualcomm QCS6490 上做行为克隆推理（steering/throttle 回归）。
与 `parts/interpreter.py` 的 TfLite 并列，但独立成模块且不 import tensorflow：
车端 python（系统 3.12 + aidlite，见 .venv-npu）不必安装 TF 即可跑 NPU 与
tflite 两类模型，`utils.get_model_by_type` 的 `aidlite_` 分支必须在 import
keras 前返回本模块。

实测约束（AIMO 产物 README 验证过）：
  1. .ctx.bin 只能配 TYPE_DSP；TYPE_CPU/TYPE_GPU 会被拒（StatusCode[120010]）
  2. NPU 形状必须读模型同目录的 qnn_model_info.json，不要硬编码；
     tflite 后端 aidlite 自己能解析模型，但 set_model_properties 需要先给值，
     由 pilot 按 cfg.IMAGE_* 给约定值
  3. 不要加载 htp_backend_extensions.json（AIMO 服务器 x86 路径，设备报
     Unknown Key，无增益）
  4. 运行环境：aidlite 只装在系统 /usr/bin/python3（cpython-312 的 .so），
     DonkeyDrift 默认 .venv（3.11）里没有——车进程需用 .venv-npu 启动
     （management/base.py 已自动选择，可用 DONKEY_CAR_PYTHON 覆盖）
"""
from __future__ import annotations

import contextlib
import ctypes
import json
import logging
import os
import sys
import threading

import numpy as np

from donkeycar.utils import normalize_image

logger = logging.getLogger(__name__)

_NPU_MODEL_EXTS = ('.aidem', '.ctx.bin')
_TFLITE_MODEL_EXTS = ('.tflite',)


def _suffix_matches(path: str, exts) -> bool:
    return any(ext in path for ext in exts)


class _quiet_c:
    """AidLite/QNN 插件用 printf 打噪声且不走日志系统，从 fd 层临时吞掉（含 fflush）。

    进程级锁：并发推理（web 后端线程池）下多个 _quiet_c 交错 enter/exit 会互相
    还原 fd，stdout/stderr 可能被永久指到 devnull；quiet 区全局串行化后，
    最后一个退出的上下文总能把真实 fd 还原回去。"""

    _lock = threading.Lock()

    def __init__(self, path=os.devnull):
        self.path, self.saved = path, None

    def __enter__(self):
        self._lock.acquire()
        try:
            sys.stdout.flush()
            sys.stderr.flush()
            ctypes.CDLL(None).fflush(None)
            self.saved, self.saved2 = os.dup(1), os.dup(2)
            self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            os.dup2(self.fd, 1)
            os.dup2(self.fd, 2)
        except Exception:
            self.saved = None
        return self

    def __exit__(self, *exc):
        try:
            if self.saved is not None:
                sys.stdout.flush()
                sys.stderr.flush()
                ctypes.CDLL(None).fflush(None)
                os.dup2(self.saved, 1)
                os.dup2(self.saved2, 2)
                for fd in (self.fd, self.saved, self.saved2):
                    os.close(fd)
                ctypes.CDLL(None).fflush(None)
        finally:
            self.saved = None
            self._lock.release()
        return False


class AidLite:
    """AidLite 解释器（默认 = AIMO NPU 产物 → QNN240 + HTP/DSP）。

    与 TfLite 解释器鸭子类型兼容（load / get_input_shape / predict_from_dict /
    shutdown / summary），但不继承 parts.interpreter.Interpreter——那个基类
    所在模块顶层 import tensorflow。
    """

    # 后端模式：'npu'（.aidem）或 'tflite'（.tflite → aidlite CPU 后端）
    mode = 'npu'

    def __init__(self):
        self.adl = None                      # aidlite 模块，load() 时惰性导入
        self.interpreter = None
        self.in_shapes = self.out_shapes = None
        self.input_keys = ["img_in"]
        # 命名对齐 KerasLinear.y_transform，输出顺序 = (steering, throttle)
        self.output_keys = ["n_outputs0", "n_outputs1"]
        self._lock = threading.Lock()        # 序列化 invoke 与 shutdown（热加载竞态）
        # tflite 后端插件每次推理都打 printf 噪声；NPU 路径实测不需要
        self._quiet_infer = self.mode != 'npu'

    # ── 加载 ────────────────────────────────────────────────────────────────
    def load(self, model_path: str) -> None:
        exts = _NPU_MODEL_EXTS if self.mode == 'npu' else _TFLITE_MODEL_EXTS
        if not _suffix_matches(model_path, exts):
            raise ValueError(f"不认识的模型扩展名: {model_path}（mode={self.mode} 需 {exts}）")
        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"模型不存在: {model_path}")

        try:
            import aidlite
        except ImportError as e:
            raise RuntimeError(
                f"import aidlite 失败（{e}）。AidLite 后端只能跑在装有 aidlite 的 "
                "python（本机为系统 /usr/bin/python3，见 .venv-npu）下") from e

        self.adl = aidlite
        if self.mode == 'npu':
            info_path = os.path.join(os.path.dirname(os.path.abspath(model_path)),
                                     "qnn_model_info.json")
            if not os.path.isfile(info_path):
                raise FileNotFoundError(
                    f"缺少 {info_path}（AIMO 产物形状定义，必须与模型同目录）")
            info = json.load(open(info_path))
            self.in_shapes = [list(v) for v in info["inputDimensions"].values()]
            self.out_shapes = [list(v) for v in info["outputDimensions"].values()]
            framework, accelerate = aidlite.FrameworkType.TYPE_QNN240, \
                aidlite.AccelerateType.TYPE_DSP               # ← 走 NPU
            soc_desc = f"{info.get('htp_socs_name')}/{info.get('data_type')}"
        else:
            # tflite：形状须由构造方预先给出（aidlite 要求 set_model_properties
            # 先给值；pilot 按 cfg.IMAGE_* 提供，linear 模型输出恒为 2×[1,1]）
            if not self.in_shapes or not self.out_shapes:
                raise ValueError("tflite 后端需在构造时提供 in_shapes/out_shapes")
            framework, accelerate = aidlite.FrameworkType.TYPE_TFLITE, \
                aidlite.AccelerateType.TYPE_CPU
            soc_desc = "CPU"

        with _quiet_c():
            m = aidlite.Model.create_instance(model_path)
            if m is None:
                raise RuntimeError(f"Model.create_instance 失败: {model_path}")
            m.set_model_properties(self.in_shapes, aidlite.DataType.TYPE_FLOAT32,
                                   self.out_shapes, aidlite.DataType.TYPE_FLOAT32)
            c = aidlite.Config.create_instance()
            c.framework_type = framework
            c.accelerate_type = accelerate
            it = aidlite.InterpreterBuilder.build_interpreter_from_model_and_config(m, c)
            if it is None:
                raise RuntimeError("build_interpreter_from_model_and_config 失败")
            rc = it.init()
            if rc != 0:
                raise RuntimeError(f"interpreter.init() 失败 rc={rc}")
            rc = it.load_model()
            if rc != 0:
                raise RuntimeError(f"interpreter.load_model() 失败 rc={rc}")
        self.interpreter = it
        logger.info("AidLite[%s] 已加载 %s in=%s out=%s (%s)",
                    self.mode, os.path.basename(model_path),
                    self.in_shapes, self.out_shapes, soc_desc)

    # ── 形状查询（去 batch，如 (120, 160, 3)） ──────────────────────────────
    def get_input_shape(self, input_name):
        if self.in_shapes is None:
            raise RuntimeError("先 load() 模型")
        return tuple(self.in_shapes[0][1:])

    def output_shapes(self):
        if self.in_shapes is None:
            raise RuntimeError("先 load() 模型")
        return ({k: self.get_input_shape(k) for k in self.input_keys},
                {k: tuple(s[1:]) for k, s in zip(self.output_keys, self.out_shapes)})

    # ── 推理 ────────────────────────────────────────────────────────────────
    def predict_from_dict(self, input_dict):
        """输入已归一化 float32；返回 [array([steering]), array([throttle])]"""
        arr = next(iter(input_dict.values()))
        arr = np.asarray(arr)
        if arr.ndim == 3:
            arr = arr[None, ...]
        arr = np.ascontiguousarray(arr, dtype=np.float32)

        quiet = _quiet_c() if self._quiet_infer else contextlib.nullcontext()
        with quiet, self._lock:
            it = self.interpreter
            if it is None:
                raise RuntimeError("解释器已关闭或尚未 load()")
            rc = it.set_input_tensor(0, arr)
            if rc != 0:
                raise RuntimeError(f"set_input_tensor 失败 rc={rc}")
            rc = it.invoke()
            if rc != 0:
                raise RuntimeError(f"invoke 失败 rc={rc}")
            outs = [np.asarray(it.get_output_tensor(i)).reshape(-1)
                    for i in range(len(self.out_shapes))]
        return outs if len(outs) > 1 else outs[0]

    def shutdown(self):
        with self._lock:
            it, self.interpreter = self.interpreter, None
        if it is None:
            return
        with _quiet_c():
            try:
                it.destroy()
            except Exception:
                logger.warning("关闭 AidLite 解释器失败", exc_info=True)

    def summary(self) -> str:
        backend = 'QNN240/DSP' if self.mode == 'npu' else 'TFLite/CPU'
        return f"AidLite[{backend}] in={self.in_shapes} out={self.out_shapes}"

    def __str__(self) -> str:
        return type(self).__name__


class AidLiteTflite(AidLite):
    """.tflite 模型 → aidlite 内建 TFLite 后端（CPU），无需系统 TensorFlow。

    形状必须构造时给定（aidlite 的 set_model_properties 先于模型解析）；
    加载后如与模型声明不符会由 invoke 报错暴露。
    """

    mode = 'tflite'

    def __init__(self, in_shapes, out_shapes):
        super().__init__()
        self.in_shapes = [list(s) for s in in_shapes]
        self.out_shapes = [list(s) for s in out_shapes]


class NpuLinearPilot:
    """NPU 版 KerasLinear：run(img_arr) → (angle, throttle)，推理接口鸭子类型对齐。

    只推理不训练；KerasPilot 的 set_optimizer/create_model 等训练接口不存在。
    构造时不触发 aidlite 导入，load() 才真正建解释器。
    """

    def __init__(self, cfg=None, interpreter: AidLite | None = None,
                 input_shape=None):
        self.interpreter = interpreter or AidLite()
        if input_shape is None:
            h = getattr(cfg, 'IMAGE_H', 120)
            w = getattr(cfg, 'IMAGE_W', 160)
            d = getattr(cfg, 'IMAGE_DEPTH', 3)
            input_shape = (h, w, d)
        self.input_shape = input_shape
        self.num_outputs = 2

    def load(self, model_path: str) -> None:
        logger.info('Loading NPU model %s', model_path)
        self.interpreter.load(model_path)
        shape = self.interpreter.get_input_shape("img_in")
        if tuple(shape) != tuple(self.input_shape):
            logger.warning("模型输入 %s 与 cfg.IMAGE_H/W/DEPTH %s 不一致，以模型为准",
                           tuple(shape), tuple(self.input_shape))
            self.input_shape = tuple(shape)

    def run(self, img_arr: np.ndarray, *other_arr) -> tuple:
        """行车循环入口：uint8 RGB 帧 → (angle, throttle)。其余输入（IMU 等）忽略。"""
        norm_img_arr = normalize_image(np.asarray(img_arr))
        out = self.interpreter.predict_from_dict({"img_in": norm_img_arr})
        steering, throttle = out[0], out[1]
        return float(steering[0]), float(throttle[0])

    def get_input_shape(self, input_name="img_in"):
        return self.interpreter.get_input_shape(input_name)

    def shutdown(self) -> None:
        self.interpreter.shutdown()

    def summary(self) -> str:
        return f"{type(self).__name__}({self.interpreter.summary()})"

    def __str__(self) -> str:
        return type(self).__name__


# ── 独立自检（venv-npu 下可跑） ───────────────────────────────────────────────
if __name__ == "__main__":
    MODELS_DIR = os.path.expanduser("~/projects/mycar/models")
    p = NpuLinearPilot()
    p.load(os.path.join(MODELS_DIR, "Sim01_qcs6490_w8a8.qnn240.ctx.bin.aidem"))
    x = np.full((120, 160, 3), 0.5, np.float32)      # 已归一化的灰输入
    angle, throttle = p.run((x * 255).astype(np.uint8))
    print(f"NPU 输出: steering {angle:+.6f}  throttle {throttle:+.6f}")
    p.shutdown()

    tfl = NpuLinearPilot(interpreter=AidLiteTflite(
        in_shapes=[[1, 120, 160, 3]], out_shapes=[[1, 1], [1, 1]]))
    tfl.load(os.path.join(MODELS_DIR, "Sim01.tflite"))
    angle, throttle = tfl.run((x * 255).astype(np.uint8))
    print(f"tflite(CPU) 输出: steering {angle:+.6f}  throttle {throttle:+.6f}")
    tfl.shutdown()
