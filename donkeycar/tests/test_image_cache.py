"""有界图像缓存的单元测试（2026-10 OOM 修复配套）。

覆盖两层：
1. BoundedImageCache 本体：LRU 淘汰、字节预算不变量（驻留量 <= 预算，
   单条超预算条目除外）、get 刷新顺序、缩预算即淘汰、非法预算拒绝；
2. TubRecord 集成：ARRAY/BINARY 策略下访问全部记录后缓存驻留量不超过
   CACHE_MAX_BYTES；NOCACHE 完全不留驻留；缓存命中结果与磁盘重载完全
   一致（数值行为不变）；处理器槽位语义保留（test_train 依赖的
   "第二次调用复用已缓存的处理后图像"）；多 epoch 驻留量平稳。
"""
from copy import copy

import numpy as np
import pytest
from PIL import Image

from donkeycar.config import Config
from donkeycar.pipeline.image_cache import BoundedImageCache, \
    DEFAULT_CACHE_MAX_BYTES, get_global_image_cache
from donkeycar.pipeline.types import TubRecord

FRAME_W, FRAME_H = 16, 12
FRAME_BYTES = FRAME_W * FRAME_H * 3


@pytest.fixture(autouse=True)
def clean_global_cache():
    """每个测试独占全局缓存：清空并恢复默认预算，避免互相污染。"""
    cache = get_global_image_cache()
    cache.clear()
    cache.configure(DEFAULT_CACHE_MAX_BYTES)
    yield cache
    cache.clear()
    cache.configure(DEFAULT_CACHE_MAX_BYTES)


def make_tub_images(tmp_path, count):
    """写 count 张小合成 jpg，返回 (base_path, underlying 列表)。"""
    img_dir = tmp_path / 'images'
    img_dir.mkdir()
    rng = np.random.default_rng(7)
    underlyings = []
    for i in range(count):
        arr = rng.integers(0, 255, (FRAME_H, FRAME_W, 3), dtype=np.uint8)
        name = f'{i}_cam_image_array_.jpg'
        Image.fromarray(arr).save(img_dir / name, format='JPEG')
        underlyings.append({
            'cam/image_array': name,
            'user/angle': 0.0,
            'user/throttle': 0.5,
            'user/mode': 'user',
        })
    return str(tmp_path), underlyings


def make_config(policy='ARRAY', max_bytes=DEFAULT_CACHE_MAX_BYTES):
    cfg = Config()
    cfg.IMAGE_W = FRAME_W
    cfg.IMAGE_H = FRAME_H
    cfg.IMAGE_DEPTH = 3
    cfg.CACHE_POLICY = policy
    cfg.CACHE_MAX_BYTES = max_bytes
    return cfg


# ---------------------------------------------------------------------------
# BoundedImageCache 本体
# ---------------------------------------------------------------------------

def test_put_evicts_beyond_budget():
    cache = BoundedImageCache(max_bytes=3 * FRAME_BYTES)
    for i in range(5):
        cache.put(f'k{i}', np.full((FRAME_H, FRAME_W, 3), i, np.uint8))
    assert cache.curr_bytes <= 3 * FRAME_BYTES
    assert len(cache) == 3
    # 最旧的 k0/k1 被淘汰，最新的三条驻留
    assert 'k0' not in cache and 'k1' not in cache
    assert 'k2' in cache and 'k3' in cache and 'k4' in cache


def test_get_refreshes_lru_order():
    cache = BoundedImageCache(max_bytes=2 * FRAME_BYTES)
    img = np.zeros((FRAME_H, FRAME_W, 3), np.uint8)
    cache.put('a', img)
    cache.put('b', img.copy())
    cache.get('a')  # a 变为最近使用
    cache.put('c', img.copy())  # 应淘汰 b 而不是 a
    assert 'a' in cache and 'b' not in cache and 'c' in cache


def test_single_oversized_entry_is_retained():
    # 预算放不下单条时保留最新一条（退化为单条缓存），而不是丢光或死循环
    cache = BoundedImageCache(max_bytes=FRAME_BYTES // 2)
    cache.put('a', np.zeros((FRAME_H, FRAME_W, 3), np.uint8))
    assert len(cache) == 1 and 'a' in cache
    cache.put('b', np.ones((FRAME_H, FRAME_W, 3), np.uint8))
    assert len(cache) == 1 and 'b' in cache


def test_shrinking_budget_evicts():
    cache = BoundedImageCache(max_bytes=5 * FRAME_BYTES)
    img = np.zeros((FRAME_H, FRAME_W, 3), np.uint8)
    for i in range(5):
        cache.put(f'k{i}', img)
    assert len(cache) == 5
    assert cache.configure(2 * FRAME_BYTES) is True
    assert len(cache) == 2
    assert cache.curr_bytes <= 2 * FRAME_BYTES


def test_configure_rejects_non_positive_budget():
    cache = BoundedImageCache()
    with pytest.raises(ValueError):
        cache.configure(0)
    with pytest.raises(ValueError):
        cache.configure(-1)


def test_replace_key_does_not_double_count():
    cache = BoundedImageCache(max_bytes=2 * FRAME_BYTES)
    img = np.zeros((FRAME_H, FRAME_W, 3), np.uint8)
    cache.put('k', img)
    cache.put('k', img.copy())  # 覆盖同键不应使记账翻倍
    assert cache.curr_bytes == FRAME_BYTES
    assert len(cache) == 1


# ---------------------------------------------------------------------------
# TubRecord 集成
# ---------------------------------------------------------------------------

def test_array_policy_residency_bounded(tmp_path):
    base, underlyings = make_tub_images(tmp_path, 6)
    cfg = make_config('ARRAY', max_bytes=3 * FRAME_BYTES)
    records = [TubRecord(cfg, base, u) for u in underlyings]
    for rec in records:
        rec.image()
    cache = get_global_image_cache()
    assert cache.curr_bytes <= 3 * FRAME_BYTES
    assert len(cache) <= 3
    # 最近访问的三条仍在（jpg 解码后恰为 FRAME_BYTES）
    for rec in records[-3:]:
        assert rec._image is not None


def test_nocache_leaves_cache_empty_and_returns_images(tmp_path):
    base, underlyings = make_tub_images(tmp_path, 4)
    cfg = make_config('NOCACHE')
    records = [TubRecord(cfg, base, u) for u in underlyings]
    first = [rec.image() for rec in records]
    assert all(img is not None for img in first)
    cache = get_global_image_cache()
    assert len(cache) == 0 and cache.curr_bytes == 0
    # 第二遍（NOCACHE 每次重读磁盘）结果一致
    second = [rec.image() for rec in records]
    for a, b in zip(first, second):
        assert np.array_equal(a, b)


def test_binary_policy_residency_bounded(tmp_path):
    base, underlyings = make_tub_images(tmp_path, 6)
    # BINARY 存 jpg 字节（比解码数组小），预算按 2 帧原始数组大小给
    cfg = make_config('BINARY', max_bytes=2 * FRAME_BYTES)
    records = [TubRecord(cfg, base, u) for u in underlyings]
    first = [rec.image() for rec in records]
    cache = get_global_image_cache()
    assert cache.curr_bytes <= 2 * FRAME_BYTES
    assert len(cache) < 6  # 驻留条数受预算约束，而非全量驻留
    second = [rec.image() for rec in records]
    for a, b in zip(first, second):
        assert np.array_equal(a, b)


def test_cached_result_matches_fresh_load(tmp_path):
    """数值行为不变：有界缓存命中值 == 磁盘重载值。"""
    base, underlyings = make_tub_images(tmp_path, 4)
    cfg_cached = make_config('ARRAY', max_bytes=10 * FRAME_BYTES)
    cached_records = [TubRecord(cfg_cached, base, u) for u in underlyings]
    pass1 = [rec.image() for rec in cached_records]
    pass2 = [rec.image() for rec in cached_records]
    # NOCACHE 记录每次从磁盘现读，作为真值参照
    cfg_fresh = make_config('NOCACHE')
    fresh_records = [TubRecord(cfg_fresh, base, u) for u in underlyings]
    fresh = [rec.image() for rec in fresh_records]
    for p1, p2, fr in zip(pass1, pass2, fresh):
        assert np.array_equal(p1, p2)
        assert np.array_equal(p1, fr)


def test_processor_slot_semantics_preserved(tmp_path):
    """test_train 依赖的槽位语义：processor 结果驻留后，下一次带不同
    processor 的调用作用在缓存值上；条目被淘汰后则回退为重读原图。"""
    base, underlyings = make_tub_images(tmp_path, 1)
    big = make_config('ARRAY', max_bytes=10 * FRAME_BYTES)
    rec = TubRecord(big, base, underlyings[0])
    p1 = lambda a: a * 2  # noqa: E731
    p2 = lambda a: a + 1  # noqa: E731
    out1 = rec.image(processor=p1)
    # 命中缓存：p2 作用在已缓存的 p1(raw) 上
    assert np.array_equal(rec.image(processor=p2), p2(out1))

    # 同一 underlying、槽位被淘汰后 → 回退为重读原图，p2 只作用一次
    tiny = make_config('ARRAY', max_bytes=1)
    rec2 = TubRecord(tiny, base, underlyings[0])
    rec2.image(processor=p1)  # 单条超预算仍会短暂驻留
    get_global_image_cache().clear()  # 模拟该槽位被 LRU 淘汰
    cfg_fresh = make_config('NOCACHE')
    fresh_raw = TubRecord(cfg_fresh, base, underlyings[0]).image()
    assert np.array_equal(rec2.image(processor=p2), p2(fresh_raw))


def test_multi_epoch_residency_stable(tmp_path):
    """连续多 epoch：驻留量不随 epoch 增长，且每 epoch 数据一致。"""
    base, underlyings = make_tub_images(tmp_path, 6)
    cfg = make_config('ARRAY', max_bytes=2 * FRAME_BYTES)
    records = [TubRecord(cfg, base, u) for u in underlyings]
    cache = get_global_image_cache()
    epoch_images = []
    residency = []
    for _ in range(4):
        epoch_images.append([rec.image() for rec in records])
        residency.append(cache.curr_bytes)
        assert cache.curr_bytes <= 2 * FRAME_BYTES
    assert len(set(residency)) == 1, f'residency drifted: {residency}'
    for later in epoch_images[1:]:
        for first_img, later_img in zip(epoch_images[0], later):
            assert np.array_equal(first_img, later_img)


def test_copy_shares_cache_slot(tmp_path):
    base, underlyings = make_tub_images(tmp_path, 2)
    cfg = make_config('ARRAY')
    rec = TubRecord(cfg, base, underlyings[0])
    img = rec.image()
    rec2 = copy(rec)
    assert rec2._image is img  # __copy__ 语义：共享同一槽位对象


def test_budget_plumbed_from_config(tmp_path):
    base, underlyings = make_tub_images(tmp_path, 1)
    cfg = make_config('ARRAY', max_bytes=FRAME_BYTES)
    TubRecord(cfg, base, underlyings[0])  # 构造即把预算配到全局缓存
    assert get_global_image_cache().max_bytes == FRAME_BYTES
