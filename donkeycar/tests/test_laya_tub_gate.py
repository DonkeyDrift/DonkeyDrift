"""laya_tub_gate.py 的单元 + 端到端测试。

覆盖：
  - tub v1/v2 读取（含 _deleted 跳过、v1 数字序排序）
  - 窗口特征工程（静止 vs 运动）
  - 规则引擎：需求文档 5.1 的冒烟场景（40 帧巡线 + 20 帧撞墙静止）
  - 决策逻辑（阈值、balance 可复现、保守并集语义）
  - report / delete / export 三模式端到端（用官方 Tub 构造真实格式的合成 tub）
  - export 的索引坐标系回归测试：删除过记录的 tub（_index 有空洞）不能删错行
  - eval 模式（合成基准，不需要 laya）

Laya 引擎本身不在此测试（需要 2GB 依赖 + 模型下载），由 scripts/laya_tub_gate.md
里的手动验证流程覆盖。
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest

import numpy as np

SCRIPT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "laya_tub_gate.py"))
_spec = importlib.util.spec_from_file_location("laya_tub_gate", SCRIPT_PATH)
gate = importlib.util.module_from_spec(_spec)
sys.modules["laya_tub_gate"] = gate
_spec.loader.exec_module(gate)

from donkeycar.parts.tub_v2 import Tub  # noqa: E402

INPUTS = ["cam/image_array", "user/angle", "user/throttle"]
TYPES = ["image_array", "float", "float"]

RNG = np.random.default_rng(42)


def normal_frame(i):
    """模拟巡线帧：随机噪声纹理（相邻帧差异大）+ 平滑正弦转向。"""
    img = RNG.integers(0, 255, size=(120, 160, 3), dtype=np.uint8)
    return {"cam/image_array": img, "user/angle": 0.3 * np.sin(i / 8.0),
            "user/throttle": 0.5, "user/mode": "user"}


def stall_frame(i):
    """模拟撞墙静止帧：恒定亮画面 + 油门为 0 + 转向冻在固定值。"""
    img = np.full((120, 160, 3), 210, dtype=np.uint8)
    return {"cam/image_array": img, "user/angle": 0.42,
            "user/throttle": 0.0, "user/mode": "user"}


def write_tub(path, n_normal, n_stall, delete_first=False):
    """用官方 Tub 写一个合成 tub：前 n_normal 帧巡线，后 n_stall 帧静止。"""
    tub = Tub(path, inputs=INPUTS, types=TYPES)
    for i in range(n_normal):
        tub.write_record(normal_frame(i))
    for i in range(n_stall):
        tub.write_record(stall_frame(i))
    if delete_first:
        tub.delete_records([0])  # 制造 _index 空洞，考验索引坐标系
    tub.close()


def run_main(argv):
    gate.main(argv)


class TestLoader(unittest.TestCase):

    def setUp(self):
        self._dir = tempfile.mkdtemp()

    def test_load_v2_roundtrip(self):
        path = os.path.join(self._dir, "tub_v2")
        write_tub(path, n_normal=6, n_stall=0)
        records, inputs, types = gate.load_tub_records(path)
        self.assertEqual(len(records), 6)
        # manifest.json 里的 schema 应被解析出来
        self.assertEqual(inputs, INPUTS)
        self.assertEqual(types, TYPES)
        self.assertEqual([r["_index"] for r in records], list(range(6)))

    def test_load_v2_skips_deleted(self):
        path = os.path.join(self._dir, "tub_del")
        write_tub(path, n_normal=5, n_stall=0, delete_first=True)
        records, _, _ = gate.load_tub_records(path)
        # _index 0 被软删除：剩 4 条，且保留原始索引 1..4（位置 0..3）
        self.assertEqual(len(records), 4)
        self.assertEqual([r["_index"] for r in records], [1, 2, 3, 4])

    def test_load_v1_fallback_numeric_sort(self):
        path = os.path.join(self._dir, "tub_v1")
        os.makedirs(path)
        with open(os.path.join(path, "meta.json"), "w") as fp:
            json.dump({"inputs": ["user/angle"], "types": ["float"]}, fp)
        for i in range(12):  # 超过 10 个文件，字典序会把 record_10 排到 record_2 前面
            with open(os.path.join(path, f"record_{i}.json"), "w") as fp:
                json.dump({"user/angle": i / 100.0, "user/throttle": 0.5}, fp)
        records, inputs, types = gate.load_tub_records(path)
        self.assertEqual(len(records), 12)
        self.assertEqual(inputs, ["user/angle"])
        angles = [r["user/angle"] for r in records]
        self.assertEqual(angles, sorted(angles))  # 数字序，非字典序

    def test_load_missing_tub(self):
        with self.assertRaises(SystemExit):
            gate.load_tub_records(os.path.join(self._dir, "nope"))


class TestWindowFeatures(unittest.TestCase):

    def _rec(self, idx, angle, thr, ts):
        return {"_index": idx, "_timestamp_ms": ts,
                "user/angle": angle, "user/throttle": thr}

    def test_stationary_vs_moving(self):
        base = np.full((48, 64), 0.8, dtype=np.float32)
        moving = [np.clip(base + RNG.normal(0, 0.05, base.shape), 0, 1).astype(np.float32)
                  for _ in range(10)]
        win_moving = [self._rec(i, 0.1 * np.sin(i), 0.5, 1_000_000 + i * 50) for i in range(10)]
        gray_moving = {i: g for i, g in enumerate(moving)}
        fm = gate.window_features(win_moving, gray_moving)
        self.assertGreater(fm["frame_motion"], 0.02)
        self.assertAlmostEqual(fm["thr_zero_ratio"], 0.0)

        win_stall = [self._rec(i, 0.42, 0.0, 2_000_000 + i * 50) for i in range(10)]
        gray_stall = {i: base.copy() for i in range(10)}
        fs = gate.window_features(win_stall, gray_stall)
        self.assertLess(fs["frame_motion"], 0.001)
        self.assertAlmostEqual(fs["thr_zero_ratio"], 1.0)
        self.assertAlmostEqual(fs["brightness"], 0.8, places=2)

    def test_no_vision_sentinel(self):
        win = [self._rec(i, 0.0, 0.5, i * 50) for i in range(10)]
        f = gate.window_features(win, {})  # 无任何灰度缓存
        self.assertEqual(f["frame_motion"], -1.0)  # -1 是"拿不到"，不是"真的为 0"

    def test_timestamp_field_compat(self):
        # v2 写 _timestamp_ms，老数据可能是 timestamp_ms
        win = [{"_index": i, "timestamp_ms": 1_000 + i * 50,
                "user/angle": 0.0, "user/throttle": 0.4} for i in range(10)]
        f = gate.window_features(win, {})
        self.assertAlmostEqual(f["dt_ms_mean"], 50.0, places=3)


class TestHeuristicSmoke(unittest.TestCase):
    """需求文档 5.1 的冒烟测试：40 帧巡线 + 20 帧撞墙静止，规则引擎应抓出静止段。"""

    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.tub_path = os.path.join(self._dir, "tub_smoke")
        write_tub(self.tub_path, n_normal=40, n_stall=20)

    def test_stall_windows_flagged(self):
        records, _, _ = gate.load_tub_records(self.tub_path)
        feats, _ = gate.build_windows(records, self.tub_path, window=10, stride=5,
                                      no_vision=False)
        scores = gate.heuristic_score_all(feats)
        by_start = {f["start"]: (f, s) for f, s in zip(feats, scores)}
        # 纯静止窗口（start>=40）必须全部命中 stationary_stall
        for start in (40, 45, 50):
            f, s = by_start[start]
            self.assertEqual(s["defect"], "stationary_stall", f"start={start}")
            self.assertLess(s["is_clean"], 0.35)
            self.assertLess(f["frame_motion"], 0.004)
        # 纯巡线窗口（end<=39）必须干净
        for start in (0, 15, 30):
            _, s = by_start[start]
            self.assertEqual(s["defect"], "none", f"start={start}")
            self.assertGreaterEqual(s["is_clean"], 0.35)
        # 机动分类：正弦 ±0.3 的窗口应被归为转向而非 brake
        self.assertIn(by_start[0][1]["maneuver"], ("left", "right", "straight"))


class TestDecide(unittest.TestCase):

    def _feats(self, n):
        out = []
        for i in range(n):
            out.append({"start": i * 5, "end": i * 5 + 9, "indices": list(range(i * 5, i * 5 + 10))})
        return out

    def test_threshold_and_union(self):
        feats = self._feats(3)
        scores = [{"is_clean": 0.9, "quality": "good", "defect": "none", "maneuver": "straight"},
                  {"is_clean": 0.1, "quality": "garbage", "defect": "stationary_stall", "maneuver": "brake"},
                  {"is_clean": 0.9, "quality": "good", "defect": "none", "maneuver": "straight"}]
        keep, drop = gate.decide(feats, scores, threshold=0.35, balance=False,
                                 straight_keep=0.5, seed=0)
        self.assertEqual(len(drop), 1)
        self.assertEqual(drop[0]["action"], "drop")
        self.assertEqual(drop[0]["indices"], list(range(5, 15)))  # 携带真实索引列表

    def test_balance_reproducible(self):
        feats = self._feats(50)
        scores = [{"is_clean": 0.9, "quality": "good", "defect": "none",
                   "maneuver": "straight"}] * 50
        k1, d1 = gate.decide(feats, scores, 0.35, True, 0.5, seed=7)
        k2, d2 = gate.decide(feats, scores, 0.35, True, 0.5, seed=7)
        self.assertEqual([v["indices"] for v in d1], [v["indices"] for v in d2])  # 同种子同结果
        self.assertTrue(all(v["action"] == "downsample" for v in d1))
        self.assertAlmostEqual(len(d1) / 50, 0.5, delta=0.2)  # 保留比例约一半


class TestModesEndToEnd(unittest.TestCase):

    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.tub_path = os.path.join(self._dir, "tub_e2e")
        write_tub(self.tub_path, n_normal=40, n_stall=20)

    def _report_lines(self):
        with open(os.path.join(self.tub_path, "laya_gate_report.jsonl")) as fp:
            return [json.loads(l) for l in fp if l.strip()]

    def test_report_mode_does_not_touch_tub(self):
        manifest = os.path.join(self.tub_path, "manifest.json")
        with open(manifest, "rb") as fp:
            before = fp.read()
        run_main(["--tub", self.tub_path, "--mode", "report",
                  "--engine", "heuristic"])
        with open(manifest, "rb") as fp:
            self.assertEqual(fp.read(), before)  # report 模式绝不改动数据
        lines = self._report_lines()
        self.assertEqual(len(lines), 11)  # 60 帧 window=10 stride=5 → 11 个窗口
        for row in lines:
            for key in ("start", "end", "indices", "is_clean", "quality",
                        "defect", "maneuver", "action", "engine", "frame_motion"):
                self.assertIn(key, row)
        self.assertTrue(all(row["engine"] == "heuristic" for row in lines))
        self.assertTrue(any(row["defect"] == "stationary_stall" for row in lines))

    def test_delete_mode_soft_deletes(self):
        run_main(["--tub", self.tub_path, "--mode", "delete",
                  "--engine", "heuristic"])
        tub = Tub(self.tub_path)
        alive = sum(1 for _ in tub)
        tub.close()
        # 纯静止段 40..59 被删；过渡窗口(35..44)因亮度突变判 off_track 也被删
        self.assertEqual(alive, 35)

    def test_export_mode(self):
        out = os.path.join(self._dir, "tub_clean")
        run_main(["--tub", self.tub_path, "--mode", "export", "--engine", "heuristic",
                  "--out", out])
        dst = Tub(out)
        rows = [r for r in dst]
        dst.close()
        # 与 delete 模式同口径：60 - (静止段 40..59 + 过渡段 35..44 去重) = 35 条
        self.assertEqual(len(rows), 35)
        self.assertTrue(all(r["user/throttle"] > 0 for r in rows))  # 静止帧一条都不该漏进来
        self.assertTrue(all(os.path.exists(os.path.join(out, "images", r["cam/image_array"]))
                            for r in rows))
        # 原 tub 未动
        src = Tub(self.tub_path)
        self.assertEqual(sum(1 for _ in src), 60)
        src.close()


class TestExportIndexCoordinates(unittest.TestCase):
    """回归测试：删除过记录的 tub（_index 有空洞）里，export 不能按"位置"误删。

    草稿版用 range(start, end+1) 生成坏索引、用 set(range(len(records))) 做保留集，
    两套坐标系在有空洞时错位，会把坏数据留在导出结果里。
    """

    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.tub_path = os.path.join(self._dir, "tub_gap")
        # 21 帧（10 巡线 + 11 静止）再软删 _index=0 → 活记录恰好 20 条（_index 1..20），
        # window=5/stride=5 时尾部静止帧也能被完整窗口覆盖；空洞则考验索引坐标系
        write_tub(self.tub_path, n_normal=10, n_stall=11, delete_first=True)

    def test_no_stall_leaks_after_index_gap(self):
        out = os.path.join(self._dir, "tub_out")
        run_main(["--tub", self.tub_path, "--mode", "export", "--engine", "heuristic",
                  "--window", "5", "--stride", "5", "--out", out])
        dst = Tub(out)
        rows = [r for r in dst]
        dst.close()
        # 静止帧特征：throttle==0。无论索引怎么错位，导出结果里不允许混进静止帧
        leaked = [r for r in rows if r["user/throttle"] <= 0]
        self.assertEqual(leaked, [], f"静止帧泄漏进导出 tub: {leaked}")


class TestEvalMode(unittest.TestCase):

    def setUp(self):
        self._dir = tempfile.mkdtemp()

    def test_synthetic_eval_heuristic(self):
        rep = os.path.join(self._dir, "eval.json")
        run_main(["--mode", "eval", "--engine", "heuristic",
                  "--eval-windows", "60", "--report", rep])
        with open(rep) as fp:
            results = json.load(fp)["results"]
        self.assertEqual(len(results), 1)  # 未装 laya 时自动只跑 heuristic
        r = results[0]
        self.assertEqual(r["engine"], "heuristic")
        self.assertGreaterEqual(r["accuracy"], 0.9)   # 自家地盘应接近满分
        self.assertLessEqual(r["ece"], 0.15)
        self.assertGreaterEqual(r["defect_accuracy"], 0.9)
        self.assertEqual(len(r["reliability"]), 10)   # 可靠性曲线 10 个桶

    def test_labels_mode_rejects_unannotated(self):
        labels_path = os.path.join(self._dir, "labels.jsonl")
        with open(labels_path, "w") as fp:
            fp.write(json.dumps({"start": 0, "end": 9}) + "\n")  # 没有 label_clean
        with self.assertRaises(SystemExit):
            run_main(["--mode", "eval", "--engine", "heuristic", "--labels", labels_path])


class TestEceMetric(unittest.TestCase):

    def test_known_value(self):
        # 4 个样本分两桶：桶[0.2,0.3) 概率 0.2、两个全错；桶[0.8,0.9] 概率 0.8、一对一错
        probs = [0.2, 0.2, 0.8, 0.8]
        labels = [0, 0, 1, 0]
        ece, rows = gate.ece_and_reliability(probs, labels)
        # ECE = 0.5*|0-0.2| + 0.5*|0.5-0.8| = 0.1 + 0.15 = 0.25
        self.assertAlmostEqual(ece, 0.25, places=6)
        self.assertEqual([r["n"] for r in rows][2], 2)

    def test_empty_bins_reported(self):
        ece, rows = gate.ece_and_reliability([0.5, 0.5], [1, 0])
        self.assertEqual(sum(r["n"] for r in rows if r["n"] > 0), 2)
        self.assertTrue(any(r["n"] == 0 and r["acc"] is None for r in rows))


if __name__ == "__main__":
    unittest.main()
