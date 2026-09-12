# -*- coding: utf-8 -*-
"""点动机理离线分析 CLI（M2 验收工具）。

用法：
    python scripts/analyze_throttle_pulses.py <tub路径> [--center 1.0,1.0]

输出：频率↔半径相关系数与单调性判定（不成立则提示停下修模型）、
按频率三档的参数表（控制器外环整定初值）。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web_ui" / "backend"))

from throttle_analysis import correlate, parameter_table, rows_from_tub


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # GBK 控制台防 ✅/❌ UnicodeEncodeError
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="点动油门机理分析（M2）")
    parser.add_argument("tub", help="SyncRecorder 录制的 tub 目录")
    parser.add_argument("--center", default="1.0,1.0", help="定圆 圆心 x,y（米）")
    args = parser.parse_args()

    try:
        cx, cy = (float(v) for v in args.center.split(","))
    except ValueError:
        parser.error(f"--center 格式错误：{args.center!r}，应为 \"x,y\"（如 1.0,1.0）")

    tub_dir = Path(args.tub)
    if not tub_dir.is_dir():
        print(f"错误：tub 目录不存在：{tub_dir}")
        return 1

    rows = rows_from_tub(str(tub_dir), center=(cx, cy))
    if len(rows) < 60:
        print(f"样本过少（{len(rows)} 行，需 ≥60）：请至少录制 1 分钟漂移")
        return 1

    corr = correlate(rows)
    print(f"样本 {len(rows)} 行")
    print(f"频率↔半径 Pearson r = {corr.pearson_r:.3f}")
    if corr.monotonic_decreasing:
        print("✅ 机理成立：点动频率高 → 轨迹半径小（负相关被数据支持）")
    else:
        print("❌ 机理未获数据支持：按 RFC 停下修正机理模型，勿带病整定控制器")
        print("   （检查：圆心参数是否正确 / 滑动窗特征是否退化 / 录制是否含漂移段）")

    table = parameter_table(rows)
    print("\n分档参数表（控制器外环整定初值）：")
    header = f"{'档位':<5}{'样本':<7}{'均频Hz':<9}{'均半径m':<9}{'均β°':<8}{'均占空比':<9}{'均幅值':<7}"
    print(header)
    for key in ("low", "mid", "high"):
        b = table[key]
        print(f"{b.label:<5}{b.n_samples:<7}{b.mean_freq_hz:<9.2f}{b.mean_radius_m:<9.2f}"
              f"{b.mean_beta_deg:<8.1f}{b.mean_duty:<9.2f}{b.mean_amp:<7.2f}")

    out_json = Path(args.tub) / "pulse_analysis.json"
    out_json.write_text(json.dumps({
        "pearson_r": corr.pearson_r,
        "monotonic_decreasing": corr.monotonic_decreasing,
        "table": {k: vars(v) for k, v in table.items()},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写入 {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
