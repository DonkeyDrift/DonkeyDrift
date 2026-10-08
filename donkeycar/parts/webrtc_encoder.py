#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WebRTC 车端视频编码器调优（P0：降时延、提帧率）。

aiortc 1.15 的默认 Vp8Encoder 参数面向通用通话场景，在本车端
（ARM 8 核 + 同进程 numpy 车辆循环）实测有两处明显不合理：

- ``deadline=realtime`` 却配 ``cpu-used=-6``：realtime 模式的合法快档是
  0~16，-6 属于 good-quality 档取值，负载下编码耗时不降反升；
- ``noise-sensitivity=4``：开启 VP8 时域降噪，遥控画面无收益，纯耗 CPU。

2026-10-08 本机回环探针（scripts/webrtc_loop_probe.py，320×240@60 合成源）
A/B 实测：cpu-used -6→15、noise-sensitivity 4→0 后，端到端 p50
53.5→45.7ms，p95 68.4→59.4ms，stamp_fps 53.1→58.2。

同时把 gop_size 3000（≈50 分钟不出关键帧）缩到 4 秒一个：丢包后的画面
恢复不再完全依赖 PLI 请求（PLI 风暴是画面冻结感的常见放大器）。

初始码率从 500kbps 提到 1.5Mbps（VP8 编码器上限）：aiortc 收到浏览器
REMB 后仍会经 ``target_bitrate`` setter 自动下调，不会失控。

用法：DriveApiBridge 初始化时自动安装（默认开启）。要回退上游默认参数：

    DRIVE_WEBRTC_ENCODER_TUNE=0

要覆盖码率（bps）：

    DRIVE_WEBRTC_VIDEO_BITRATE=1000000
"""
import logging
import multiprocessing
import os
from fractions import Fraction

logger = logging.getLogger(__name__)

DEFAULT_VIDEO_BITRATE = 1500000  # 1.5 Mbps，aiortc Vp8Encoder MAX_BITRATE
DEFAULT_GOP_SIZE = 240  # 60fps × 4s：周期关键帧，丢包恢复有界

try:
    import av
    from aiortc.codecs.vpx import Vp8Encoder, number_of_threads
    from aiortc.mediastreams import convert_timebase
    import aiortc.rtcrtpsender
except Exception:  # pragma: no cover - 与 drive_api_bridge 同策略：缺依赖只禁用 WebRTC
    av = None
    Vp8Encoder = None
    number_of_threads = None
    convert_timebase = None
    aiortc = None


class TunedVp8Encoder(Vp8Encoder):
    """上游 Vp8Encoder 的低时延替换：仅改编码器创建参数，收发/打包全兼容。

    encode() 复制自 aiortc 1.15 ``codecs/vpx.py``（该库在 codec context
    创建上没有留子类钩子），升级 aiortc 时需对照上游差异。
    """

    def __init__(self, bitrate: int = DEFAULT_VIDEO_BITRATE,
                 gop_size: int = DEFAULT_GOP_SIZE):
        super().__init__()
        # setter 会 clamp 到 [250kbps, 1.5Mbps]，与 REMB 下调共用同一路径
        self.target_bitrate = int(bitrate)
        self.gop_size = int(gop_size)

    def encode(self, frame, force_keyframe: bool = False):
        if frame.format.name != "yuv420p":
            frame = frame.reformat(format="yuv420p")

        if self.codec and (
            frame.width != self.codec.width
            or frame.height != self.codec.height
            # 码率变化超过 10%（REMB 下调）时重建编码器使新码率生效
            or abs(self.target_bitrate - self.codec.bit_rate) / self.codec.bit_rate
            > 0.1
        ):
            self.codec = None

        if force_keyframe:
            frame.pict_type = av.video.frame.PictureType.I

        if self.codec is None:
            self.codec = av.CodecContext.create("libvpx", "w")
            self.codec.width = frame.width
            self.codec.height = frame.height
            self.codec.bit_rate = self.target_bitrate
            self.codec.pix_fmt = "yuv420p"
            self.codec.gop_size = self.gop_size
            self.codec.qmin = 2
            self.codec.qmax = 56
            self.codec.options = {
                "bufsize": str(self.target_bitrate),
                # realtime 模式最快档（上游为 good-quality 档的 -6）
                "cpu-used": "15",
                "deadline": "realtime",
                "lag-in-frames": "0",
                "minrate": str(self.target_bitrate),
                "maxrate": str(self.target_bitrate),
                # 关闭时域降噪（上游为 4，纯耗 CPU）
                "noise-sensitivity": "0",
                "overshoot-pct": "15",
                "partitions": "0",
                "static-thresh": "1",
                "undershoot-pct": "100",
            }
            self.codec.thread_count = number_of_threads(
                frame.width * frame.height, multiprocessing.cpu_count()
            )

        data_to_send = b""
        for package in self.codec.encode(frame):
            data_to_send += bytes(package)

        payloads = self._packetize(data_to_send, self.picture_id)
        timestamp = convert_timebase(frame.pts, frame.time_base, Fraction(1, 90000))
        self.picture_id = (self.picture_id + 1) % (1 << 15)
        return payloads, timestamp


_installed = False


def resolve_video_bitrate(param=None) -> int:
    """码率优先级：构造参数 > DRIVE_WEBRTC_VIDEO_BITRATE > 默认 1.5Mbps。"""
    if param is not None:
        return int(param)
    env = os.environ.get("DRIVE_WEBRTC_VIDEO_BITRATE", "").strip()
    if env:
        try:
            return int(env)
        except ValueError:
            logger.warning(f"忽略非法 DRIVE_WEBRTC_VIDEO_BITRATE: {env!r}")
    return DEFAULT_VIDEO_BITRATE


def resolve_tune_enabled(param=None) -> bool:
    """调优开关优先级：构造参数 > DRIVE_WEBRTC_ENCODER_TUNE > 默认开。"""
    if param is not None:
        return bool(param)
    return os.environ.get("DRIVE_WEBRTC_ENCODER_TUNE", "").strip().lower() not in (
        "0", "false", "no", "off",
    )


def install_tuned_vp8_encoder(bitrate: int = DEFAULT_VIDEO_BITRATE,
                              gop_size: int = DEFAULT_GOP_SIZE) -> bool:
    """把 aiortc 的 VP8 编码器替换为调优版（进程级、幂等）。

    只拦截 VP8；协商到其他编码器（如 H264）时回落上游实现。
    返回是否安装成功（缺 aiortc/av 依赖时 False）。
    """
    global _installed
    if aiortc is None or Vp8Encoder is None:
        return False
    if _installed:
        return True

    original_get_encoder = aiortc.rtcrtpsender.get_encoder

    def get_encoder(codec):
        if getattr(codec, "name", "") == "VP8":
            return TunedVp8Encoder(bitrate=bitrate, gop_size=gop_size)
        return original_get_encoder(codec)

    aiortc.rtcrtpsender.get_encoder = get_encoder
    _installed = True
    logger.info(
        "已安装调优 VP8 编码器: cpu-used=15 noise-sensitivity=0 gop=%d 码率=%dbps"
        "（DRIVE_WEBRTC_ENCODER_TUNE=0 可回退）", gop_size, bitrate,
    )
    return True
