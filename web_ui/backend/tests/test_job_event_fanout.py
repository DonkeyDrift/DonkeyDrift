# -*- coding: utf-8 -*-
"""训练/连接器 job 事件 fan-out（#502）：多订阅者各收全量，不互偷。"""
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _drain(q):
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except asyncio.QueueEmpty:
            return out


def test_trainer_job_publish_fans_out_to_all_subscribers():
    from trainer_engine import TrainingJobManager

    job = TrainingJobManager().create_job("local")
    s1, s2 = job.subscribe(), job.subscribe()
    try:
        for i in range(3):
            job.publish({"type": "log", "line": f"line{i}"})
        job.publish({"type": "status", "status": "completed"})
        for sub in (s1, s2):
            msgs = _drain(sub)
            assert [m.get("line") for m in msgs if m["type"] == "log"] == \
                ["line0", "line1", "line2"], "每个订阅者都应收全量日志（#502）"
            assert msgs[-1]["status"] == "completed"
    finally:
        job.unsubscribe(s1)
        job.unsubscribe(s2)


def test_trainer_sse_generator_two_streams_each_get_all():
    """直接驱动 _sse_event_generator：两条流（两个页签）各收全量日志。"""
    import json

    from trainer_engine import TrainingJobManager
    from routers.trainer import _sse_event_generator

    manager = TrainingJobManager()
    job = manager.create_job("local")

    async def main():
        g1 = _sse_event_generator(job.id)
        g2 = _sse_event_generator(job.id)
        first1 = await g1.__anext__()   # 初始 status
        first2 = await g2.__anext__()
        assert "status" in first1 and "status" in first2

        job.publish({"type": "log", "line": "L0"})
        job.publish({"type": "log", "line": "L1"})
        job.publish({"type": "status", "status": "completed"})

        async def rest(gen):
            out = []
            try:
                while True:
                    out.append(await gen.__anext__())
            except StopAsyncIteration:
                return out

        out1 = await rest(g1)
        out2 = await rest(g2)
        return out1, out2

    out1, out2 = asyncio.run(main())

    def logs(chunk):
        return [json.loads(ln.replace("data: ", ""))["line"]
                for ln in chunk if '"type": "log"' in ln]

    assert logs(out1) == ["L0", "L1"], "第一条流必须收到全部日志（#502）"
    assert logs(out2) == ["L0", "L1"], "第二条流必须收到全部日志（#502）"


def test_connector_job_publish_fans_out():
    from connector_engine import ConnectorJobManager

    job = ConnectorJobManager().create_job("pull_tub")
    s1, s2 = job.subscribe(), job.subscribe()
    try:
        job.publish({"type": "log", "line": "a"})
        job.publish({"type": "status", "status": "completed"})
        for sub in (s1, s2):
            msgs = _drain(sub)
            assert msgs[0]["line"] == "a"
            assert msgs[-1]["status"] == "completed"
    finally:
        job.unsubscribe(s1)
        job.unsubscribe(s2)
