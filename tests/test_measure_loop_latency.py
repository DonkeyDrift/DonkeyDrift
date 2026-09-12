"""measure_loop_latency 单元测试（M0 延迟实测工具）。

覆盖 scripts/measure_loop_latency.py 的纯函数与通路测量逻辑：
- percentile95：空表/单样本/边界；
- summarize_total_p95：三段汇总与 nan（无有效样本）语义；
- _drain_pending / measure_ws_roundtrip：ws 初始推送排空与超时残留排空
  （不排空则前两个 RTT 样本≈0 为假数据，M0 判定被污染）。
"""

import asyncio
import math
import sys
import types
import unittest
from unittest import mock

from scripts.measure_loop_latency import (
    _drain_pending,
    measure_ws_roundtrip,
    percentile95,
    summarize_total_p95,
)


class Percentile95Test(unittest.TestCase):
    """percentile95：纯函数边界行为。"""

    def test_empty_returns_nan(self):
        self.assertTrue(math.isnan(percentile95([])))

    def test_single_sample(self):
        self.assertEqual(percentile95([42.0]), 42.0)

    def test_boundary_20_samples_takes_p95_slot(self):
        samples = [float(i) for i in range(1, 21)]  # 1..20
        # idx = min(int(20*0.95), 19) = 19 → 第 20 个
        self.assertEqual(percentile95(samples), 20.0)

    def test_unsorted_input(self):
        # 先排序再取 idx=min(int(3*0.95),2)=2 → 最大值
        self.assertEqual(percentile95([5.0, 1.0, 3.0]), 5.0)


class SummarizeTotalP95Test(unittest.TestCase):
    """summarize_total_p95：三段汇总；任一段无有效样本（nan）→ None。"""

    def test_normal_sum_with_ws_halved(self):
        results = {
            "vision": {"read_p95_ms": 10.0, "detect_p95_ms": 20.0},
            "ws_roundtrip": {"p95_ms": 40.0},
            "control_path": {"p95_ms": 1.0},
        }
        # 10+20 + 40/2(单程近似) + 1 = 51
        self.assertAlmostEqual(summarize_total_p95(results), 51.0)

    def test_missing_segments_count_zero(self):
        # 未测量的段不参与合计
        results = {"control_path": {"p95_ms": 1.5}}
        self.assertAlmostEqual(summarize_total_p95(results), 1.5)

    def test_nan_segment_returns_none(self):
        # 已测量但 0 有效样本 → nan → 整体无法判定（不得误报超预算）
        results = {
            "ws_roundtrip": {"p95_ms": float("nan")},
            "control_path": {"p95_ms": 1.0},
        }
        self.assertIsNone(summarize_total_p95(results))


class _FakeWS:
    """假 ws：可预载消息（模拟服务端连接后的初始推送），
    send 后按 response_delay_s 延迟回包（None 表示永不回包）。"""

    def __init__(self, preload=(), response_delay_s=None):
        self.queue = asyncio.Queue()
        for m in preload:
            self.queue.put_nowait(m)
        self._response_delay_s = response_delay_s
        self.sent = []

    async def send(self, data):
        self.sent.append(data)
        if self._response_delay_s is not None:
            async def _later():
                await asyncio.sleep(self._response_delay_s)
                self.queue.put_nowait('{"type":"car_state"}')
            asyncio.get_running_loop().create_task(_later())

    async def recv(self):
        return await self.queue.get()


def _run_ws(fake_ws, seconds=0.15, recv_timeout=0.2, interval_s=0.01):
    """用假 websockets 模块跑 measure_ws_roundtrip。"""

    class _FakeConn:
        async def __aenter__(self):
            return fake_ws

        async def __aexit__(self, *exc):
            return False

    fake_mod = types.SimpleNamespace(connect=lambda uri: _FakeConn())
    with mock.patch.dict(sys.modules, {"websockets": fake_mod}):
        return asyncio.run(measure_ws_roundtrip(
            "ws://example", seconds,
            recv_timeout=recv_timeout, interval_s=interval_s))


class DrainPendingTest(unittest.TestCase):
    """_drain_pending：排空已到达的缓冲消息直到静默。"""

    def test_drains_preloaded_messages(self):
        async def scenario():
            ws = _FakeWS(preload=["a", "b"])
            await _drain_pending(ws, quiet_s=0.05)
            self.assertTrue(ws.queue.empty())
        asyncio.run(scenario())

    def test_empty_queue_returns_promptly(self):
        async def scenario():
            ws = _FakeWS()
            await asyncio.wait_for(_drain_pending(ws, quiet_s=0.05), timeout=1.0)
        asyncio.run(scenario())


class WsRoundtripTest(unittest.TestCase):
    """measure_ws_roundtrip：初始推送排空 + 超时残留排空。"""

    def test_initial_push_not_counted_as_rtt(self):
        # 服务端连接后固定先推 car_connection + car_state 两条；
        # 不排空则前两个样本≈0ms（假数据），min_ms 会贴近 0
        fake = _FakeWS(preload=['{"type":"car_connection"}', '{"type":"car_state"}'],
                       response_delay_s=0.02)
        out = _run_ws(fake, seconds=0.2)
        r = out["ws_roundtrip"]
        self.assertGreaterEqual(r["samples"], 2)
        # 真实回包延迟 20ms；所有样本都应反映真实往返而非瞬时消费缓冲
        self.assertGreater(r["min_ms"], 10.0)

    def test_all_timeout_yields_zero_valid_samples(self):
        fake = _FakeWS(preload=[], response_delay_s=None)
        out = _run_ws(fake, seconds=0.15, recv_timeout=0.05)
        r = out["ws_roundtrip"]
        self.assertEqual(r["samples"], 0)
        self.assertIsNone(r["median_ms"])


if __name__ == "__main__":
    unittest.main()
