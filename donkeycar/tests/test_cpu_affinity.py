import os
import sys

import pytest

from donkeycar.parts import cpu_affinity

LINUX = sys.platform.startswith("linux") and cpu_affinity._HAS_SCHED

pytestmark = pytest.mark.skipif(
    not LINUX, reason="CPU 亲和性仅在 Linux 且有 sched_setaffinity 时生效")


@pytest.fixture(autouse=True)
def clear_caches(monkeypatch):
    monkeypatch.delenv("DRIVE_WEBRTC_AFFINITY", raising=False)
    monkeypatch.delenv("DRIVE_WEBRTC_MEDIA_CPUS", raising=False)
    monkeypatch.delenv("DRIVE_WEBRTC_AFFINITY_PIN_VEHICLE", raising=False)
    cpu_affinity.media_cpu_set.cache_clear()
    yield
    cpu_affinity.media_cpu_set.cache_clear()


def test_parse_cpu_list_formats():
    assert cpu_affinity.parse_cpu_list("4-7") == {4, 5, 6, 7}
    assert cpu_affinity.parse_cpu_list("4,5,6,7") == {4, 5, 6, 7}
    assert cpu_affinity.parse_cpu_list(" 4  5 ") == {4, 5}
    assert cpu_affinity.parse_cpu_list("7") == {7}
    assert cpu_affinity.parse_cpu_list("") is None
    assert cpu_affinity.parse_cpu_list("x-y") is None
    assert cpu_affinity.parse_cpu_list("4,") is None or cpu_affinity.parse_cpu_list("4,") == {4}


def test_affinity_enabled_default_and_off(monkeypatch):
    assert cpu_affinity.affinity_enabled() is True
    for off in ("0", "false", "no", "off"):
        monkeypatch.setenv("DRIVE_WEBRTC_AFFINITY", off)
        assert cpu_affinity.affinity_enabled() is False
    monkeypatch.setenv("DRIVE_WEBRTC_AFFINITY", "1")
    assert cpu_affinity.affinity_enabled() is True


def test_pin_vehicle_thread_enabled(monkeypatch):
    assert cpu_affinity.pin_vehicle_thread_enabled() is False
    monkeypatch.setenv("DRIVE_WEBRTC_AFFINITY_PIN_VEHICLE", "1")
    assert cpu_affinity.pin_vehicle_thread_enabled() is True
    monkeypatch.setenv("DRIVE_WEBRTC_AFFINITY_PIN_VEHICLE", "0")
    assert cpu_affinity.pin_vehicle_thread_enabled() is False


def test_media_cpu_set_explicit_override(monkeypatch):
    allowed = os.sched_getaffinity(0)
    pick = sorted(allowed)[:2]
    monkeypatch.setenv("DRIVE_WEBRTC_MEDIA_CPUS", f"{pick[0]},{pick[1]}")
    assert cpu_affinity.media_cpu_set() == frozenset(pick)


def test_media_cpu_set_explicit_range(monkeypatch):
    allowed = sorted(os.sched_getaffinity(0))
    if len(allowed) < 4:
        pytest.skip("可用核不足 4 个")
    lo = allowed[0]
    monkeypatch.setenv("DRIVE_WEBRTC_MEDIA_CPUS", f"{lo}-{lo+3}")
    assert cpu_affinity.media_cpu_set() == frozenset(range(lo, lo + 4))


def test_media_cpu_set_invalid_override_falls_back_to_topology(monkeypatch):
    monkeypatch.setenv("DRIVE_WEBRTC_MEDIA_CPUS", "9998-9999")
    # 无交集 → 回退按算力选核（不抛异常、非空、是当前进程可用核子集）
    picked = cpu_affinity.media_cpu_set()
    assert picked
    assert picked <= os.sched_getaffinity(0)


def test_media_cpu_set_takes_high_capacity_half(monkeypatch):
    def fake_capacity(cpu):
        return {0: 381, 1: 381, 2: 381, 3: 381, 4: 889, 5: 889, 6: 889, 7: 1024}.get(cpu, 0)

    fake_online = [0, 1, 2, 3, 4, 5, 6, 7]
    monkeypatch.setattr(cpu_affinity, "_cpu_capacity", fake_capacity)
    monkeypatch.setattr(cpu_affinity, "_online_cpus", lambda: fake_online)
    # 容量排序（稳定性）：7(1024) 6/5/4(889) 在前，取一半 = 前 4 个
    assert cpu_affinity.media_cpu_set() == frozenset({7, 6, 5, 4})
    assert cpu_affinity.vehicle_cpu_set() == frozenset({0, 1, 2, 3})


def test_media_cpu_set_size_floor(monkeypatch):
    monkeypatch.setattr(cpu_affinity, "_online_cpus", lambda: [0, 1])
    monkeypatch.setattr(cpu_affinity, "_cpu_capacity", lambda cpu: 1.0)
    # 2 核的一半取整为 1，但 max(1, ...) 保底
    picked = cpu_affinity.media_cpu_set()
    assert len(picked) >= 1


def test_pin_current_thread_roundtrip():
    original = os.sched_getaffinity(0)
    try:
        target = {min(original)}
        assert cpu_affinity.pin_current_thread(target) is True
        assert os.sched_getaffinity(0) == target
        assert cpu_affinity.pin_current_thread(set()) is False
    finally:
        os.sched_setaffinity(0, original)


def test_pin_current_thread_ignores_unusable_cpus():
    original = os.sched_getaffinity(0)
    try:
        # 不可用核被过滤到交集；若与当前掩码完全无交集则失败返回 False
        assert cpu_affinity.pin_current_thread({99998, 99999}) is False
        assert os.sched_getaffinity(0) == original
    finally:
        os.sched_setaffinity(0, original)


def test_run_threaded_pins_vehicle_thread_when_enabled(monkeypatch):
    from donkeycar.parts.drive_api_bridge import DriveApiBridge

    # 本文件只测亲和性：禁用编码器调优安装，避免污染全局
    # aiortc.rtcrtpsender.get_encoder（test_webrtc_encoder 依赖其原始状态）
    monkeypatch.setenv("DRIVE_WEBRTC_ENCODER_TUNE", "0")
    monkeypatch.setenv("DRIVE_WEBRTC_AFFINITY_PIN_VEHICLE", "1")
    original = os.sched_getaffinity(0)
    bridge = DriveApiBridge(auto_start=False)
    try:
        result = bridge.run_threaded(img_arr=None)
        # Part 返回签名不变；车辆线程已被钉到媒体核之外的核
        assert isinstance(result, tuple)
        assert os.sched_getaffinity(0) == (original & cpu_affinity.vehicle_cpu_set())
        # 只尝试一次：后续调用不再改亲和性（_vehicle_pin_attempted 守卫）
        monkeypatch.setenv("DRIVE_WEBRTC_AFFINITY_PIN_VEHICLE", "0")
        bridge.run_threaded(img_arr=None)
        assert os.sched_getaffinity(0) == (original & cpu_affinity.vehicle_cpu_set())
    finally:
        os.sched_setaffinity(0, original)
        bridge.shutdown()


def test_run_threaded_does_not_pin_vehicle_thread_by_default(monkeypatch):
    from donkeycar.parts.drive_api_bridge import DriveApiBridge

    monkeypatch.setenv("DRIVE_WEBRTC_ENCODER_TUNE", "0")
    original = os.sched_getaffinity(0)
    bridge = DriveApiBridge(auto_start=False)
    try:
        bridge.run_threaded(img_arr=None)
        assert os.sched_getaffinity(0) == original
    finally:
        bridge.shutdown()
