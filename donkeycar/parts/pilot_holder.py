#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行时可热切换的推理模型容器（issue #003 热加载）。

车端模型过去只在 `manage.py drive` 启动时按 `--model` 加载，运行中换模型
只能重启车端进程。本 Part 在启动时无条件注册，内部持有一个 KerasPilot，
允许在车端进程运行期间原子替换：

- Web 端选模型 → 后端经 WebSocket 下发 `load_model` → DriveApiBridge 调用
  `PilotHolder.load(path, type)`，构建新模型后原子替换当前实例；
- 未选择模型时容器为空，`run()` 输出全 None，等价于原先「没有 pilot 输出」，
  DriveMode 仍按 0 处理，不会导致车端启动失败；
- 构建在锁外完成，换代在锁内原子完成；`run()` 只在锁内取一次引用，
  推理过程在锁外，避免持锁阻塞。

仅依赖 `donkeycar.utils.get_model_by_type`，不在模块导入期引入 TensorFlow。
"""
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class PilotHolder:
    """可原子替换内部 KerasPilot 的常驻 Part。"""

    def __init__(self, cfg, output_count: int = 2):
        self.cfg = cfg
        self.output_count = int(output_count)
        self._lock = threading.Lock()
        self._pilot = None
        self._model_path: Optional[str] = None
        self._model_type: Optional[str] = None

    # ------------------------------------------------------------------
    # 构建 / 加载
    # ------------------------------------------------------------------
    def _build(self, model_path: str, model_type: Optional[str]):
        # 延迟导入，避免模块导入期触发重量级依赖
        from donkeycar import utils as dk_utils

        resolved_type = model_type or getattr(self.cfg, "DEFAULT_MODEL_TYPE", "linear")
        pilot = dk_utils.get_model_by_type(resolved_type, self.cfg)
        pilot.load(model_path)
        return pilot, resolved_type

    def load(self, model_path: str, model_type: Optional[str] = None):
        """构建并原子替换当前模型；构建失败时保留旧模型并把异常抛给调用方。"""
        if not model_path or not isinstance(model_path, str):
            raise ValueError("model_path 无效")
        # 构建在锁外完成：热加载可能耗时数百毫秒到数秒，不能阻塞推理线程。
        pilot, resolved_type = self._build(model_path, model_type)
        with self._lock:
            old = self._pilot
            self._pilot = pilot
            self._model_path = model_path
            self._model_type = resolved_type
        if old is not None:
            try:
                old.shutdown()
            except Exception:  # pragma: no cover - 旧模型清理失败不影响新模型
                logger.warning("关闭旧模型失败", exc_info=True)
        logger.info("已热加载模型: %s (%s)", model_path, resolved_type)
        return pilot

    # ------------------------------------------------------------------
    # Vehicle Part 接口
    # ------------------------------------------------------------------
    def run(self, img_arr, *other_arr):
        with self._lock:
            pilot = self._pilot
        if pilot is None:
            # 与「启动时未注册 pilot」等价：DriveMode 收到 None 按 0 处理。
            return tuple(None for _ in range(self.output_count))
        return pilot.run(img_arr, *other_arr)

    def shutdown(self):
        with self._lock:
            pilot, self._pilot = self._pilot, None
        if pilot is not None:
            pilot.shutdown()

    # ------------------------------------------------------------------
    # 状态查询（供测试/诊断）
    # ------------------------------------------------------------------
    def current(self):
        with self._lock:
            return self._pilot

    @property
    def model_path(self) -> Optional[str]:
        with self._lock:
            return self._model_path

    @property
    def model_type(self) -> Optional[str]:
        with self._lock:
            return self._model_type
