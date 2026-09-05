"""issue #373：AI 清理「碰撞后倒车」——识别器单元测试 + 路由接口测试。

识别器测试直接用合成的 (steering/)throttle 序列构造记录：
- 碰撞后倒车（急停后倒车 / 直接坠入倒车）→ 应识别；
- 纯倒车（静止起步直接倒车）、正常行驶、急停不倒车 → 不识别；
- 跨会话边界不关联。
"""
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_clean_engine import AiCleanConfig, CollisionReverseHeuristic


def _records(throttles, start_index=0, session_id="s0"):
    """把油门序列转成 record dict 列表（物理 _index 连续）。"""
    return [
        {
            "_index": start_index + i,
            "_session_id": session_id,
            "_timestamp_ms": 1000 + i * 50,
            "user/angle": 0.0,
            "user/throttle": t,
        }
        for i, t in enumerate(throttles)
    ]


class TestCollisionReverseHeuristic:
    def test_stop_then_reverse_is_flagged(self):
        # 正向行驶 → 急停（0）→ 倒车 5 帧 → 恢复前进
        seq = [0.4] * 20 + [0.0] * 8 + [-0.3] * 5 + [0.4] * 10
        segments = CollisionReverseHeuristic().detect(_records(seq))

        assert len(segments) == 1
        seg = segments[0]
        assert seg.reason_code == "stop_then_reverse"
        # 碰撞点=首个急停帧（pos 20），前扩 5 → pos 15；倒车尾 pos 32，后扩 5 → pos 37
        assert seg.start_index == 15
        assert seg.end_index == 37
        assert seg.frame_count == 23
        assert seg.indexes == list(range(15, 38))
        assert seg.detail["collision_index"] == 20
        assert seg.detail["reverse_start_index"] == 28
        assert seg.detail["reverse_frames"] == 5
        assert seg.detail["peak_forward_throttle"] == 0.4

    def test_plunge_reverse_is_flagged(self):
        # 正向行驶直接被打成倒车（无停稳过程）
        seq = [0.5] * 10 + [-0.4] * 6 + [0.5] * 10
        segments = CollisionReverseHeuristic().detect(_records(seq))

        assert len(segments) == 1
        seg = segments[0]
        assert seg.reason_code == "plunge_reverse"
        # anchor=倒车起点 pos 10，前扩 5 → 5；倒车尾 pos 15，后扩 5 → 20
        assert seg.start_index == 5
        assert seg.end_index == 20

    def test_pure_reverse_from_standstill_not_flagged(self):
        # 静止 → 直接倒车（起步倒车，前方无正向行驶）→ 纯倒车，不删
        seq = [0.0] * 15 + [-0.3] * 10 + [0.0] * 5
        assert CollisionReverseHeuristic().detect(_records(seq)) == []

    def test_normal_driving_not_flagged(self):
        seq = [0.3, 0.5, 0.2, 0.6, 0.0, 0.4, 0.45, 0.0, 0.35] * 3
        assert CollisionReverseHeuristic().detect(_records(seq)) == []

    def test_stop_without_reverse_not_flagged(self):
        # 急停后停在原地再起步——没有倒车段
        seq = [0.5] * 10 + [0.0] * 20 + [0.5] * 10
        assert CollisionReverseHeuristic().detect(_records(seq)) == []

    def test_short_reverse_blip_not_flagged(self):
        # 急停后只有 2 帧倒车（< min_reverse_frames）→ 误触级别，不删
        seq = [0.4] * 10 + [0.0] * 5 + [-0.3] * 2 + [0.4] * 10
        assert CollisionReverseHeuristic().detect(_records(seq)) == []

    def test_reverse_long_after_collision_not_flagged(self):
        # 碰撞后过了很久（> collision_lookback_frames）才倒车 → 不关联
        cfg = AiCleanConfig(collision_lookback_frames=10)
        seq = [0.4] * 10 + [0.0] * 20 + [-0.3] * 5 + [0.4] * 5
        assert CollisionReverseHeuristic(config=cfg).detect(_records(seq)) == []

    def test_two_collisions_produce_two_segments(self):
        seq = (
            [0.4] * 15 + [0.0] * 5 + [-0.3] * 4 + [0.4] * 40
            + [0.0] * 5 + [-0.3] * 4 + [0.4] * 10
        )
        segments = CollisionReverseHeuristic().detect(_records(seq))
        assert len(segments) == 2
        assert segments[0].end_index < segments[1].start_index

    def test_nearby_segments_merge(self):
        # 同一次碰撞后倒两下（倒车 4 帧 → 停 2 帧 → 再倒 4 帧）→ 合并为一段
        seq = [0.4] * 10 + [0.0] * 5 + [-0.3] * 4 + [0.0] * 2 + [-0.3] * 4 + [0.4] * 10
        segments = CollisionReverseHeuristic().detect(_records(seq))
        assert len(segments) == 1
        # 间隙（停 2 帧）也圈进片段
        seg = segments[0]
        assert seg.indexes == list(range(seg.start_index, seg.end_index + 1))

    def test_session_boundary_breaks_association(self):
        # 会话 A 末尾碰撞急停，会话 B 开头倒车 → 跨会话不关联，不删
        recs = _records([0.4] * 10 + [0.0] * 5, session_id="a") + _records(
            [-0.3] * 5 + [0.4] * 5, start_index=15, session_id="b"
        )
        assert CollisionReverseHeuristic().detect(recs) == []

    def test_pilot_throttle_fallback(self):
        # 无 user/throttle 时回退 pilot/throttle
        seq = [0.4] * 10 + [0.0] * 5 + [-0.3] * 5 + [0.4] * 5
        recs = [
            {"_index": i, "_session_id": "s0", "pilot/throttle": t}
            for i, t in enumerate(seq)
        ]
        segments = CollisionReverseHeuristic().detect(recs)
        assert len(segments) == 1

    def test_missing_throttle_not_flagged(self):
        # 油门字段缺失：不得虚构碰撞/倒车
        recs = [{"_index": i, "_session_id": "s0"} for i in range(30)]
        assert CollisionReverseHeuristic().detect(recs) == []

    def test_segment_bounds_clamped_at_sequence_edges(self):
        # 碰撞发生在开头附近：前扩不能越过第 0 帧
        seq = [0.4] * 3 + [0.0] * 4 + [-0.3] * 5
        segments = CollisionReverseHeuristic().detect(_records(seq))
        assert len(segments) == 1
        assert segments[0].start_index == 0
        assert segments[0].end_index == len(seq) - 1


def _make_tub(base_path: Path, throttles):
    """按油门序列写一个真实 tub（单会话）。"""
    from donkeycar.parts.tub_v2 import Tub

    tub = Tub(
        str(base_path),
        inputs=["cam/image_array", "user/angle", "user/throttle"],
        types=["image_array", "float", "float"],
    )
    for t in throttles:
        tub.write_record({"user/angle": 0.0, "user/throttle": t})
    tub.close()


def _build_client():
    from routers import tub as tub_router

    app = FastAPI()
    app.include_router(tub_router.router, prefix="/api/tub")
    return TestClient(app)


# 25 帧：前进 8 → 急停 4 → 倒车 5 → 前进 8；命中片段 pos 3..21（前扩 5/后扩 5）
COLLISION_SEQ = [0.4] * 8 + [0.0] * 4 + [-0.3] * 5 + [0.4] * 8


class TestAiCleanApi:
    def test_candidates_lists_current_and_sibling_tubs(self, tmp_path):
        tub_a = tmp_path / "data"
        tub_b = tmp_path / "data_sim"
        _make_tub(tub_a, COLLISION_SEQ)
        _make_tub(tub_b, [0.4] * 10)
        (tmp_path / "not_a_tub").mkdir()

        client = _build_client()
        response = client.get("/api/tub/ai_clean/candidates", params={"tubPath": str(tub_a)})

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] is True
        paths = [t["path"] for t in payload["tubs"]]
        assert str(tub_a) in paths and str(tub_b) in paths
        assert all("not_a_tub" not in p for p in paths)
        current = [t for t in payload["tubs"] if t["is_current"]]
        assert len(current) == 1 and current[0]["path"] == str(tub_a)

    def test_candidates_rejects_non_tub(self, tmp_path):
        client = _build_client()
        response = client.get("/api/tub/ai_clean/candidates", params={"tubPath": str(tmp_path)})
        assert response.status_code == 400

    def test_scan_reports_segments_per_tub(self, tmp_path):
        tub_a = tmp_path / "data"
        tub_b = tmp_path / "data_clean"
        _make_tub(tub_a, COLLISION_SEQ)
        _make_tub(tub_b, [0.4] * 10 + [0.0] * 5 + [-0.3] * 2)  # 倒车太短，不命中

        client = _build_client()
        response = client.post(
            "/api/tub/ai_clean/scan",
            json={"tub_paths": [str(tub_a), str(tub_b)]},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] is True
        assert payload["total_segments"] == 1
        by_path = {t["tub_path"]: t for t in payload["tubs"]}
        seg = by_path[str(tub_a)]["segments"][0]
        assert seg["start_index"] == 3
        assert seg["end_index"] == 21
        assert seg["frame_count"] == 19
        assert by_path[str(tub_b)]["segment_count"] == 0

    def test_scan_keeps_per_tub_error(self, tmp_path):
        tub_a = tmp_path / "data"
        _make_tub(tub_a, COLLISION_SEQ)

        client = _build_client()
        response = client.post(
            "/api/tub/ai_clean/scan",
            json={"tub_paths": [str(tub_a), str(tmp_path / "missing")]},
        )

        assert response.status_code == 200
        payload = response.json()
        by_path = {t["tub_path"]: t for t in payload["tubs"]}
        assert by_path[str(tub_a)]["segment_count"] == 1
        assert "error" in by_path[str(tmp_path / "missing")]

    def test_execute_deletes_indexes_and_preserves_rest(self, tmp_path):
        _make_tub(tmp_path, COLLISION_SEQ)
        client = _build_client()

        scan = client.post(
            "/api/tub/ai_clean/scan", json={"tub_paths": [str(tmp_path)]}
        ).json()
        indexes = scan["tubs"][0]["segments"][0]["indexes"]

        response = client.post(
            "/api/tub/ai_clean/execute",
            json={"deletions": [{"tub_path": str(tmp_path), "indexes": indexes}]},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] is True
        assert payload["total_deleted"] == len(indexes)
        assert payload["results"][0]["deleted_count"] == len(indexes)

        # 删除后扫描同一 tub：片段帧已不在存活记录里，不再命中
        rescan = client.post(
            "/api/tub/ai_clean/scan", json={"tub_paths": [str(tmp_path)]}
        ).json()
        assert rescan["total_segments"] == 0

        # manifest 层一致性：被删索引出现在 deleted_indexes，存活帧数吻合
        from donkeycar.parts.tub_v2 import Tub

        tub = Tub(str(tmp_path), read_only=True)
        try:
            remaining = [r["_index"] for r in tub]
            assert set(indexes).issubset(tub.manifest.deleted_indexes)
            assert len(remaining) == len(COLLISION_SEQ) - len(indexes)
            assert not set(remaining) & set(indexes)
        finally:
            tub.close()

    def test_execute_syncs_globally_loaded_tub(self, tmp_path):
        _make_tub(tmp_path, COLLISION_SEQ)
        from routers import tub as tub_router

        client = _build_client()
        # 先把该 tub 加载为全局当前 tub
        load = client.post("/api/tub/load", json={"path": str(tmp_path)})
        assert load.status_code == 200
        assert load.json()["record_count"] == len(COLLISION_SEQ)

        scan = client.post(
            "/api/tub/ai_clean/scan", json={"tub_paths": [str(tmp_path)]}
        ).json()
        indexes = scan["tubs"][0]["segments"][0]["indexes"]
        response = client.post(
            "/api/tub/ai_clean/execute",
            json={"deletions": [{"tub_path": str(tmp_path), "indexes": indexes}]},
        )

        payload = response.json()
        expected = len(COLLISION_SEQ) - len(indexes)
        assert payload["record_count"] == expected
        assert set(indexes).issubset(set(payload["deleted_indexes"]))

        # 全局记录已同步刷新
        records = client.get("/api/tub/records", params={"limit": 1000}).json()
        assert records["total"] == expected

        tub_router.current_tub = None
        tub_router.current_records = []
        tub_router.current_tub_path = ""

    def test_execute_rejects_empty_request(self):
        client = _build_client()
        response = client.post("/api/tub/ai_clean/execute", json={"deletions": []})
        assert response.status_code == 400
