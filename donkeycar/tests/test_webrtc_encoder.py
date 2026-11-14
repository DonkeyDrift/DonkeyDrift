import numpy as np
import pytest
from fractions import Fraction

av = pytest.importorskip("av")
pytest.importorskip("aiortc")

import aiortc.rtcrtpsender
from donkeycar.parts.webrtc_encoder import (
    DEFAULT_VIDEO_BITRATE,
    TunedVp8Encoder,
    install_tuned_vp8_encoder,
    resolve_tune_enabled,
    resolve_video_bitrate,
)


def make_rgb_frame(pts=0, width=320, height=240):
    frame = av.VideoFrame.from_ndarray(
        np.zeros((height, width, 3), dtype=np.uint8), format="rgb24")
    frame.pts = pts
    frame.time_base = Fraction(1, 60)
    return frame


@pytest.fixture
def restore_get_encoder():
    """安装测试后恢复 aiortc 模块与幂等标记，避免污染其他用例。

    预置 ``_installed = False``：其他测试文件构造 DriveApiBridge 时可能
    已真实安装过补丁，这里强制本用例重新走完整安装路径才有效。
    """
    import donkeycar.parts.webrtc_encoder as mod
    saved_get_encoder = aiortc.rtcrtpsender.get_encoder
    saved_installed = mod._installed
    mod._installed = False
    yield
    aiortc.rtcrtpsender.get_encoder = saved_get_encoder
    mod._installed = saved_installed


def warm_codec(encoder):
    """编码若干帧使 codec context 就绪，再返回供断言。"""
    for i in range(3):
        encoder.encode(make_rgb_frame(pts=i))
    assert encoder.codec is not None
    return encoder.codec


def test_tuned_encoder_applies_low_latency_options(monkeypatch):
    # PyAV 在 open 时消费 options 字典，事后读不回；用代理录制赋值时刻快照
    class OptionsRecorder:
        def __init__(self, ctx):
            object.__setattr__(self, "_ctx", ctx)
            object.__setattr__(self, "options_snapshot", None)

        def __setattr__(self, name, value):
            if name == "options":
                object.__setattr__(self, "options_snapshot", dict(value))
            # 全部赋值转发给真实 context（width/height/bit_rate/options...）
            setattr(object.__getattribute__(self, "_ctx"), name, value)

        def __getattr__(self, name):
            return getattr(object.__getattribute__(self, "_ctx"), name)

    recorder_holder = {}
    import donkeycar.parts.webrtc_encoder as webrtc_encoder_mod
    orig_create = av.CodecContext.create

    def spy_create(name, mode):
        ctx = orig_create(name, mode)
        if name == "libvpx":
            recorder = OptionsRecorder(ctx)
            recorder_holder["recorder"] = recorder
            return recorder
        return ctx

    # av.CodecContext 是 C 扩展类型，不能改类属性；替换模块级 av 引用
    from types import SimpleNamespace
    monkeypatch.setattr(webrtc_encoder_mod, "av", SimpleNamespace(
        CodecContext=SimpleNamespace(create=spy_create),
        video=av.video,
    ))

    encoder = TunedVp8Encoder(bitrate=1000000, gop_size=240)
    warm_codec(encoder)

    snapshot = recorder_holder["recorder"].options_snapshot
    assert snapshot["cpu-used"] == "15"
    assert snapshot["noise-sensitivity"] == "0"
    assert snapshot["deadline"] == "realtime"
    assert snapshot["lag-in-frames"] == "0"
    assert encoder.codec.gop_size == 240
    assert encoder.codec.bit_rate == 1000000


def test_tuned_encoder_bitrate_clamped_to_vpx_range():
    # Vp8Encoder 的 target_bitrate setter clamp 到 [250kbps, 1.5Mbps]
    assert TunedVp8Encoder(bitrate=9000000).target_bitrate == 1500000
    assert TunedVp8Encoder(bitrate=100000).target_bitrate == 250000


def test_tuned_encoder_returns_payloads_and_rtp_timestamp():
    encoder = TunedVp8Encoder()
    payloads, timestamp = encoder.encode(make_rgb_frame(pts=7))
    # VP8 软编码零帧也会产出有效载荷（描述符+压缩数据）
    assert payloads, "encode 应产出至少一个 RTP 载荷"
    assert all(isinstance(p, bytes) for p in payloads)
    # 1/60 时基 → 90kHz 时钟：pts×1500
    assert timestamp == 7 * 1500


def test_tuned_encoder_rebuilds_on_large_bitrate_change():
    encoder = TunedVp8Encoder(bitrate=1000000)
    first_codec = warm_codec(encoder)
    # REMB 下调超过 10% 触发重建，新码率生效
    encoder.target_bitrate = 500000
    encoder.encode(make_rgb_frame(pts=10))
    assert encoder.codec is not first_codec
    assert encoder.codec.bit_rate == 500000


def test_install_intercepts_vp8_only(restore_get_encoder):
    class FakeH264Encoder:
        pass

    sentinel = FakeH264Encoder()
    aiortc.rtcrtpsender.get_encoder = lambda codec: sentinel

    assert install_tuned_vp8_encoder(bitrate=800000) is True
    get_encoder = aiortc.rtcrtpsender.get_encoder

    class FakeCodec:
        def __init__(self, name):
            self.name = name

    vp8_encoder = get_encoder(FakeCodec("VP8"))
    assert isinstance(vp8_encoder, TunedVp8Encoder)
    assert vp8_encoder.target_bitrate == 800000

    assert get_encoder(FakeCodec("H264")) is sentinel
    # 幂等：重复安装不叠加包裹
    assert install_tuned_vp8_encoder(bitrate=800000) is True


def test_resolve_video_bitrate_precedence(monkeypatch):
    monkeypatch.delenv("DRIVE_WEBRTC_VIDEO_BITRATE", raising=False)
    assert resolve_video_bitrate() == DEFAULT_VIDEO_BITRATE
    assert resolve_video_bitrate(500000) == 500000
    monkeypatch.setenv("DRIVE_WEBRTC_VIDEO_BITRATE", "999999")
    assert resolve_video_bitrate() == 999999
    assert resolve_video_bitrate(1) == 1  # 显式参数优先于 env
    monkeypatch.setenv("DRIVE_WEBRTC_VIDEO_BITRATE", "not-a-number")
    assert resolve_video_bitrate() == DEFAULT_VIDEO_BITRATE  # 非法值回落默认


def test_resolve_tune_enabled(monkeypatch):
    monkeypatch.delenv("DRIVE_WEBRTC_ENCODER_TUNE", raising=False)
    assert resolve_tune_enabled() is True
    assert resolve_tune_enabled(False) is False
    assert resolve_tune_enabled(True) is True
    for off in ("0", "false", "no", "off", "FALSE"):
        monkeypatch.setenv("DRIVE_WEBRTC_ENCODER_TUNE", off)
        assert resolve_tune_enabled() is False
    monkeypatch.setenv("DRIVE_WEBRTC_ENCODER_TUNE", "1")
    assert resolve_tune_enabled() is True


def test_drive_api_bridge_installs_tuned_encoder_by_default(restore_get_encoder,
                                                            monkeypatch):
    monkeypatch.delenv("DRIVE_WEBRTC_ENCODER_TUNE", raising=False)
    monkeypatch.delenv("DRIVE_WEBRTC_VIDEO_BITRATE", raising=False)
    from donkeycar.parts.drive_api_bridge import DriveApiBridge

    class FakeCodec:
        name = "VP8"

    before = aiortc.rtcrtpsender.get_encoder
    bridge = DriveApiBridge(auto_start=False)  # 默认 webrtc + tune 开
    try:
        assert aiortc.rtcrtpsender.get_encoder is not before
        assert isinstance(
            aiortc.rtcrtpsender.get_encoder(FakeCodec()), TunedVp8Encoder)
    finally:
        bridge.shutdown()


def test_drive_api_bridge_skips_tune_when_disabled(restore_get_encoder,
                                                   monkeypatch):
    monkeypatch.setenv("DRIVE_WEBRTC_ENCODER_TUNE", "0")
    from donkeycar.parts.drive_api_bridge import DriveApiBridge

    before = aiortc.rtcrtpsender.get_encoder
    bridge = DriveApiBridge(auto_start=False)
    try:
        # 未安装补丁：get_encoder 保持原样
        assert aiortc.rtcrtpsender.get_encoder is before
    finally:
        bridge.shutdown()
