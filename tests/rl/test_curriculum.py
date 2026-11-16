"""M2 D3:出生课程单测(离线,零 sim)。"""

import pytest

from donkeydrifter.rl.curriculum import CurriculumConfig, SpawnCurriculum


def test_same_seed_same_sequence():
    a = SpawnCurriculum(CurriculumConfig(seed=42))
    b = SpawnCurriculum(CurriculumConfig(seed=42))
    seq_a = [a.sample() for _ in range(20)]
    seq_b = [b.sample() for _ in range(20)]
    assert seq_a == seq_b


def test_different_seed_different_sequence():
    a = SpawnCurriculum(CurriculumConfig(seed=42))
    b = SpawnCurriculum(CurriculumConfig(seed=7))
    assert [a.sample() for _ in range(10)] != [b.sample() for _ in range(10)]


def test_lateral_is_signed_and_in_band():
    cur = SpawnCurriculum(CurriculumConfig(seed=1, lateral=1.0))
    lats = [cur.sample()["lateral_offset"] for _ in range(200)]
    assert all(-1.0 <= x <= 1.0 for x in lats)
    signs = {1 if x > 0 else -1 if x < 0 else 0 for x in lats}
    assert 1 in signs and -1 in signs  # 双侧都出现(防单侧偏科)


def test_heading_noise_nonnegative_and_bounded():
    cur = SpawnCurriculum(CurriculumConfig(seed=2, heading=8.0))
    hs = [cur.sample()["heading_noise"] for _ in range(100)]
    assert all(0.0 <= x <= 8.0 for x in hs)


def test_node_range_passed_through_when_set():
    cur = SpawnCurriculum(CurriculumConfig(seed=3, node_min=10, node_max=50))
    f = cur.sample()
    assert f["node_min"] == 10 and f["node_max"] == 50


def test_reset_sequence_replays():
    cur = SpawnCurriculum(CurriculumConfig(seed=9))
    first = [cur.sample() for _ in range(5)]
    cur.reset_sequence()
    assert [cur.sample() for _ in range(5)] == first


def test_fields_literal_for_env_passthrough():
    """字段必须是 env reset 消息的直接字段子集(字面透传契约)。"""
    cur = SpawnCurriculum(CurriculumConfig(seed=4))
    f = cur.sample()
    assert set(f) <= {"lateral_offset", "heading_noise", "node_min",
                      "node_max", "seed"}
    assert isinstance(f["seed"], int) and f["seed"] > 0
