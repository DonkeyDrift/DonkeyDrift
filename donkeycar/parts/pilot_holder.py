#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行时可热切换的推理模型容器（issue #003 热加载）。

车端模型过去只在 `manage.py drive` 启动时按 `--model` 加载，运行中换模型
只能重启车端进程。本 Part 在启动时无条件注册，内部持有当前 pilot（模型或
漂移回放），允许在车端进程运行期间原子替换：

- Web 端选模型 → 后端经 WebSocket 下发 `load_model` → DriveApiBridge 调用
  `PilotHolder.load(path, type)`，构建新模型后原子替换当前实例；
- 未选择模型时容器为空，`run()` 输出全 None，等价于原先「没有 pilot 输出」，
  DriveMode 仍按 0 处理，不会导致车端启动失败；
- 构建在锁外完成，换代在锁内原子完成；`run()` 只在锁内取一次引用，
  推理过程在锁外，避免持锁阻塞。

仅依赖 `donkeycar.utils.get_model_by_type`，不在模块导入期引入 TensorFlow。
"""
import hashlib
import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# 推理可观测性参数：周期日志间隔 / 帧冻结告警阈值 / 内容哈希兜底采样间隔（秒）
_OBS_LOG_INTERVAL = 5.0
_OBS_FREEZE_WARN_S = 2.0
_OBS_HASH_INTERVAL = 1.0


class PilotHolder:
    """可原子替换内部 KerasPilot 的常驻 Part。"""

    def __init__(self, cfg, output_count: int = 2, initial_pilot=None):
        self.cfg = cfg
        self.output_count = int(output_count)
        self._lock = threading.Lock()
        self._pilot = initial_pilot
        self._model_path: Optional[str] = None
        self._model_type: Optional[str] = None
        self._target_hw: Optional[tuple[int, int]] = None
        # 推理可观测性状态（issue：全自动 pilot 恒定输出排查）
        self._obs_debug = os.environ.get('DK_PILOT_DEBUG', '').strip() not in ('', '0')
        self._obs_reset(now=time.time())

    def _obs_reset(self, now: float) -> None:
        """初始化/换模型后重置观测状态。"""
        self._obs_last_log = now
        self._obs_frame_id: Optional[int] = None
        self._obs_frame_digest: Optional[str] = None
        self._obs_last_hash = now
        self._obs_fresh_since: Optional[float] = None
        self._obs_freeze_warned = False
        self._obs_fresh_frames = 0

    # ------------------------------------------------------------------
    # 构建 / 加载
    # ------------------------------------------------------------------
    def _build(self, model_path: str, model_type: Optional[str]):
        # 延迟导入，避免模块导入期触发重量级依赖
        from donkeycar import utils as dk_utils

        resolved_type = model_type or getattr(self.cfg, "DEFAULT_MODEL_TYPE", "linear")
        pilot = dk_utils.get_model_by_type(resolved_type, self.cfg)
        if model_path.lower().endswith('.json'):
            pilot.interpreter.load_json(model_path)
        else:
            pilot.load(model_path)
        target_hw = self._validate_input_shape(pilot, model_path)
        return pilot, resolved_type, target_hw

    def _validate_input_shape(self, pilot, model_path: str) -> Optional[tuple[int, int]]:
        """校验模型输入通道数与 cfg 一致，并记录模型期望的 (H, W)。

        若模型输入 (H, W) 与当前相机分辨率不一致（例如云端训练的 160x120 模型
        运行在 320x240 相机配置下），run() 会在推理前自动执行等比缩放 + 加白框
        填充（不直接拉伸）。若颜色通道数 D 不一致则拒绝加载。
        """
        expected = (getattr(self.cfg, "IMAGE_H", None),
                    getattr(self.cfg, "IMAGE_W", None),
                    getattr(self.cfg, "IMAGE_DEPTH", None))
        try:
            shape = tuple(pilot.get_input_shape('img_in'))
        except Exception:  # pragma: no cover - 拿不到输入形状的模型类型不拦截
            return None
        try:
            # TfLite/Keras 返回的可能是 np.integer，统一转 Python int 再比较
            actual = tuple(int(d) for d in shape[-3:])
        except (TypeError, ValueError):  # pragma: no cover - 动态/未知维度不拦截
            return None
        if len(actual) != 3 or actual[0] <= 0 or actual[1] <= 0:
            return None
        if isinstance(expected[2], int) and expected[2] > 0 and actual[2] != expected[2]:
            raise ValueError(
                f"模型输入通道数 {actual[2]} 与当前相机配置 {expected[2]} 不一致（{model_path}）")
        if (isinstance(expected[0], int) and isinstance(expected[1], int)
                and (actual[0], actual[1]) != (expected[0], expected[1])):
            logger.info(
                "模型输入 %dx%d 与相机分辨率 %dx%d 不同，推理时将自动等比缩放/加白框适配（%s）",
                actual[1], actual[0], expected[1], expected[0], model_path,
            )
        return (actual[0], actual[1])

    def load(self, model_path: str, model_type: Optional[str] = None):
        """构建并原子替换当前模型；构建失败时保留旧模型并把异常抛给调用方。"""
        if not model_path or not isinstance(model_path, str):
            raise ValueError("model_path 无效")
        # 构建在锁外完成：热加载可能耗时数百毫秒到数秒，不能阻塞推理线程。
        pilot, resolved_type, target_hw = self._build(model_path, model_type)
        with self._lock:
            old = self._pilot
            self._pilot = pilot
            self._model_path = model_path
            self._model_type = resolved_type
            self._target_hw = target_hw
            self._obs_reset(now=time.time())
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
            target_hw = self._target_hw
        if pilot is None:
            # 与「启动时未注册 pilot」等价：DriveMode 收到 None 按 0 处理。
            return tuple(None for _ in range(self.output_count))
        if target_hw is not None and img_arr is not None and hasattr(img_arr, "shape"):
            from donkeycar.utils import fit_image_array
            target_h, target_w = target_hw
            if img_arr.shape[0] != target_h or img_arr.shape[1] != target_w:
                img_arr = fit_image_array(img_arr, target_w, target_h)
        outputs = pilot.run(img_arr, *other_arr)
        self._observe(img_arr, outputs)
        return outputs

    def _observe(self, img_arr, outputs) -> None:
        """周期记录推理输入/输出统计，并检测输入帧长时间不变（疑似相机冻结）。

        排查「全自动时 pilot 输出恒定」这类问题的首要线索是模型到底看到了
        什么：输入帧若持续不变，输出恒定就是必然。开销控制：对象 id 每帧
        比较（O(1)），内容哈希最多每秒一次兜底（防原地改写的相机实现），
        周期日志每 5s 一条。观测自身绝不抛异常、绝不影响主链路。
        DK_PILOT_DEBUG=1 时逐帧打印输入输出（调试用）。
        """
        try:
            now = time.time()
            outs_desc = self._format_outputs(outputs)

            fresh = False
            if img_arr is not None and hasattr(img_arr, 'shape'):
                arr_id = id(img_arr)
                if arr_id != self._obs_frame_id:
                    fresh = True
                    self._obs_frame_id = arr_id
                    self._obs_fresh_since = now
                elif now - self._obs_last_hash >= _OBS_HASH_INTERVAL:
                    # 同一对象也可能是原地改写，低频哈希兜底比对
                    self._obs_last_hash = now
                    digest = hashlib.sha1(img_arr.tobytes()).hexdigest()[:10]
                    if digest != self._obs_frame_digest:
                        fresh = True
                        self._obs_fresh_since = now
                    self._obs_frame_digest = digest
            if fresh:
                self._obs_fresh_frames += 1
                self._obs_freeze_warned = False
            elif self._obs_fresh_since is not None:
                frozen_s = now - self._obs_fresh_since
                if frozen_s > _OBS_FREEZE_WARN_S and not self._obs_freeze_warned:
                    self._obs_freeze_warned = True
                    logger.warning(
                        "pilot 输入帧已 %.1fs 未更新（疑似相机/管道冻结），"
                        "当前输出[%s]——输出恒定先查输入！", frozen_s, outs_desc)

            if now - self._obs_last_log >= _OBS_LOG_INTERVAL:
                interval = now - self._obs_last_log
                in_desc = '无图像输入'
                if img_arr is not None and hasattr(img_arr, 'shape'):
                    try:
                        in_desc = (f"输入 shape={img_arr.shape} dtype={img_arr.dtype} "
                                   f"mean={float(img_arr.mean()):.1f}")
                    except Exception:
                        in_desc = f"输入 shape={getattr(img_arr, 'shape', '?')}"
                logger.info("pilot 观测: %s 输出[%s] 新帧 %d/%.1fs（%s）",
                            in_desc, outs_desc, self._obs_fresh_frames, interval,
                            self._model_path or '未加载')
                self._obs_fresh_frames = 0
                self._obs_last_log = now

            if self._obs_debug:
                logger.info("pilot frame: 输入 id=%s 输出[%s]",
                            self._obs_frame_id, outs_desc)
        except Exception:  # pragma: no cover - 观测失败不影响推理
            logger.debug("pilot 观测异常", exc_info=True)

    @staticmethod
    def _format_outputs(outputs) -> str:
        outs = outputs if isinstance(outputs, tuple) else (outputs,)
        parts = []
        for value in outs:
            try:
                parts.append(f"{float(value):+.3f}")
            except (TypeError, ValueError):
                parts.append(repr(value))
        return '/'.join(parts) if parts else '空'

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
