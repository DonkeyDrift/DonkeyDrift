# -*- coding: utf-8 -*-
"""点动油门离线分析（RFC 7.3 / M2 验收）。

从录制 tub 的滑动窗行序列中量化"点动频率 ↔ 轨迹半径"关系：
- correlate：Pearson 相关系数 + 单调性判定（频率高→半径小是否在数据上成立）；
- parameter_table：按频率三档分桶统计（半径/β/占空比/幅值均值），
  作为控制器外环整定的初值参数表。

若 correlate 在真实数据上不呈现负相关 → 按 RFC 停下修正机理模型，
不带病进控制器整定。
"""
import math
import statistics
from dataclasses import dataclass
from typing import List


@dataclass
class AnalysisRow:
    t_s: float
    pulse_freq_hz: float
    duty: float
    peak_amp: float
    radius_m: float
    beta_deg: float


@dataclass
class CorrelationResult:
    pearson_r: float
    monotonic_decreasing: bool


@dataclass
class FreqBin:
    label: str
    n_samples: int
    mean_freq_hz: float
    mean_radius_m: float
    mean_beta_deg: float
    mean_duty: float
    mean_amp: float


def _pearson(xs: List[float], ys: List[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def correlate(rows: List[AnalysisRow]) -> CorrelationResult:
    freqs = [r.pulse_freq_hz for r in rows]
    radii = [r.radius_m for r in rows]
    r_value = _pearson(freqs, radii)
    return CorrelationResult(pearson_r=r_value,
                             monotonic_decreasing=(r_value < -0.6))


def parameter_table(rows: List[AnalysisRow],
                    low_edge: float = 4.5, high_edge: float = 6.5) -> dict:
    def make_bin(label: str, subset: List[AnalysisRow]) -> FreqBin:
        if not subset:
            return FreqBin(label, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
        return FreqBin(
            label=label, n_samples=len(subset),
            mean_freq_hz=statistics.fmean(r.pulse_freq_hz for r in subset),
            mean_radius_m=statistics.fmean(r.radius_m for r in subset),
            mean_beta_deg=statistics.fmean(r.beta_deg for r in subset),
            mean_duty=statistics.fmean(r.duty for r in subset),
            mean_amp=statistics.fmean(r.peak_amp for r in subset),
        )

    low = [r for r in rows if r.pulse_freq_hz < low_edge]
    mid = [r for r in rows if low_edge <= r.pulse_freq_hz <= high_edge]
    high = [r for r in rows if r.pulse_freq_hz > high_edge]
    return {"low": make_bin("low", low), "mid": make_bin("mid", mid),
            "high": make_bin("high", high)}


def rows_from_tub(tub_path: str, center=(1.0, 1.0)) -> List[AnalysisRow]:
    """从 SyncRecorder 的 tub 读取行序列（半径按离圆心距离计算）。"""
    from donkeycar.parts.tub_v2 import Tub
    tub = Tub(base_path=tub_path)
    rows: List[AnalysisRow] = []
    for record in tub:
        dx = record["pose/x"] - center[0]
        dy = record["pose/y"] - center[1]
        rows.append(AnalysisRow(
            t_s=float(record.get("_timestamp_ms", 0.0)) / 1000.0,
            pulse_freq_hz=float(record["state/throttle_pulse_freq"]),
            duty=float(record["state/throttle_duty"]),
            peak_amp=float(record["state/throttle_pulse_amp"]),
            radius_m=math.hypot(dx, dy),
            beta_deg=float(record["state/beta"]),
        ))
    return rows
