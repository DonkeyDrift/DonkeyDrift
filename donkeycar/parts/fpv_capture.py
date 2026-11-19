# -*- coding: utf-8 -*-
"""FPV 采集卡相机部件（latest-only，平台可移植）。

M1 交付（docs/arch/fpv-pilot-capture-plan.md §3.2/§3.4）：

- 读帧 = **PyAV 重试循环：每帧新建 decode generator + EAGAIN 重试**
  （fpv_rate_audit 实证满帧 120fps、p50=8.33ms 精确 1/120）。
  ⚠️ 勿回退"复用 generator"读法——avfoundation 帧间隙常态返 EAGAIN
  （avf_read_frame 不阻塞等帧，30fps 内置相机同样如此），generator 内抛异常即终止，
  复用死 generator 只会拿假 EOF（2026-11-20 误诊事故根因，见 §3.4 警告框）。
- latest-only 双槽同帧派发，绝不排队：
  * 模型槽：model_w×model_h RGB ndarray（推理用，采集线程内一步 reformat+缩放）；
  * 全帧槽：width×height **PyAV VideoFrame**（录制/预览用，读取时才转 RGB——
    低频消费者省掉逐帧转换，帧对象引用计数安全持有）。
- 到达时刻：wall clock 写 frame_freshness.set_source_arrival 侧信道（下游
  DriveVideoFrameBuffer 去重/pts 用）；另记单调时钟供帧龄/间隔统计。
- 平台开关 backend=avfoundation|dshow|v4l2；设备默认按名解析（macOS 枚举索引
  不稳定，实测三会话三变序），显式 device 直接跳过解析。

独立采集/预览/验收见 scripts/fpv_preview.py；采集能力探测见 scripts/fpv_card_probe.py。
"""
import logging
import re
import shutil
import subprocess
import threading
import time
from collections import deque

import numpy as np

from donkeycar.parts.frame_freshness import set_source_arrival

logger = logging.getLogger(__name__)


class FpvCaptureError(Exception):
    pass


def _resolve_avfoundation_index(name_substr: str) -> str:
    """按名字子串解析 AVFoundation 设备索引（索引不稳定，名字是稳定键）。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FpvCaptureError("按名解析设备需要 ffmpeg(brew install ffmpeg);或直接传 device 索引")
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-f", "avfoundation",
         "-list_devices", "true", "-i", ""],
        capture_output=True, text=True, timeout=15)
    devices = []
    section = None
    pat = re.compile(r"\[(\d+)\] (.+)$")
    for line in (proc.stderr or "").splitlines():
        if "video devices" in line:
            section = "video"
        elif "audio devices" in line:
            section = "audio"
        elif section == "video":
            m = pat.search(line)
            if m:
                devices.append((m.group(1), m.group(2).strip()))
    hits = [(i, n) for i, n in devices if name_substr.lower() in n.lower()]
    if len(hits) != 1:
        raise FpvCaptureError(
            f"设备名 {name_substr!r} 匹配 {len(hits)} 个（需唯一）: {hits or devices}")
    return hits[0][0]


class FpvCaptureCardCamera:
    """USB 采集卡相机（UVC NV12→RGB，latest-only 双槽）。

    典型用法::

        cam = FpvCaptureCardCamera(device_name="USB3 Video",
                                   width=1280, height=720, fps=120)
        cam.start()
        img, ts = cam.latest_model_frame()   # 320x240x3 RGB + 单调到达时刻
        frame, ts = cam.latest_full_frame()  # 原分辨率 VideoFrame(惰性转 RGB)
        cam.stats()                          # fps/帧间隔/EAGAIN/帧龄
        cam.stop()

    open_fn: 测试钩子——返回对象需有 decode(video=0)/close()（如 fake container）。
    """

    def __init__(self, *, device_name="USB3 Video", device=None,
                 backend="avfoundation", width=1280, height=720, fps=120,
                 pixfmt="nv12", model_w=320, model_h=240,
                 eagain_sleep=0.001, starve_timeout=1.5, open_fn=None):
        self.device_name = device_name
        self._device_arg = device
        self.backend = backend
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.pixfmt = pixfmt
        self.model_w = int(model_w)
        self.model_h = int(model_h)
        self._eagain_sleep = float(eagain_sleep)
        self._starve_timeout = float(starve_timeout)
        self._open_fn = open_fn

        self._container = None
        self._thread = None
        self._stop = threading.Event()
        self._model_slot = None   # (ndarray(model_h, model_w, 3) uint8, 到达单调时刻)
        self._full_slot = None    # (av.VideoFrame, 到达单调时刻)——读取时惰性转 RGB
        self._lock = threading.Lock()  # 仅护 start/stop 竞态；槽赋值本身原子

        self._frames = 0
        self._eagain = 0
        self._errors = 0
        self._status = "idle"
        self._starved = False
        self._last_arrival = None          # 单调
        self._arrivals = deque(maxlen=360)   # 单调到达时刻（~3s@120fps）
        self._intervals = deque(maxlen=360)  # 到达间隔 ms

    # ---------- 设备打开 ----------

    def _device_str(self) -> str:
        if self._device_arg is not None:
            return str(self._device_arg)
        if self.backend == "avfoundation":
            idx = _resolve_avfoundation_index(self.device_name)
            logger.info("fpv: %r -> avfoundation index %s", self.device_name, idx)
            return idx
        if self.backend == "dshow":
            return f"video={self.device_name}"
        if self.backend == "v4l2":
            return self.device_name  # /dev/videoN 直接给路径
        raise FpvCaptureError(f"未知 backend: {self.backend!r}")

    def _open_real(self):
        import av  # 延迟导入：测试注入 open_fn 时不需要真实设备/权限
        options = {
            "framerate": str(self.fps),
            "video_size": f"{self.width}x{self.height}",
            "pixel_format": self.pixfmt,
        }
        return av.open(self._device_str(), format=self.backend, options=options)

    # ---------- 读帧（核心范式：每帧新建 generator + EAGAIN 重试） ----------

    def _read_once(self):
        """一次读取尝试。返回 (frame, 错误标签)；错误标签 None=拿到帧。

        每次调用新建 decode generator——generator 抛 EAGAIN 后即终止（Python
        generator 语义），复用只会拿到假 StopIteration。UVC rawvideo 一包一帧，
        取一帧即弃 generator 不丢帧。
        """
        gen = self._container.decode(video=0)
        try:
            return next(gen), None
        except StopIteration:
            return None, "eof"
        except Exception as exc:  # av.AVError 族不全继承 OSError
            msg = str(exc)
            if "Errno 35" in msg or "temporarily unavailable" in msg:
                return None, "eagain"
            return None, f"error:{msg}"

    def _capture_loop(self):
        try:
            while not self._stop.is_set():
                frame, err = self._read_once()
                if err == "eagain":
                    self._eagain += 1
                    if self._last_arrival is not None and \
                            time.monotonic() - self._last_arrival > self._starve_timeout:
                        self._starved = True
                    time.sleep(self._eagain_sleep)
                    continue
                if err == "eof":
                    self._status = "eof"
                    logger.warning("fpv: 设备流结束(eof)")
                    break
                if err:
                    self._errors += 1
                    if self._errors <= 5:
                        logger.error("fpv: 读帧错误: %s", err)
                    if self._errors > 100:
                        self._status = "error"
                        logger.error("fpv: 错误过多(%d),停止采集", self._errors)
                        break
                    time.sleep(0.005)
                    continue

                now = time.monotonic()
                if self._last_arrival is not None:
                    self._intervals.append((now - self._last_arrival) * 1000.0)
                self._last_arrival = now
                self._arrivals.append(now)
                self._frames += 1
                self._starved = False

                # 模型帧：一步 reformat(NV12→RGB24 + 缩放)，采集线程内完成
                model = frame.reformat(
                    format="rgb24", width=self.model_w, height=self.model_h
                ).to_ndarray()
                self._model_slot = (model, now)
                # 全帧槽持原始 VideoFrame，惰性转 RGB（录制/预览低频消费）
                self._full_slot = (frame, now)
                set_source_arrival()  # 下游去重/pts 侧信道（wall clock）
        finally:
            try:
                if self._container is not None:
                    self._container.close()
            except Exception:
                pass

    # ---------- 生命周期 ----------

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            opener = self._open_fn or self._open_real
            self._container = opener()
            self._status = "running"
            self._thread = threading.Thread(
                target=self._capture_loop, name="fpv-capture", daemon=True)
            self._thread.start()
            logger.info("fpv: 采集启动 %dx%d@%d %s (%s)",
                        self.width, self.height, self.fps, self.pixfmt, self.backend)

    def stop(self, timeout=2.0):
        with self._lock:
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout=timeout)
                self._thread = None
            if self._status == "running":
                self._status = "stopped"
            self._container = None

    # ---------- 消费者接口（latest-only，绝不排队） ----------

    def latest_model_frame(self):
        """返回 (model ndarray, 单调到达时刻)；尚无帧时 (None, 0.0)。"""
        slot = self._model_slot
        return slot if slot is not None else (None, 0.0)

    def latest_full_frame(self):
        """返回 (全帧 RGB ndarray(width×height×3), 单调到达时刻)；惰性转换。

        尚无帧时 (None, 0.0)。
        """
        slot = self._full_slot
        if slot is None:
            return (None, 0.0)
        video_frame, ts = slot
        return video_frame.reformat(format="rgb24").to_ndarray(), ts

    def latest_full_video_frame(self):
        """返回 (原始 VideoFrame, 单调到达时刻)——预览/录制想自选转换路径时用。"""
        slot = self._full_slot
        return slot if slot is not None else (None, 0.0)

    # ---------- 统计 ----------

    def stats(self):
        now = time.monotonic()
        intervals = list(self._intervals)
        arrivals = [t for t in self._arrivals if now - t <= 1.0]
        p = lambda vals, q: round(
            vals[min(len(vals) - 1, round(q / 100 * (len(vals) - 1)))], 2) \
            if vals else None
        srt = sorted(intervals)
        return {
            "status": self._status,
            "frames": self._frames,
            "fps_1s": len(arrivals),
            "arrival_p50_ms": p(srt, 50),
            "arrival_p95_ms": p(srt, 95),
            "eagain_retries": self._eagain,
            "errors": self._errors,
            "starved": self._starved,
            "last_age_ms": round((now - self._last_arrival) * 1000.0, 1)
            if self._last_arrival else None,
            "model_shape": tuple(self._model_slot[0].shape)
            if self._model_slot is not None else None,
            "backend": self.backend,
            "device_name": self.device_name,
            "requested": f"{self.width}x{self.height}@{self.fps} {self.pixfmt}",
        }
