# -*- coding: utf-8 -*-
"""实车安全联锁验收清单 + 判定规则 CLI（P1，2026-10-12）。

依据 docs/plan/overhead-drift-safety-acceptance.md（runbook），把验收中
两条"判定规则"做成可执行分析，把安全联锁核对清单做成可记录的清单：

1. radius-sign：半径环符号实证（M2 点动机理验证后执行）
   读录制 tub 的「点动频率 ↔ 轨迹半径」相关性，三值判定：
   - r ≤ -0.6：机理「频率高→半径小」成立 → radius_freq_sign 保持 -1
   - r ≥ +0.6：机理反转「频率高→半径大」→ radius_freq_sign 置 +1
     （打印 POST /api/drift/config 载荷，热改生效）
   - 其余：证据不足 → 停下修正机理模型，勿带病整定控制器

2. beta-noise：低速 β 噪声 vs 接管判据（M4 低速闭环后执行）
   读低速段 β 时间序列（tub 或 CSV），在同一批数据上回放三种接管判据：
   - zero_dip（现行）：|β|≥阈值持续 hold 且零次跌破（drift_session.py
     update_auto_observation 语义，缺口清计时）
   - window_mean（备选）：滑窗均值 |β|≥阈值持续 hold
   - over_ratio（备选）：滑窗内 |β|≥阈值的样本占比 ≥ ratio 持续 hold
   输出噪声水位、各判据接管延迟/重置次数与最终判定（现行判据可行 /
   判据不适配建议备选 / 数据无持续超阈段），带回评估，勿现场改代码。

3. checklist：安全联锁核对清单（runbook R1~R8，交互或 --answers 驱动）
   可选 --server 拉 GET /api/drift/state 取证（events/watchdog、
   send_failures、camera_loop_errors），产出 JSON 验收记录与终判。

退出码：0=通过/判定成立；1=存在失败项或判据不适配/停下；2=用法或数据错误。
"""
import argparse
import csv
import json
import statistics
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "web_ui" / "backend"))

# 判定阈值（与 throttle_analysis.correlate / drift_session.py 对齐）
RADIUS_SIGN_R_THRESHOLD = 0.6   # |r| 超过它才算方向明确
ENGAGE_BETA_DEG = 15.0          # drift_session.DEFAULT_ENGAGE_BETA_DEG
ENGAGE_HOLD_S = 0.5             # drift_session.DEFAULT_ENGAGE_STABLE_S
ENGAGE_MAX_GAP_S = 0.2          # 采样缺口超此值清计时（镜像 note_detection_gap）


# ─────────────────────────── 数据输入 ───────────────────────────
@dataclass
class BetaSample:
    t_s: float
    beta_deg: float


def load_beta_samples_from_tub(tub_path: str) -> List[BetaSample]:
    """从 SyncRecorder 的 tub 读 β 时间序列（毫秒时间戳转秒）。"""
    from donkeycar.parts.tub_v2 import Tub
    tub = Tub(base_path=tub_path)
    return [BetaSample(t_s=float(r.get("_timestamp_ms", 0.0)) / 1000.0,
                       beta_deg=float(r["state/beta"])) for r in tub]


def load_beta_samples_from_csv(csv_path: str) -> List[BetaSample]:
    """读 t_s,beta_deg 两列 CSV（带表头）。"""
    out: List[BetaSample] = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(BetaSample(t_s=float(row["t_s"]),
                                  beta_deg=float(row["beta_deg"])))
    return out


# ─────────────────────── D1 半径环符号判定 ───────────────────────
@dataclass
class RadiusSignDecision:
    decision: str                 # keep_-1 | set_+1 | stop
    pearson_r: float
    radius_freq_sign: Optional[float]
    reason: str
    config_payload: Optional[dict]


def decide_radius_sign(pearson_r: float,
                       r_threshold: float = RADIUS_SIGN_R_THRESHOLD
                       ) -> RadiusSignDecision:
    if pearson_r <= -r_threshold:
        return RadiusSignDecision(
            decision="keep_-1", pearson_r=pearson_r, radius_freq_sign=-1.0,
            reason="机理成立（频率高→半径小），radius_freq_sign 保持默认 -1",
            config_payload=None)
    if pearson_r >= r_threshold:
        return RadiusSignDecision(
            decision="set_+1", pearson_r=pearson_r, radius_freq_sign=1.0,
            reason="机理反转（频率高→半径大），radius_freq_sign 置 +1 负反馈",
            config_payload={"radius_freq_sign": 1.0})
    return RadiusSignDecision(
        decision="stop", pearson_r=pearson_r, radius_freq_sign=None,
        reason="相关性方向不明确（|r| < %.2f）：按下修 RFC 停下修正机理"
               "模型，勿带病整定控制器" % r_threshold,
        config_payload=None)


# ─────────────────────── D2 接管判据回放 ───────────────────────
@dataclass
class RuleResult:
    rule: str
    engaged: bool
    engage_t_s: Optional[float]
    latency_s: Optional[float]   # 相对序列首个超阈样本
    resets: int                  # 超阈计时被跌破/缺口清零次数


def _hold_engage(series: Sequence[Tuple[float, float]], threshold: float,
                 hold_s: float, max_gap_s: float, rule: str) -> RuleResult:
    """通用保持计时：value ≥ threshold 持续 hold_s（零次跌破）才接管。

    任一样本跌破阈值或采样缺口 > max_gap_s 都清计时（镜像
    drift_session.update_auto_observation / note_detection_gap 语义）。
    """
    over_since: Optional[float] = None
    first_over_t: Optional[float] = None
    engage_t: Optional[float] = None
    resets = 0
    prev_t: Optional[float] = None
    for t_s, value in series:
        if prev_t is not None and t_s - prev_t > max_gap_s:
            if over_since is not None:
                resets += 1
                over_since = None
        if value >= threshold:
            if first_over_t is None:
                first_over_t = t_s
            if over_since is None:
                over_since = t_s
            elif engage_t is None and t_s - over_since >= hold_s:
                engage_t = t_s
        else:
            if over_since is not None:
                resets += 1
            over_since = None
        prev_t = t_s
        if engage_t is not None:
            break
    latency = (engage_t - first_over_t
               if engage_t is not None and first_over_t is not None else None)
    return RuleResult(rule=rule, engaged=engage_t is not None,
                      engage_t_s=engage_t, latency_s=latency, resets=resets)


def _trailing(series: Sequence[Tuple[float, float]], window_s: float,
              reduce) -> List[Tuple[float, float]]:
    """对序列做 window_s 滑窗归约，输出与输入等长的派生序列。"""
    out: List[Tuple[float, float]] = []
    lo = 0
    for i, (t_s, _) in enumerate(series):
        while series[lo][0] < t_s - window_s:
            lo += 1
        window = [v for _, v in series[lo:i + 1]]
        out.append((t_s, reduce(window)))
    return out


def simulate_engage(samples: Sequence[BetaSample], threshold_deg: float,
                    hold_s: float, max_gap_s: float) -> RuleResult:
    """现行判据：|β|≥阈值持续 hold_s 且零次跌破。"""
    series = [(s.t_s, abs(s.beta_deg)) for s in samples]
    return _hold_engage(series, threshold_deg, hold_s, max_gap_s, "zero_dip")


def simulate_engage_window_mean(samples: Sequence[BetaSample],
                                threshold_deg: float, hold_s: float,
                                window_s: float, max_gap_s: float
                                ) -> RuleResult:
    """备选判据：滑窗均值 |β|≥阈值持续 hold_s。"""
    series = [(s.t_s, abs(s.beta_deg)) for s in samples]
    derived = _trailing(series, window_s,
                        lambda w: sum(w) / len(w))
    return _hold_engage(derived, threshold_deg, hold_s, max_gap_s,
                        "window_mean")


def simulate_engage_over_ratio(samples: Sequence[BetaSample],
                               threshold_deg: float, hold_s: float,
                               window_s: float, ratio: float,
                               max_gap_s: float) -> RuleResult:
    """备选判据：滑窗内 |β|≥阈值样本占比 ≥ ratio 持续 hold_s。"""
    series = [(s.t_s, abs(s.beta_deg)) for s in samples]
    derived = _trailing(series, window_s,
                        lambda w: sum(1 for v in w if v >= threshold_deg)
                        / len(w))
    return _hold_engage(derived, ratio, hold_s, max_gap_s, "over_ratio")


@dataclass
class NoiseFloor:
    n: int
    mean_deg: float
    std_deg: float
    p2p_deg: float
    min_deg: float
    max_deg: float


def noise_floor(samples: Sequence[BetaSample]) -> NoiseFloor:
    vals = [abs(s.beta_deg) for s in samples]
    if not vals:
        return NoiseFloor(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return NoiseFloor(
        n=len(vals), mean_deg=statistics.fmean(vals),
        std_deg=statistics.stdev(vals) if len(vals) > 1 else 0.0,
        p2p_deg=max(vals) - min(vals),
        min_deg=min(vals), max_deg=max(vals))


@dataclass
class BetaNoiseVerdict:
    floor: NoiseFloor
    current: RuleResult
    window_mean: RuleResult
    over_ratio: RuleResult
    has_sustained_over: bool
    verdict: str    # pass | criterion_mismatch | no_data
    advice: str


def evaluate_beta_noise(samples: Sequence[BetaSample],
                        threshold_deg: float = ENGAGE_BETA_DEG,
                        hold_s: float = ENGAGE_HOLD_S,
                        window_s: float = 0.5,
                        over_ratio: float = 0.8,
                        max_gap_s: float = ENGAGE_MAX_GAP_S,
                        sustained_s: float = 2.0) -> BetaNoiseVerdict:
    floor = noise_floor(samples)
    cur = simulate_engage(samples, threshold_deg, hold_s, max_gap_s)
    wm = simulate_engage_window_mean(samples, threshold_deg, hold_s,
                                     window_s, max_gap_s)
    orr = simulate_engage_over_ratio(samples, threshold_deg, hold_s,
                                     window_s, over_ratio, max_gap_s)
    # "真实超阈段"存在性：滑窗均值连续 ≥ sustained_s 高于阈值
    mean_series = _trailing([(s.t_s, abs(s.beta_deg)) for s in samples],
                            1.0, lambda w: sum(w) / len(w))
    run_start: Optional[float] = None
    has_sustained = False
    for t_s, v in mean_series:
        if v >= threshold_deg:
            if run_start is None:
                run_start = t_s
            elif t_s - run_start >= sustained_s:
                has_sustained = True
                break
        else:
            run_start = None

    if cur.engaged and (cur.latency_s or 0.0) <= 1.0:
        verdict = "pass"
        advice = ("现行 500ms 零次跌破判据可行（接管延迟 %.2fs），"
                  "保持 drift_session.DEFAULT_ENGAGE_* 不动" % cur.latency_s)
    elif not has_sustained:
        verdict = "no_data"
        advice = ("数据不含持续超阈段（滑窗均值未见 ≥%.0fs 超阈），"
                  "仅记录噪声水位；补一段真实超阈数据（低速起漂）再评"
                  "接管判据" % sustained_s)
    else:
        candidates = [r for r in (wm, orr)
                      if r.engaged and (r.latency_s or 9e9) < 2.0]
        verdict = "criterion_mismatch"
        if candidates:
            best = min(candidates, key=lambda r: r.latency_s or 9e9)
            advice = ("现行判据不适配（%s），建议改 %s（同数据接管延迟 "
                      "%.2fs）——带回评估列入判据修订，勿现场改代码"
                      % ("未接管" if not cur.engaged
                         else "接管延迟 %.2fs" % cur.latency_s,
                         best.rule, best.latency_s))
        else:
            advice = ("持续超阈段存在但三种判据均未可靠接管：检查 β 估计"
                      "链路（0.2s 割线基线）与采样时基，带回分析，"
                      "勿现场改代码")
    return BetaNoiseVerdict(floor=floor, current=cur, window_mean=wm,
                            over_ratio=orr, has_sustained_over=has_sustained,
                            verdict=verdict, advice=advice)


# ─────────────────────── R1~R8 安全联锁清单 ───────────────────────
CHECKLIST_ITEMS = [
    {"id": "R1", "title": "看门狗-检测丢失",
     "op": "ENGAGED 中遮住镜头 >0.2s",
     "expect": "car_mode→0 + 零油门；events 出现 kind=watchdog、"
               "reason=检测丢失超时（仅 ENGAGED 触发）"},
    {"id": "R2", "title": "看门狗-遥测停滞",
     "op": "ENGAGED 中断开车端连接（SBC 断网/杀 manage.py）>0.5s",
     "expect": "car_mode→0 + 零油门；events reason=遥测停滞超时"
               "（仅 ENGAGED 触发）"},
    {"id": "R3", "title": "看门狗-下发失败",
     "op": "ws 异常期间观察 send_failures 计数",
     "expect": "≥3 次触发 reason=控制下发连续失败（通常与 R2 同源，"
               "不强求单独隔离）"},
    {"id": "R4", "title": "非 AUTO 不动车",
     "op": "IDLE/观察期遮镜头、断遥测",
     "expect": "只记事件、绝不动车（观察期车在人手里）"},
    {"id": "R5", "title": "MODE 0→2 跳变平滑",
     "op": "接管/退出瞬间肉眼观察",
     "expect": "平滑无抽搐/窜动；异常记录现象（贯穿低速闭环与定圆阶段）"},
    {"id": "R6", "title": "多 client 仲裁",
     "op": "AUTO 期间开第二个浏览器标签尝试键盘控车",
     "expect": "控制被服务端丢弃、回发 control_rejected、车不受干扰"
               "（含同标签页）"},
    {"id": "R7", "title": "RC 夺回（MODE 0）",
     "op": "任意 AUTO 状态拨 RC MODE 0",
     "expect": "立即人工接管——第一兜底，全程有效"},
    {"id": "R8", "title": "M5 定圆保持",
     "op": "β*≈25° 起漂后定圆保持 30s",
     "expect": "β 均值误差 < 5°，半径波动可接受（真实漂移段是看门狗/"
               "护栏的最终考场）"},
]

RESULTS = ("pass", "fail", "skip")


def verdict_from_results(results: Sequence[dict]) -> Tuple[str, str]:
    """终判：任一 fail → fail；有 skip 无 fail → incomplete；全 pass → pass。"""
    by = {r["id"]: r["result"] for r in results}
    if any(v == "fail" for v in by.values()):
        return "fail", ("❌ 存在失败项，禁止进入下一步；记录现象与数据"
                        "带回分析（勿现场改代码）")
    if any(v == "skip" for v in by.values()):
        return "incomplete", ("⚠️ 有跳过项，验收不完整；补测后重跑清单")
    return "pass", "✅ 安全联锁验收全部通过，可进入下一步（M5/实车漂移）"


def _fetch_state_evidence(server: str, token: str) -> dict:
    url = server.rstrip("/") + "/api/drift/state"
    req = urllib.request.Request(url)
    if token:
        req.add_header("X-Donkey-Token", token)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _print_evidence(state: dict) -> None:
    errs = state.get("camera_loop_errors")
    fails = state.get("send_failures")
    print(f"[取证] camera_loop_errors={errs} send_failures={fails}")
    for ev in (state.get("events") or [])[-20:]:
        print(f"  t={ev.get('t_s')}: kind={ev.get('kind')} "
              f"detail={ev.get('detail')}")


def _ask_result(item_id: str) -> Tuple[str, str]:
    while True:
        raw = input(f"  {item_id} 结果 [p]ass/[f]ail/[s]kip: ").strip().lower()
        mapped = {"p": "pass", "pass": "pass",
                  "f": "fail", "fail": "fail",
                  "s": "skip", "skip": "skip"}.get(raw)
        if mapped:
            note = input("  备注（可空）: ").strip()
            return mapped, note
        print("  请输入 p / f / s")


def run_checklist(answers: Optional[dict], server: str, token: str,
                  out_path: Optional[str]) -> int:
    evidence = None
    if server:
        try:
            evidence = _fetch_state_evidence(server, token)
            _print_evidence(evidence)
        except Exception as exc:  # 取证失败不阻塞人工核对
            print(f"[取证] 拉取 {server}/api/drift/state 失败：{exc}")

    results = []
    interactive = answers is None
    for item in CHECKLIST_ITEMS:
        print(f"\n[{item['id']}] {item['title']}")
        print(f"  操作：{item['op']}")
        print(f"  预期：{item['expect']}")
        if interactive:
            result, note = _ask_result(item["id"])
        else:
            a = answers.get(item["id"], {})
            result = a.get("result", "skip")
            if result not in RESULTS:
                print(f"  错误：{item['id']} 结果非法 {result!r}", file=sys.stderr)
                return 2
            note = a.get("note", "")
        results.append({"id": item["id"], "title": item["title"],
                        "result": result, "note": note})

    verdict, message = verdict_from_results(results)
    record = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": results,
        "verdict": verdict,
        "message": message,
        "evidence": evidence,
    }
    print(f"\n终判：{verdict} — {message}")
    if out_path:
        Path(out_path).write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"验收记录已写入 {out_path}")
    return 0 if verdict == "pass" else 1


# ─────────────────────────── CLI ───────────────────────────
def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # GBK 控制台防 UnicodeEncodeError
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="实车安全联锁验收清单 + 判定规则（P1）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("radius-sign", help="D1 半径环符号实证判定")
    p1.add_argument("tub", help="SyncRecorder 录制的 tub 目录")
    p1.add_argument("--center", default="0.5,0.5",
                    help="定圆圆心 x,y（米，本场地默认 0.5,0.5）")
    p1.add_argument("--r-threshold", type=float, default=RADIUS_SIGN_R_THRESHOLD)

    p2 = sub.add_parser("beta-noise", help="D2 低速 β 噪声 vs 接管判据")
    src = p2.add_mutually_exclusive_group(required=True)
    src.add_argument("--tub", help="SyncRecorder 录制的 tub 目录")
    src.add_argument("--csv", help="t_s,beta_deg 两列 CSV")
    p2.add_argument("--threshold", type=float, default=ENGAGE_BETA_DEG)
    p2.add_argument("--hold-ms", type=float, default=ENGAGE_HOLD_S * 1000)
    p2.add_argument("--window-ms", type=float, default=500.0)
    p2.add_argument("--ratio", type=float, default=0.8)
    p2.add_argument("--max-gap-s", type=float, default=ENGAGE_MAX_GAP_S)

    p3 = sub.add_parser("checklist", help="R1~R8 安全联锁核对清单")
    p3.add_argument("--server", default="", help="后端地址，拉 /api/drift/state 取证")
    p3.add_argument("--token", default="", help="后端访问令牌（X-Donkey-Token）")
    p3.add_argument("--answers", default="",
                    help="非交互模式：JSON 文件 {\"R1\": {\"result\": "
                         "\"pass|fail|skip\", \"note\": \"...\"}, ...}")
    p3.add_argument("--out", default="", help="验收记录 JSON 输出路径")

    args = parser.parse_args()

    if args.cmd == "radius-sign":
        from throttle_analysis import correlate, rows_from_tub
        try:
            cx, cy = (float(v) for v in args.center.split(","))
        except ValueError:
            print(f"错误：--center 格式应为 \"x,y\"，收到 {args.center!r}",
                  file=sys.stderr)
            return 2
        rows = rows_from_tub(args.tub, center=(cx, cy))
        if len(rows) < 60:
            print(f"错误：样本过少（{len(rows)} 行，需 ≥60）", file=sys.stderr)
            return 2
        corr = correlate(rows)
        d = decide_radius_sign(corr.pearson_r, args.r_threshold)
        print(f"样本 {len(rows)} 行，频率↔半径 Pearson r = {d.pearson_r:.3f}")
        print(f"判定：{d.decision} — {d.reason}")
        if d.config_payload is not None:
            print("热改载荷：POST /api/drift/config "
                  f"{json.dumps(d.config_payload, ensure_ascii=False)}")
        return 0 if d.decision != "stop" else 1

    if args.cmd == "beta-noise":
        samples = (load_beta_samples_from_tub(args.tub) if args.tub
                   else load_beta_samples_from_csv(args.csv))
        if len(samples) < 30:
            print(f"错误：样本过少（{len(samples)} 点，需 ≥30）", file=sys.stderr)
            return 2
        v = evaluate_beta_noise(
            samples, threshold_deg=args.threshold,
            hold_s=args.hold_ms / 1000.0, window_s=args.window_ms / 1000.0,
            over_ratio=args.ratio, max_gap_s=args.max_gap_s)
        f = v.floor
        print(f"样本 {f.n} 点：|β| 均值 {f.mean_deg:.1f}° σ {f.std_deg:.1f}° "
              f"峰峰值 {f.p2p_deg:.1f}°（[{f.min_deg:.1f}, {f.max_deg:.1f}]）")
        for r in (v.current, v.window_mean, v.over_ratio):
            lat = ("%.2fs" % r.latency_s) if r.latency_s is not None else "—"
            print(f"  {r.rule:<11} 接管={'是' if r.engaged else '否'} "
                  f"延迟={lat} 重置={r.resets}")
        print(f"判定：{v.verdict} — {v.advice}")
        return 0 if v.verdict == "pass" else 1

    answers = None
    if args.answers:
        answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
    return run_checklist(answers, args.server, args.token,
                         args.out or None)


if __name__ == "__main__":
    sys.exit(main())
