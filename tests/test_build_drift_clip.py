"""build_drift_clip 单元测试。

覆盖 scripts/build_drift_clip.py：从 Donkeycar Tub v2 读取录制数据，
选段/拼接/归一化/调速率，输出标准 replay clip JSON（schema
mus4.drift_replay_clip.v1）。

遵循 AAA 模式；所有 Tub 数据用 donkeycar.parts.tub_v2.Tub 在临时目录
真实写入，避免依赖外部样本文件，保证测试自包含。
"""

import json
import os
import shutil
import tempfile
import unittest

from donkeycar.parts.tub_v2 import Tub

from scripts.build_drift_clip import (
    CLIP_SCHEMA,
    load_tub_records,
    build_segment,
    concat_segments,
    apply_scale,
    resample_timeline,
    build_clip,
)


def _make_tub(tub_dir, records):
    """在临时目录写入一个 Tub v2，每条 record 是 dict。

    自动补齐 _timestamp_ms（每条 +20ms）、_index，字段类型按 TubWriter
    约定（user/angle、user/throttle 为 float，user/mode 为 str）。
    """
    inputs = ["user/angle", "user/throttle", "user/mode"]
    types = ["float", "float", "str"]
    tub = Tub(tub_dir, inputs=inputs, types=types, max_catalog_len=1000)
    tub = Tub(tub_dir, inputs=inputs, types=types, max_catalog_len=1000)
    for rec in records:
        full = {
            "user/angle": float(rec.get("angle", 0.0)),
            "user/throttle": float(rec.get("throttle", 0.0)),
            "user/mode": rec.get("mode", "user"),
        }
        # Tub.write_record 自动补 _timestamp_ms（真实 time.time()）、_index、
        # _session_id。load_tub_records 的测试只断言字段存在与删除跳过，
        # 不依赖时戳具体值，故无需覆盖时戳；需要可控时戳的场景由
        # BuildSegment/ResampleTimeline 等用手工构造的 record 列表测试。
        tub.write_record(full)
    tub.close()
    return tub_dir


class LoadTubRecordsTest(unittest.TestCase):
    """load_tub_records：从 Tub v2 迭代并抽取控制字段。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="drift_clip_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_returns_user_angle_and_throttle(self):
        """读取后应返回含 angle/throttle/mode/timestamp 的 dict 列表。"""
        tub_dir = os.path.join(self.tmp, "tub_a")
        _make_tub(tub_dir, [
            {"angle": 0.0, "throttle": 0.1, "mode": "user"},
            {"angle": 0.5, "throttle": 0.2, "mode": "local"},
        ])
        records = load_tub_records(tub_dir)
        self.assertEqual(len(records), 2)
        for r in records:
            self.assertIn("angle", r)
            self.assertIn("throttle", r)
            self.assertIn("mode", r)
            self.assertIn("t_ms", r)
            self.assertIn("index", r)
        self.assertAlmostEqual(records[0]["angle"], 0.0)
        self.assertAlmostEqual(records[1]["throttle"], 0.2)

    def test_load_skips_deleted_records(self):
        """已软删除的记录应被 ManifestIterator 跳过。"""
        tub_dir = os.path.join(self.tmp, "tub_del")
        _make_tub(tub_dir, [
            {"angle": 0.1, "throttle": 0.1},
            {"angle": 0.2, "throttle": 0.2},
            {"angle": 0.3, "throttle": 0.3},
        ])
        tub = Tub(tub_dir, read_only=False)
        tub.delete_records([1])  # 删除第 2 条
        tub.close()
        records = load_tub_records(tub_dir)
        angles = [r["angle"] for r in records]
        self.assertEqual(len(records), 2)
        self.assertNotIn(0.2, angles)


class BuildSegmentTest(unittest.TestCase):
    """build_segment：按 _index 区间或时戳区间裁剪。"""

    def test_clip_by_index_range(self):
        records = [
            {"index": 0, "t_ms": 1000, "angle": 0.0, "throttle": 0.0, "mode": "user"},
            {"index": 1, "t_ms": 1020, "angle": 0.1, "throttle": 0.1, "mode": "local"},
            {"index": 2, "t_ms": 1040, "angle": 0.2, "throttle": 0.2, "mode": "local"},
            {"index": 3, "t_ms": 1060, "angle": 0.3, "throttle": 0.3, "mode": "local"},
            {"index": 4, "t_ms": 1080, "angle": 0.4, "throttle": 0.4, "mode": "local"},
        ]
        seg = build_segment(records, start_index=1, end_index=3)
        self.assertEqual([r["index"] for r in seg], [1, 2, 3])

    def test_clip_by_timestamp_range(self):
        records = [
            {"index": 0, "t_ms": 1000, "angle": 0.0, "throttle": 0.0, "mode": "user"},
            {"index": 1, "t_ms": 1020, "angle": 0.1, "throttle": 0.1, "mode": "local"},
            {"index": 2, "t_ms": 1040, "angle": 0.2, "throttle": 0.2, "mode": "local"},
        ]
        seg = build_segment(records, start_ms=1010, end_ms=1050)
        self.assertEqual([r["index"] for r in seg], [1, 2])


class ConcatSegmentsTest(unittest.TestCase):
    """concat_segments：多段拼接，段间插入静置帧。"""

    def test_concat_inserts_transition_frame(self):
        seg_a = [
            {"index": 0, "t_ms": 1000, "angle": 0.1, "throttle": 0.1, "mode": "local"},
        ]
        seg_b = [
            {"index": 0, "t_ms": 2000, "angle": 0.2, "throttle": 0.2, "mode": "local"},
        ]
        merged = concat_segments([seg_a, seg_b], transition_ms=300)
        # 段间应插入 1 帧静置 (angle=0, throttle=0)
        self.assertEqual(len(merged), 3)
        self.assertEqual(merged[0]["angle"], 0.1)
        self.assertEqual(merged[1]["angle"], 0.0)
        self.assertEqual(merged[1]["throttle"], 0.0)
        self.assertEqual(merged[2]["angle"], 0.2)
        # 合并后时戳应单调递增（静置帧在两段之间）
        self.assertGreater(merged[1]["t_ms"], merged[0]["t_ms"])
        self.assertGreater(merged[2]["t_ms"], merged[1]["t_ms"])

    def test_concat_single_segment_no_transition(self):
        seg_a = [
            {"index": 0, "t_ms": 1000, "angle": 0.1, "throttle": 0.1, "mode": "local"},
            {"index": 1, "t_ms": 1020, "angle": 0.2, "throttle": 0.2, "mode": "local"},
        ]
        merged = concat_segments([seg_a], transition_ms=300)
        self.assertEqual(len(merged), 2)


class ApplyScaleTest(unittest.TestCase):
    """apply_scale：对 throttle/angle 缩放与限幅。"""

    def test_scale_applies_to_throttle_and_angle(self):
        records = [
            {"index": 0, "t_ms": 1000, "angle": 0.5, "throttle": 0.5, "mode": "user"},
            {"index": 1, "t_ms": 1020, "angle": -0.8, "throttle": 0.6, "mode": "user"},
        ]
        scaled = apply_scale(records, throttle_scale=0.5, angle_scale=1.0,
                             throttle_clip=0.6, angle_clip=1.0)
        self.assertAlmostEqual(scaled[0]["throttle"], 0.25)
        self.assertAlmostEqual(scaled[1]["angle"], -0.8)

    def test_scale_clips_to_max(self):
        records = [
            {"index": 0, "t_ms": 1000, "angle": 1.0, "throttle": 1.0, "mode": "user"},
        ]
        scaled = apply_scale(records, throttle_scale=1.0, angle_scale=1.0,
                             throttle_clip=0.6, angle_clip=1.0)
        # 油门 1.0 超 0.6 上限应被钳到 0.6
        self.assertAlmostEqual(scaled[0]["throttle"], 0.6)


class ResampleTimelineTest(unittest.TestCase):
    """resample_timeline：按速率重采样时间轴。"""

    def test_speed_2x_halves_timeline(self):
        records = [
            {"index": 0, "t_ms": 1000, "angle": 0.0, "throttle": 0.0, "mode": "local"},
            {"index": 1, "t_ms": 1100, "angle": 0.1, "throttle": 0.1, "mode": "local"},
            {"index": 2, "t_ms": 1200, "angle": 0.2, "throttle": 0.2, "mode": "local"},
        ]
        resampled = resample_timeline(records, speed=2.0)
        # speed=2.0：相对时戳压缩一半
        # 首帧 t_rel=0，末帧原相对 200ms -> 100ms
        self.assertAlmostEqual(resampled[0]["t_rel"], 0.0)
        self.assertAlmostEqual(resampled[-1]["t_rel"], 100.0)

    def test_speed_0_5x_doubles_timeline(self):
        records = [
            {"index": 0, "t_ms": 1000, "angle": 0.0, "throttle": 0.0, "mode": "local"},
            {"index": 1, "t_ms": 1100, "angle": 0.1, "throttle": 0.1, "mode": "local"},
        ]
        resampled = resample_timeline(records, speed=0.5)
        self.assertAlmostEqual(resampled[-1]["t_rel"], 200.0)


class BuildClipTest(unittest.TestCase):
    """build_clip：端到端组装标准 clip JSON。"""

    def test_output_schema_v1(self):
        records = [
            {"index": 0, "t_ms": 1000, "angle": 0.1, "throttle": 0.2, "mode": "local"},
            {"index": 1, "t_ms": 1020, "angle": 0.2, "throttle": 0.3, "mode": "local"},
        ]
        clip = build_clip(records, source="tub_test", speed=1.0)
        self.assertEqual(clip["schema"], CLIP_SCHEMA)
        self.assertIn("samples", clip)
        self.assertEqual(len(clip["samples"]), 2)
        for s in clip["samples"]:
            self.assertIn("t_rel", s)
            self.assertIn("angle", s)
            self.assertIn("throttle", s)
        self.assertEqual(clip["meta"]["source"], "tub_test")
        self.assertEqual(clip["meta"]["speed"], 1.0)

    def test_first_sample_t_rel_is_zero(self):
        records = [
            {"index": 0, "t_ms": 5000, "angle": 0.1, "throttle": 0.2, "mode": "local"},
            {"index": 1, "t_ms": 5020, "angle": 0.2, "throttle": 0.3, "mode": "local"},
        ]
        clip = build_clip(records, source="tub_test", speed=1.0)
        self.assertAlmostEqual(clip["samples"][0]["t_rel"], 0.0)
        self.assertAlmostEqual(clip["samples"][1]["t_rel"], 20.0)


if __name__ == "__main__":
    unittest.main()
