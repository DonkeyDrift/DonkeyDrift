"""TunedVp8Encoder 对 aiortc 内部结构的契约守卫（防升级漂移）。

webrtc_encoder.py 的 encode() 复制自 aiortc 1.15 ``codecs/vpx.py``（上游没留
子类钩子），install_tuned_vp8_encoder 的 monkey-patch 也依赖 rtcrtpsender 的
内部形状。aiortc 升级若改变这些契约，本文件当场报错、提示对照上游重做
encode()/补丁，而不是在车上静默产生坏 RTP 流。
"""
import inspect

import pytest

pytest.importorskip("av")

from aiortc.codecs.vpx import Vp8Encoder, number_of_threads  # noqa: E402
import aiortc.rtcrtpsender as rtcrtpsender  # noqa: E402
from aiortc.mediastreams import convert_timebase  # noqa: E402

from donkeycar.parts import webrtc_encoder  # noqa: E402


def test_upstream_vp8_encoder_exposes_copied_encode_contract():
    """encode() 复制品依赖的基类属性/方法必须仍然存在。"""
    init_src = inspect.getsource(Vp8Encoder.__init__)
    assert "self.codec" in init_src, \
        "上游 __init__ 不再初始化 self.codec，TunedVp8Encoder.encode 需对照重做"
    assert "self.picture_id" in init_src, \
        "上游 __init__ 不再初始化 picture_id，RTP 序号语义失效"
    assert callable(getattr(Vp8Encoder, "_packetize", None)), \
        "上游移除 _packetize，encode() 的 RTP 打包路径失效"
    target_bitrate = getattr(Vp8Encoder, "target_bitrate", None)
    assert isinstance(target_bitrate, property) and target_bitrate.fset is not None, \
        "target_bitrate setter（REMB 下调与码率 clamp 的共用路径）消失"
    assert callable(convert_timebase), "convert_timebase（RTP 时间戳换算）消失"
    assert callable(number_of_threads), "number_of_threads（编码线程数计算）消失"


def test_upstream_get_encoder_dispatch_contract():
    """monkey-patch 假设：上游分发器返回可实例化的 Vp8Encoder、sender 以单位置参数调用。

    断言一律用模块级源码而非运行期属性：先行的测试可能已把
    rtcrtpsender.get_encoder 替换成 TunedVp8Encoder 工厂，
    inspect.getsource(属性) 会取到补丁函数。上游 def get_encoder 位于
    aiortc.codecs 包（rtcrtpsender 只是 import 进来替换）。
    """
    import aiortc.codecs as aiortc_codecs

    codecs_src = inspect.getsource(aiortc_codecs)
    assert 'mimeType == "video/vp8"' in codecs_src, "上游分发器不再按 mimeType 识别 VP8"
    assert "def get_encoder(" in codecs_src, "上游 get_encoder 定义消失"
    sender_src = inspect.getsource(rtcrtpsender)
    assert "get_encoder(codec)" in sender_src, \
        "上游 RTCRtpSender 调用 get_encoder 的方式变了，替换补丁需重做"


def test_tuned_encoder_still_pins_low_latency_options():
    """低时延参数仍钉在 encode() 的 options 里（P0 时延优化的核心，勿退化）。"""
    src = inspect.getsource(webrtc_encoder.TunedVp8Encoder.encode)
    assert '"cpu-used": "15"' in src
    assert '"noise-sensitivity": "0"' in src
    assert '"deadline": "realtime"' in src
    assert '"lag-in-frames": "0"' in src
    assert "self._packetize" in src
    assert "convert_timebase" in src
