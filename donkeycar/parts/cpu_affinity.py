#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WebRTC 媒体线程 CPU 亲和性（P1a：降时延、提帧率）。

2026-10-08 本机（高通 8 核 big.LITTLE：cpu0-3 小核 cap=381，cpu4-6 大核
cap=889，cpu7 主核 cap=1024）回环探针 A/B 实测：

- 不绑核（P0 状态）：fps 58.1、e2e p50 45.2ms / p95 61.7ms、帧间隔
  p95 26.7ms；
- 仅媒体线程绑大核半区：fps 60.1、p50 32.9ms / p95 43.0ms、帧间隔
  p95 21.4ms（全部达标）；
- 再加车辆线程绑小核半区：p50 30.6ms / p95 38.8ms（额外 ~3ms，可选）。

劣化主因不是 GIL，而是调度器把 numpy 车辆循环、aiortc 事件循环、
编码线程池在核间来回迁移（含跨大小核簇迁移），缓存/预取全部失效。
把媒体侧（bridge 线程 + 其编码线程池）钉在按算力选出的高容量核上
即可恢复；默认不动车辆线程（实车推理需要全核自由度）。

配置（env，模板/构造均可）：

- ``DRIVE_WEBRTC_AFFINITY``：默认 ``1``；``0`` 完全关闭
- ``DRIVE_WEBRTC_MEDIA_CPUS``：显式指定媒体核，如 ``4-7`` / ``4,5,6,7``；
  默认按 /sys cpu_capacity 取容量最高的前一半核
- ``DRIVE_WEBRTC_AFFINITY_PIN_VEHICLE``：默认 ``0``；``1`` 时把车辆
  车辆线程（run_threaded 调用方）钉在其余核上再挤 ~3ms

非 Linux / 无 sched_setaffinity 环境自动退化为无操作。
"""
import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)

_HAS_SCHED = hasattr(os, "sched_setaffinity")
_SYS_CPU = "/sys/devices/system/cpu"


def affinity_enabled() -> bool:
    if not _HAS_SCHED:  # 非 Linux（Windows/macOS 开发机）
        return False
    return os.environ.get("DRIVE_WEBRTC_AFFINITY", "").strip().lower() not in (
        "0", "false", "no", "off",
    )


def parse_cpu_list(value: str):
    """解析 ``"4-7"`` / ``"4,5,6"`` / ``"4 5"`` 形式的 CPU 列表；非法返回 None。"""
    cpus = set()
    for token in str(value).replace(",", " ").split():
        try:
            if "-" in token:
                lo, hi = token.split("-", 1)
                cpus.update(range(int(lo), int(hi) + 1))
            else:
                cpus.add(int(token))
        except ValueError:
            return None
    return cpus or None


def _cpu_capacity(cpu: int):
    """单核算力（越大越强）；sysfs 缺项时逐级回退，全缺返回 None。"""
    for path in (
        f"{_SYS_CPU}/cpu{cpu}/cpu_capacity",
        f"{_SYS_CPU}/cpu{cpu}/cpufreq/cpuinfo_max_freq",
    ):
        try:
            with open(path) as f:
                return float(f.read().strip())
        except (OSError, ValueError):
            continue
    return None


def _online_cpus():
    try:
        with open(f"{_SYS_CPU}/online") as f:
            return sorted(parse_cpu_list(f.read().strip()))
    except OSError:
        return sorted(os.sched_getaffinity(0)) if _HAS_SCHED else list(range(os.cpu_count() or 1))


@lru_cache(maxsize=1)
def media_cpu_set():
    """媒体线程目标核：env 显式指定 > 按算力取最高的前一半核。"""
    if not _HAS_SCHED:
        return frozenset()
    explicit = parse_cpu_list(os.environ.get("DRIVE_WEBRTC_MEDIA_CPUS", ""))
    if explicit:
        allowed = os.sched_getaffinity(0)
        usable = frozenset(c for c in explicit if c in allowed)
        if usable:
            return usable
        logger.warning("DRIVE_WEBRTC_MEDIA_CPUS=%r 与进程可用核 %r 无交集，忽略",
                       os.environ["DRIVE_WEBRTC_MEDIA_CPUS"], sorted(allowed))

    online = _online_cpus()
    capacities = [(c, _cpu_capacity(c) or 0.0) for c in online]
    ordered = [c for c, _ in sorted(capacities, key=lambda item: -item[1])]
    take = max(1, len(ordered) // 2)
    return frozenset(ordered[:take])


def vehicle_cpu_set():
    """车辆线程目标核：媒体核之外的在线核（PIN_VEHICLE 开启时使用）。"""
    if not _HAS_SCHED:
        return frozenset()
    return frozenset(_online_cpus()) - media_cpu_set()


def pin_current_thread(cpus) -> bool:
    """把调用线程钉到 cpus；成功 True。pid=0 在 Linux 语义上是调用线程。"""
    if not _HAS_SCHED or not cpus:
        return False
    try:
        allowed = os.sched_getaffinity(0)
        usable = frozenset(cpus) & allowed
        if not usable:
            return False
        os.sched_setaffinity(0, usable)
        return True
    except OSError as exc:  # 容器/cgroup 限制等：降级为无操作
        logger.debug("设置 CPU 亲和性失败（忽略）: %s", exc)
        return False


def pin_vehicle_thread_enabled() -> bool:
    return _HAS_SCHED and os.environ.get(
        "DRIVE_WEBRTC_AFFINITY_PIN_VEHICLE", "").strip().lower() in ("1", "true", "yes", "on")
