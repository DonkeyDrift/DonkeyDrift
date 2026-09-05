# -*- coding: utf-8 -*-
"""throttle_analysis 单元测试（M2 验收：频率↔半径相关性在数据上可验证）。

合成已知负相关序列（频率高→半径小），验证相关系数、单调性判定与
参数分档表。
"""
import math
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from throttle_analysis import AnalysisRow, correlate, parameter_table


def make_rows(n=240, rate=20.0):
    """20Hz 采样 12 秒：频率每 3s 阶梯切换 [3,5,8,4]Hz，半径 = 1.2 − 0.09·freq。"""
    freqs = [3.0, 5.0, 8.0, 4.0]
    rows = []
    for i in range(n):
        t = i / rate
        seg = min(int(t / 3.0), 3)
        f = freqs[seg]
        radius = 1.2 - 0.09 * f
        rows.append(AnalysisRow(t_s=t, pulse_freq_hz=f, duty=0.4 + 0.02 * f,
                                peak_amp=0.8, radius_m=radius, beta_deg=15 + 2 * f))
    return rows


class TestCorrelation:
    def test_negative_correlation_detected(self):
        rows = make_rows()
        result = correlate(rows)
        assert result.pearson_r < -0.8, "已知强负相关应被检出"
        assert result.monotonic_decreasing is True

    def test_flat_series_reports_no_relation(self):
        rows = [AnalysisRow(t_s=i * 0.05, pulse_freq_hz=5.0, duty=0.5,
                            peak_amp=0.8, radius_m=0.8, beta_deg=25.0)
                for i in range(100)]
        result = correlate(rows)
        assert result.monotonic_decreasing is False
        assert abs(result.pearson_r) < 0.3


class TestParameterTable:
    def test_bins_by_frequency(self):
        rows = make_rows()
        table = parameter_table(rows)
        # 三档（低<4.5 / 中4.5~6.5 / 高>6.5）：低档平均半径应大于高档
        assert table["low"].mean_radius_m > table["high"].mean_radius_m
        assert table["low"].mean_freq_hz < table["high"].mean_freq_hz
        assert table["low"].n_samples > 0
        assert table["high"].n_samples > 0

    def test_table_contains_controller_seed_parameters(self):
        table = parameter_table(make_rows())
        for key in ("low", "mid", "high"):
            bin_ = table[key]
            assert 0.0 <= bin_.mean_duty <= 1.0
            assert 0.0 <= bin_.mean_amp <= 1.0
            assert bin_.mean_beta_deg != 0.0
