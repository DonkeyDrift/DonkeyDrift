# -*- coding: utf-8 -*-
"""FPV 采集部件测试（fake container，不依赖真实硬件/摄像头权限）。

核心回归护栏：读帧循环必须"每帧新建 generator + EAGAIN 重试"——旧读法复用
死 generator，首个 EAGAIN 即拿假 EOF（2026-11-20 误诊事故根因，详见
docs/arch/fpv-pilot-capture-plan.md §3.4 警告框）。test_retry_* 即该护栏。
"""
import time

import numpy as np

from donkeycar.parts.fpv_capture import FpvCaptureCardCamera


class FakeFrame:
    def __init__(self, tag):
        self.tag = tag

    def reformat(self, format=None, width=None, height=None, **kwargs):
        w = width or 8
        h = height or 6
        tag = self.tag

        class _Reformatted:
            def to_ndarray(self):
                arr = np.zeros((h, w, 3), np.uint8)
                arr[:] = tag % 256
                return arr

        return _Reformatted()


class FakeContainer:
    """脚本化容器：每次 decode(video=0) 消耗一个脚本项并返回单目 generator。

    脚本项："eagain"（抛 EAGAIN，模拟 avf 帧间隙）/"eof"/FakeFrame。
    空脚本视为 eof。语义与真实 av.container 一致：generator 抛异常即终止。
    """

    def __init__(self, script):
        self.script = list(script)
        self.closed = False
        self.decode_calls = 0

    def decode(self, video=0):
        self.decode_calls += 1
        outcome = self.script.pop(0) if self.script else "eof"

        def gen():
            if outcome == "eagain":
                raise BlockingIOError(35, "Resource temporarily unavailable")
            if outcome == "eof":
                return
            yield outcome

        return gen()

    def close(self):
        self.closed = True


def _make_cam(container, **kw):
    args = dict(open_fn=lambda: container,
                width=8, height=6, model_w=8, model_h=6,
                eagain_sleep=0.001)
    args.update(kw)
    return FpvCaptureCardCamera(**args)


def _wait_eof(cam, timeout=2.0):
    """等脚本自然耗尽(eof)/error 后返回终态——避免 stop() 打断循环造成状态竞态。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = cam.stats()["status"]
        if st in ("eof", "error"):
            return st
        time.sleep(0.005)
    return cam.stats()["status"]


def test_retry_survives_eagain_and_keeps_capturing():
    """回归护栏：首个 EAGAIN 后必须继续出帧（旧读法在此断流拿假 EOF）。"""
    container = FakeContainer(["eagain", FakeFrame(1), "eagain", FakeFrame(2)])
    cam = _make_cam(container)
    cam.start()
    assert _wait_eof(cam) == "eof"
    cam.stop()
    st = cam.stats()
    assert st["frames"] == 2, f"EAGAIN 后未继续出帧: {st}"
    assert st["eagain_retries"] == 2
    assert st["errors"] == 0
    img, ts = cam.latest_model_frame()
    assert img.shape == (6, 8, 3)
    assert img[0, 0, 0] == 2  # latest = 第 2 帧
    assert container.closed


def test_latest_only_overwrites_no_queue():
    """latest-only：三帧先后到达，槽里只有最后一帧。"""
    container = FakeContainer([FakeFrame(1), FakeFrame(2), FakeFrame(3)])
    cam = _make_cam(container)
    cam.start()
    assert _wait_eof(cam) == "eof"
    cam.stop()
    assert cam.stats()["frames"] == 3
    img, _ = cam.latest_model_frame()
    assert img[0, 0, 0] == 3
    full, ts = cam.latest_full_frame()
    assert full.shape == (6, 8, 3)
    assert full[0, 0, 0] == 3
    assert ts > 0


def test_stats_and_eof_status():
    """stats 结构齐全；真 eof（流结束）如实报状态，不冒充 ok。"""
    container = FakeContainer([FakeFrame(7)])
    cam = _make_cam(container)
    cam.start()
    assert _wait_eof(cam) == "eof"
    cam.stop()
    st = cam.stats()
    assert st["frames"] == 1
    assert st["status"] == "eof"
    assert st["model_shape"] == (6, 8, 3)
    assert st["requested"] == "8x6@120 nv12"
    assert st["eagain_retries"] == 0
    # 首帧前无到达间隔，p50 为 None 但不崩
    assert st["arrival_p50_ms"] is None


def test_eof_after_eagain_marks_true_eof():
    """EAGAIN 若干后流真结束 → eof 是真的（新 generator 语义下 StopIteration
    只在流尽时出现，不再是假象）。"""
    container = FakeContainer(["eagain", "eagain", "eof"])
    cam = _make_cam(container)
    cam.start()
    assert _wait_eof(cam) == "eof"
    cam.stop()
    st = cam.stats()
    assert st["frames"] == 0
    assert st["eagain_retries"] == 2
