# -*- coding: utf-8 -*-
"""scripts/safety_acceptance.py 判定规则单元测试（P1，2026-10-12）。

覆盖纯判定逻辑（不碰 I/O / 网络）：
- decide_radius_sign：半径环符号三值判定与边界
- simulate_engage 系列：现行「零次跌破」语义（跌破清计时、缺口清计时、
  保持 500ms 接管）与两种备选判据的对照
- evaluate_beta_noise：pass / no_data / criterion_mismatch 三条判定路径
- noise_floor / verdict_from_results / CSV 读取
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.safety_acceptance import (  # noqa: E402
    BetaSample,
    decide_radius_sign,
    evaluate_beta_noise,
    load_beta_samples_from_csv,
    noise_floor,
    simulate_engage,
    simulate_engage_over_ratio,
    simulate_engage_window_mean,
    verdict_from_results,
)


def _series(values, dt=0.1, t0=0.0):
    return [BetaSample(t_s=t0 + i * dt, beta_deg=v)
            for i, v in enumerate(values)]


class TestDecideRadiusSign:
    def test_clear_negative_keeps_default(self):
        d = decide_radius_sign(-0.85)
        assert d.decision == "keep_-1"
        assert d.radius_freq_sign == -1.0
        assert d.config_payload is None

    def test_clear_positive_flips_sign(self):
        d = decide_radius_sign(0.85)
        assert d.decision == "set_+1"
        assert d.radius_freq_sign == 1.0
        assert d.config_payload == {"radius_freq_sign": 1.0}

    def test_ambiguous_stops(self):
        for r in (0.0, -0.59, 0.59, 0.3):
            d = decide_radius_sign(r)
            assert d.decision == "stop"
            assert d.radius_freq_sign is None
            assert d.config_payload is None
            assert "勿带病整定" in d.reason

    def test_threshold_boundary_inclusive(self):
        assert decide_radius_sign(-0.6).decision == "keep_-1"
        assert decide_radius_sign(0.6).decision == "set_+1"


class TestSimulateEngage:
    def test_clean_step_engages_at_hold(self):
        samples = _series([20.0] * 15)  # 1.5s 持续超阈
        r = simulate_engage(samples, 15.0, 0.5, 0.2)
        assert r.engaged is True
        assert abs(r.latency_s - 0.5) < 1e-6
        assert r.resets == 0

    def test_dip_resets_hold_timer(self):
        # 4 拍超阈 + 1 拍回落（0.5s 循环）：最长连续 0.4s < 0.5s，不接管
        samples = _series([25.0, 25.0, 25.0, 25.0, 5.0] * 5)
        r = simulate_engage(samples, 15.0, 0.5, 0.2)
        assert r.engaged is False
        assert r.resets == 5

    def test_gap_resets_hold_timer(self):
        samples = [BetaSample(0.0, 20.0), BetaSample(0.1, 20.0),
                   BetaSample(0.6, 20.0), BetaSample(0.7, 20.0),
                   BetaSample(0.8, 20.0), BetaSample(0.9, 20.0),
                   BetaSample(1.0, 20.0), BetaSample(1.1, 20.0),
                   BetaSample(1.2, 20.0)]
        r = simulate_engage(samples, 15.0, 0.5, 0.2)
        assert r.engaged is True
        assert r.resets == 1  # 0.5s 缺口清计时一次
        assert abs(r.latency_s - 1.1) < 1e-6  # 从首超阈 0.0 起算

    def test_latency_measured_from_first_crossing(self):
        # 起步超阈在 t=0.3 被打断，t=0.4 重新起算并于 t=0.9 接管：
        # latency 相对序列首个超阈样本（t=0）为 0.9s
        samples = _series([20.0, 20.0, 20.0, 5.0] + [20.0] * 10)
        r = simulate_engage(samples, 15.0, 0.5, 0.2)
        assert r.engaged is True
        assert abs(r.latency_s - 0.9) < 1e-6


class TestAlternativeRules:
    def test_window_mean_engages_where_zero_dip_fails(self):
        samples = _series([25.0, 25.0, 25.0, 25.0, 5.0] * 5)
        zero = simulate_engage(samples, 15.0, 0.5, 0.2)
        mean = simulate_engage_window_mean(samples, 15.0, 0.5, 0.5, 0.2)
        assert zero.engaged is False
        assert mean.engaged is True

    def test_over_ratio_engages_with_brief_dips(self):
        # ratio=0.6：滑窗内 4/5 超阈持续满足；零次跌破判据不满足
        samples = _series([25.0, 25.0, 25.0, 25.0, 5.0] * 5)
        zero = simulate_engage(samples, 15.0, 0.5, 0.2)
        ratio = simulate_engage_over_ratio(samples, 15.0, 0.5, 0.5, 0.6, 0.2)
        assert zero.engaged is False
        assert ratio.engaged is True


class TestNoiseFloor:
    def test_stats(self):
        samples = _series([2.0, 4.0, 6.0, 8.0])
        f = noise_floor(samples)
        assert f.n == 4
        assert abs(f.mean_deg - 5.0) < 1e-6
        assert abs(f.p2p_deg - 6.0) < 1e-6
        assert f.min_deg == 2.0 and f.max_deg == 8.0

    def test_empty(self):
        f = noise_floor([])
        assert f.n == 0 and f.p2p_deg == 0.0


class TestEvaluateBetaNoise:
    def test_pass_when_current_rule_engages_fast(self):
        samples = _series([20.0] * 30)  # 3s 干净超阈
        v = evaluate_beta_noise(samples)
        assert v.verdict == "pass"
        assert "现行" in v.advice

    def test_no_data_without_sustained_over(self):
        samples = _series([2.0, 4.0, 2.0, 4.0] * 15)  # 纯低速噪声
        v = evaluate_beta_noise(samples)
        assert v.verdict == "no_data"
        assert v.has_sustained_over is False
        assert "噪声水位" in v.advice

    def test_mismatch_recommends_window_mean(self):
        # 4 拍超阈 + 1 拍回落 4s：零次跌破永不接管，滑窗均值接管
        samples = _series([25.0, 25.0, 25.0, 25.0, 5.0] * 8)
        v = evaluate_beta_noise(samples)
        assert v.verdict == "criterion_mismatch"
        assert v.current.engaged is False
        assert v.has_sustained_over is True
        assert v.window_mean.engaged is True
        assert "window_mean" in v.advice
        assert "勿现场改代码" in v.advice


class TestVerdictAndCsv:
    def test_all_pass(self):
        results = [{"id": f"R{i}", "result": "pass"} for i in range(1, 9)]
        verdict, msg = verdict_from_results(results)
        assert verdict == "pass"
        assert "✅" in msg

    def test_any_fail_wins(self):
        results = [{"id": f"R{i}", "result": "pass"} for i in range(1, 9)]
        results[2] = {"id": "R3", "result": "fail"}
        verdict, msg = verdict_from_results(results)
        assert verdict == "fail"
        assert "勿现场改代码" in msg

    def test_skip_makes_incomplete(self):
        results = [{"id": f"R{i}", "result": "pass"} for i in range(1, 9)]
        results[7] = {"id": "R8", "result": "skip"}
        assert verdict_from_results(results)[0] == "incomplete"

    def test_csv_roundtrip(self, tmp_path):
        p = tmp_path / "beta.csv"
        p.write_text("t_s,beta_deg\n0.0,20.5\n0.1,-21.5\n", encoding="utf-8")
        samples = load_beta_samples_from_csv(str(p))
        assert [s.t_s for s in samples] == [0.0, 0.1]
        assert samples[1].beta_deg == -21.5
