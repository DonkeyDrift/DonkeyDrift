# -*- coding: utf-8 -*-
"""共享测试夹具：每个测试前后重置模拟器帧到达侧信道。

frame_freshness 是进程内单例（实车为 None、模拟器有值），测试之间若不重置，
dgym 相关用例会把到达时刻泄漏给后续帧缓冲用例，改变其时间戳与去重语义。
"""
import pytest

from donkeycar.parts import frame_freshness


@pytest.fixture(autouse=True)
def _reset_frame_freshness():
    frame_freshness.reset_source_arrival()
    yield
    frame_freshness.reset_source_arrival()
