#!/usr/bin/env python3
"""D4 协议 smoke test:DonkeyDrift sim × rl/env.py 全链路实测。

用法:
    .venv/bin/python scripts/rl_smoke_test.py                     # 全流程(拉起 sim)
    .venv/bin/python scripts/rl_smoke_test.py --mode remote       # 只连已手动启动的 sim
    .venv/bin/python scripts/rl_smoke_test.py --sim-app <path>    # 指定 sim

必测项(任一 fail/BLOCKER → 退出码 1):
  1 连接 + info 字段齐全性   2 reset_car 耗时 p50/p95(<2s)
  3 边界动作含 brake 不炸连接 4 frame_skip=1 下 n control ↔ n 帧遥测
  5 断连恢复(杀→拉起→看门狗重建→遥测恢复,记录秒数)
  6 帧率实测:有窗 / headless(-nographics)/ headless(keep-gfx) × img_enc(none/jpg)
记录项(非阻断):
  7 同 seed reset 首帧复现性 + spawn 字段支持探针(上报矛盾点的实测证据)

产物:outputs/rl_smoke_result.json(逐项 pass/fail/BLOCKER + 数值)。
纪律:sim 停止只按「自家子进程 pid / lsof 按端口」,全脚本零 pkill。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _sim_proc import launch_sim, resolve_sim_exe, stop_sim, wait_for_port  # noqa: E402
import _sim_proc  # noqa: E402

from donkeydrifter.rl import DonkeyDriftEnv  # noqa: E402

DEFAULT_SIM_APP = "/Users/hwp/Dev/DKC/sdsandbox/build/donkey_sim.app"
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs")

# sim 遥测核心字段(reward/obs 的硬依赖,缺一即 item1 fail)
CORE_FIELDS = ["pos", "speed", "cte", "gyro", "accel", "vel"]
# fork 已知全字段(只记录命中情况,不作为门槛)
KNOWN_FIELDS = ["forward_vel", "hit", "car", "lidar", "frame_id", "collision_impulse",
                "flipped", "stuck_time", "lap", "active_node", "total_nodes",
                "last_lap_time", "lap_count"]


class SmokeRunner:
    def __init__(self):
        self.items = []

    def item(self, item_id, name, mandatory, fn=None, *, status=None, detail=None):
        entry = {"id": item_id, "name": name, "mandatory": mandatory,
                 "status": None, "detail": {}}
        t0 = time.time()
        if status is not None:  # 预置结果(如 BLOCKER)
            entry["status"], entry["detail"] = status, detail or {}
        else:
            try:
                detail = fn() or {}
                entry["detail"] = detail
                entry["status"] = detail.pop("status", "pass")
            except Exception as e:
                entry["status"] = "fail"
                entry["detail"] = {"error": f"{type(e).__name__}: {e}",
                                   "trace": traceback.format_exc()[-1500:]}
        entry["elapsed_s"] = round(time.time() - t0, 2)
        self.items.append(entry)
        tag = {"pass": "PASS", "fail": "FAIL", "BLOCKER": "BLOCKER",
               "record": "REC "}.get(entry["status"], entry["status"])
        print(f"[{tag}] #{item_id} {name} ({entry['elapsed_s']}s)")
        for k, v in entry["detail"].items():
            vs = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
            print(f"        {k}: {vs[:300]}")
        return entry

    @property
    def summary(self):
        mand = [i for i in self.items if i["mandatory"]]
        return {
            "passed": sum(1 for i in self.items if i["status"] == "pass"),
            "record": sum(1 for i in self.items if i["status"] == "record"),
            "failed": sum(1 for i in self.items if i["status"] == "fail"),
            "blockers": sum(1 for i in self.items if i["status"] == "BLOCKER"),
            "mandatory_failed": [i["id"] for i in mand if i["status"] in ("fail", "BLOCKER")],
        }


def _fps_probe(env, n_steps: int, action=(0.0, 0.5)) -> dict:
    """n 步实测:吞吐、sim frame_id 推进、步耗时分布。"""
    tok = env._frame_token()
    fid0 = tok[1] if tok[0] == "fid" else None
    durations = []
    stale = 0
    t0 = time.perf_counter()
    for _ in range(n_steps):
        t1 = time.perf_counter()
        _, _, _, _, info = env.step(action)
        durations.append(time.perf_counter() - t1)
        if info.get("rl/stale"):
            stale += 1
    elapsed = time.perf_counter() - t0
    tok = env._frame_token()
    fid1 = tok[1] if tok[0] == "fid" else None
    out = {
        "n_steps": n_steps,
        "wall_elapsed_s": round(elapsed, 2),
        "steps_per_s": round(n_steps / elapsed, 2),
        "stale_steps": stale,
        "step_ms_p50": round(statistics.median(durations) * 1000, 1),
        "step_ms_p95": round(sorted(durations)[int(0.95 * len(durations)) - 1] * 1000, 1),
    }
    if fid0 is not None and fid1 is not None:
        out["sim_frame_id_delta"] = int(fid1 - fid0)
    return out


def _make_env(args, img_enc=None):
    return DonkeyDriftEnv(
        sim_host=args.host, sim_port=args.port, sim_path="remote",
        obs_mode="state", img_enc=img_enc,
        connect_timeout_s=90.0, frame_wait_timeout_s=2.0,
        sync_mode=getattr(args, "sync", False),
        sync_time_step=getattr(args, "sync_time_step", 0.05))


# ---------------------------------------------------------------------------
# 各测试项(sim 会话内执行)
# ---------------------------------------------------------------------------

def item1_connect_fields(env) -> dict:
    obs, info = env.reset()
    keys = sorted(k for k in info.keys() if not k.startswith("rl/"))
    missing = [f for f in CORE_FIELDS if f not in keys]
    known_hit = [f for f in KNOWN_FIELDS if f in keys]
    # M2 D0:node 字段经 viewer 提升后必须在 info 中存在(值本身记录判别
    # sim 是否真发:total_nodes ∈ {None,0,1} 视为未发,progress 自动退位移法)
    node_missing = [k for k in ("active_node", "total_nodes") if k not in keys]
    lift = {"active_node": info.get("active_node"),
            "total_nodes": info.get("total_nodes")}
    node_fed = info.get("total_nodes") not in (None, 0, 1)
    if missing or node_missing:
        return {"status": "fail", "info_keys": keys, "missing_core": missing,
                "node_keys_missing": node_missing, "known_hit": known_hit,
                "node_lift": lift, "obs_shape": list(obs.shape)}
    return {"status": "pass", "info_keys": keys, "known_hit": known_hit,
            "missing_core": [], "node_keys_missing": [],
            "node_lift": lift, "node_fields_sim_fed": bool(node_fed),
            "obs_shape": list(obs.shape),
            "reset_elapsed_s": info.get("rl/reset_elapsed_s"),
            "reset_mode": info.get("rl/reset_mode")}


def item2_reset_timing(env, trials=5) -> dict:
    # 先开出界一圈再复位:位姿跳变可观测,计时才有效
    for _ in range(40):
        env.step((0.0, 0.6))
    lat = []
    moved = 0
    for _ in range(trials):
        for _ in range(30):
            env.step((0.4, 0.5))
        _, info = env.reset()
        lat.append(info["rl/reset_elapsed_s"])
        moved += 1 if info.get("rl/reset_detected_move") else 0  # sync=None 不计
        info2 = env.step((0.0, 0.0))[4]
        assert info2.get("rl/sim_connected"), "复位后连接失活"
    p50 = statistics.median(lat)
    p95 = sorted(lat)[min(len(lat) - 1, int(0.95 * len(lat)))]
    status = "pass" if p95 < 2.0 else "fail"
    return {"status": status, "trials": trials, "p50_s": round(p50, 3),
            "p95_s": round(p95, 3), "max_s": round(max(lat), 3),
            "raw": [round(x, 3) for x in lat], "pose_jump_detected": moved}


def item3_boundary_actions(env) -> dict:
    seq = [(1.0, 1.0, 0.0), (-1.0, 1.0, 0.0), (0.0, 1.0, 1.0), (0.0, 0.0, 1.0),
           (-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (0.0, 0.0, 0.0), (0.5, 0.5, 0.5)]
    frames = 0
    if env.sync_mode:
        handler = getattr(env._sim_viewer(), "handler", None)
        for s, t, b in seq * 3:
            tok = env._frame_token()
            handler.send_control(s, t, b)  # sync:控制即步进(含 brake)
            _o, _r, _d, info4 = handler.observe()  # 拉帧进 cam.info(否则 token 永不变)
            env._cam.info = info4
            if env._frame_token() != tok:
                frames += 1
    else:
        for s, t, b in seq * 3:
            tok = env._frame_token()
            env._cam.run_threaded(s, t, b)  # 异步:part 原生 3 参通道(含 brake)
            if env._wait_new_frame(tok, 2.0):
                frames += 1
    ok = env.sim_connected and frames >= len(seq) * 3 - 1
    env.step((0.0, 0.3))  # 收尾恢复直行,确认遥测继续推进
    return {"status": "pass" if ok else "fail",
            "actions_sent": len(seq) * 3, "new_frames_seen": frames,
            "connected_after": env.sim_connected}


def item4_frame_correspondence(env, n=60) -> dict:
    tok = env._frame_token()
    fid0 = tok[1] if tok[0] == "fid" else None
    got_new = 0
    fids = []
    for _ in range(n):
        _, _, _, _, info = env.step((0.0, 0.4))
        got_new += 0 if info.get("rl/stale") else 1
        t = env._frame_token()
        if t[0] == "fid":
            fids.append(t[1])
    # 跨度 = 末帧相对「控制前」fid0 的推进:60 次相邻 +1 时 fids[-1]-fids[0]
    # 恒为 n-1(首帧已含第 1 个控制的增量)——必须相对 fid0 才是 n 的口径。
    span = (fids[-1] - fid0) if (fid0 is not None and fids) else None
    # 真实契约:① 每条 control 都等到一帧新遥测(构造保证,硬断言);
    # ② sync 一控制一帧 → 跨度恰为 n(无自由帧);
    #    async sim 20fps 自由跑,无新 control 的自由帧不递增 frame_id
    #    (2026-11-01 实测 60/60/59),允许 ≤1 帧差。
    if env.sync_mode:
        exact = got_new == n and span == n
    else:
        exact = got_new == n and (span is None or span >= n - 1)
    steps = [int(b - a) for a, b in zip(fids, fids[1:])] if len(fids) >= 2 else []
    dup_frames = steps.count(0)
    return {"status": "pass" if exact else "fail",
            "controls": n, "new_frames_received": got_new,
            "sim_frame_id_span_vs_pre_control": span,
            "fid_step_deltas": {"monotonic": all(s >= 0 for s in steps),
                                "dups": dup_frames,
                                "distribution": {str(v): steps.count(v)
                                                 for v in sorted(set(steps))}},
            "note": "每步等待新遥测帧返回,n control ↔ n 新帧由构造保证;"
                    "fid 停走=该拍 sim 未消费新 control 的自由帧(非丢帧)"}


def item7_seed_probe(env) -> dict:
    def poses(fn, n=3):
        out = []
        for _ in range(n):
            _, info = fn()
            out.append(tuple(round(float(x), 3) for x in info["pos"][:2]))
        return out

    seed_a = poses(lambda: env.reset(options={"spawn": True}, seed=42))
    seed_b = poses(lambda: env.reset(options={"spawn": True}, seed=7))
    plain = poses(lambda: env.reset())
    lat = poses(lambda: env.reset(options={"spawn_cfg": {"lateral_offset": 1.0}}))

    def spread(ps):
        xs = [p[0] for p in ps]
        ys = [p[1] for p in ps]
        return round(max(max(xs) - min(xs), max(ys) - min(ys)), 3)

    s_a, s_b, s_p = spread(seed_a), spread(seed_b), spread(plain)
    inter = max(
        max(abs(a[0] - b[0]) for a, b in zip(seed_a, seed_b)),
        max(abs(a[1] - b[1]) for a, b in zip(seed_a, seed_b)))
    if s_a < 0.1 and s_b < 0.1 and inter > 0.5:
        verdict = "sim 支持 reset_car 扩展字段(同 seed 可复现、异 seed 位置不同)——订单事实2的判死结论对本 sim 不成立"
    elif s_a < 0.1 and s_b < 0.1 and inter <= 0.5 and s_p < 0.1:
        verdict = "字段被忽略(各 reset 位置一致)——按订单事实2口径,随机出生对本 sim 不成立"
    else:
        verdict = "非确定(同 seed 位姿漂移)——符合 PhysX 方差预期,字段支持性需更大样本判别"
    return {"status": "record",
            "same_seed42_poses": seed_a, "same_seed7_poses": seed_b,
            "plain_reset_poses": plain, "lateral1_poses": lat,
            "intra_seed42_spread_m": s_a, "intra_seed7_spread_m": s_b,
            "inter_seed_max_diff_m": round(float(inter), 3),
            "plain_spread_m": s_p, "verdict": verdict}



def item8_sync_semantics(args) -> dict:
    """D1 语义自检(专用 headless sim = 训练形态):一控制一帧;停发控制
    sim 不前进;reset 走应答路径。

    ⚠ 窗口 sim 不作此检查口径:实测其渲染循环在 sync 下仍偶发背景帧
    (idle 1s 出现 +1),且步耗时 75ms vs headless 3ms(每步渲染相机)——
    sync 训练必须 -nographics/keep-gfx。
    """
    port = args.port + 10  # sim 实例占 port 与 port+1(见 _sim_proc 文档),+10 段隔离
    proc = launch_sim(args.sim_app, port=port, headless=True,
                      log_path=os.path.join(OUT_DIR, "sim_smoke_sync_sem.log"))
    env = DonkeyDriftEnv(sim_host=args.host, sim_port=port, sim_path="remote",
                         obs_mode="state", img_enc="none", sync_mode=True,
                         sync_time_step=args.sync_time_step,
                         connect_timeout_s=90.0, name="smoke-sync-sem")
    try:
        env.reset()
        fids, durs = [], []
        for _ in range(20):
            _, _, _, _, sinfo = env.step((0.0, 0.4))
            t = env._frame_token()
            assert t[0] == "fid", "sync 下 frame_id 缺失"
            fids.append(t[1])
            durs.append(sinfo["rl/step_elapsed_s"])
        deltas = [b - a for a, b in zip(fids, fids[1:])]
        one_per_step = all(d == 1 for d in deltas)
        fid0 = env._frame_token()[1]
        time.sleep(1.0)
        idle_delta = env._frame_token()[1] - fid0
        frozen = idle_delta == 0
        _, rinfo = env.reset(options={"spawn": True}, seed=5)
        answered = bool(rinfo.get("rl/reset_answered"))
        ok = one_per_step and frozen and answered
        return {"status": "pass" if ok else "fail",
                "frame_id_delta_per_step": {v: deltas.count(v) for v in set(deltas)},
                "idle_1s_frame_id_delta": idle_delta,
                "reset_answered": answered,
                "step_ms_p50": round(statistics.median(durs) * 1000, 1),
                "note": "headless(训练形态):一控制一帧 + sim 不在策略步间前进"}
    finally:
        env.close()
        stop_sim(proc=proc)


def item5_disconnect_recovery(env, args, launched) -> dict:
    """杀 sim → 等 connected 翻假 → 重拉 → 看门狗重建 → 遥测恢复。"""
    proc = launched.get("proc")
    stop_rec = stop_sim(proc=proc, port=args.port)
    launched["proc"] = None
    t_kill = time.time()
    died_at = None
    if env.sync_mode:
        # sync:无自由跑线程,sim_connected 即时查健康,无需步进喂看门狗
        while time.time() - t_kill < 30:
            if not env.sim_connected:
                died_at = time.time()
                break
            time.sleep(0.2)
    else:
        while time.time() - t_kill < 30:
            env.step((0.0, 0.0))
            if not env.sim_connected:
                died_at = time.time()
                break
    if died_at is None:
        return {"status": "fail", "stop": stop_rec,
                "error": "杀 sim 后 30s 内 connected 未翻假(看门狗失明)"}
    t_relaunch = time.time()
    proc2 = launch_sim(args.sim_app, port=args.port,
                       log_path=os.path.join(OUT_DIR, "sim_smoke_relaunch.log"))
    launched["proc"] = proc2
    recovered_at = None
    last_tok = env._frame_token()
    while time.time() - t_relaunch < 90:
        # sync:step 内部 _sync_ensure_connected 会等重连(阻塞至多 connect_timeout)
        env.step((0.0, 0.0))
        tok = env._frame_token()
        if env.sim_connected and tok != last_tok and tok[0] == "fid":
            recovered_at = time.time()
            break
        last_tok = tok
    if recovered_at is None:
        return {"status": "fail", "stop": stop_rec,
                "died_after_kill_s": round(died_at - t_kill, 2),
                "error": "重拉 sim 后 90s 内未恢复遥测"}
    _, info = env.reset()
    return {"status": "pass", "stop": stop_rec,
            "detect_death_s": round(died_at - t_kill, 2),
            "recovery_s": round(recovered_at - t_relaunch, 2),
            "post_recovery_reset_s": round(info.get("rl/reset_elapsed_s", -1), 3),
            "post_recovery_reset_move": info.get("rl/reset_detected_move")}


def _fps_pair_on_running_sim(args) -> dict:
    """sim 已就绪:当前 img_enc=none env 测一轮,再换 jpg env 测一轮。"""
    out = {}
    env = _make_env(args)
    try:
        env.reset()
        out["img_enc_none"] = _fps_probe(env, 150)
    finally:
        env.close()
    env = _make_env(args, img_enc="jpg")
    try:
        env.reset()
        out["jpg"] = _fps_probe(env, 150)
    finally:
        env.close()
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sim-app", default=DEFAULT_SIM_APP, help="sim .app 路径或裸二进制")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9091)
    ap.add_argument("--mode", choices=["auto", "remote"], default="auto",
                    help="auto=自拉 sim 全流程;remote=只连已运行的 sim(5/6 标 BLOCKER)")
    ap.add_argument("--sync", action="store_true",
                    help="M2:sync 模式全套重跑(一控制一帧;item6 换 sync 吞吐量级检查)")
    ap.add_argument("--sync-time-step", type=float, default=0.05)
    ap.add_argument("--telemetry-fps", type=int, default=None,
                    help="M2 可选探针(仅异步):sim 加 --telemetry_fps N 后实测步率,记录性")
    ap.add_argument("--out", default=os.path.join(OUT_DIR, "rl_smoke_result.json"))
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)

    runner = SmokeRunner()
    meta = {"sim_app": args.sim_app, "mode": args.mode, "host": args.host,
            "port": args.port, "started": time.strftime("%F %T"),
            "sim_exe": None}

    launched = {"proc": None}
    env = None
    can_launch = args.mode == "auto"
    if can_launch:
        try:
            launched["proc"] = launch_sim(args.sim_app, port=args.port,
                                          log_path=os.path.join(OUT_DIR, "sim_smoke_windowed.log"))
            meta["sim_exe"] = resolve_sim_exe(args.sim_app)
        except Exception as e:
            can_launch = False
            print(f"[BLOCKER] sim 拉起失败:{e}")
    else:
        if not wait_for_port(args.port, 3.0):
            print(f"[警告] :{args.port} 无人监听,remote 模式各项将按超时判定")

    def blocker(item_id, name, why):
        runner.item(item_id, name, True, status="BLOCKER",
                    detail={"reason": why})

    fps_detail = None
    try:
        env = _make_env(args)

        runner.item(1, "连接+info字段齐全性", True, lambda: item1_connect_fields(env))
        runner.item(2, "reset_car 耗时 p50/p95<2s", True, lambda: item2_reset_timing(env))
        runner.item(3, "边界动作含 brake 不炸连接", True, lambda: item3_boundary_actions(env))
        runner.item(4, "frame_skip=1 n control↔n 帧", True, lambda: item4_frame_correspondence(env))
        runner.item(7, "同seed复现+spawn字段探针(记录)", False, lambda: item7_seed_probe(env))
        if args.sync:
            runner.item(8, "sync 语义自检(headless:一控制一帧/停发冻结/应答)", True,
                        lambda: item8_sync_semantics(args))

        if not can_launch:
            blocker(6, "帧率实测", "P2 未拿到 sim 启动方式,无法控制 sim 生命周期(订单预案)")
            blocker(5, "断连恢复", "P2 未拿到 sim 启动方式,无法杀/拉 sim(订单预案)")
        elif args.sync:
            runner.item(6, "帧率实测(sync 单配置量级检查)", True,
                        lambda: item6_sync_throughput(args))
            runner.item(5, "断连恢复(杀→拉起→重建)", True,
                        lambda: item5_disconnect_recovery(env, args, launched))
        else:
            # 异步 item6:窗口段复用会话 A 的 sim(env 换 img_enc 各测一轮),
            # 随后两段 headless 会话各自拉起/停止;再重拉窗口 sim 做 item5
            env.close()
            env = None
            win = _fps_pair_on_running_sim(args)
            hg = _fps_session(args, headless=True, keep_graphics=True,
                              log_name="sim_smoke_headless_keepgfx.log")
            ng = _fps_session(args, headless=True, keep_graphics=False,
                              log_name="sim_smoke_headless_nographics.log")
            fps_detail = {"windowed": win, "headless_keep_gfx": hg,
                          "headless_nographics": ng}
            win_fps = win.get("img_enc_none", {}).get("steps_per_s", 0) or 0
            all_measured = all(
                (d or {}).get("img_enc_none", {}).get("steps_per_s", 0) > 0
                for d in (win, hg, ng))
            status = "pass" if all_measured and win_fps >= 10 else "fail"
            fps_detail["conclusion"] = (
                "窗口 %.1f 步/s;keep-gfx %.1f;nographics %.1f(none 编码口径)。"
                "nographics 若显著低于 keep-gfx,即坐实「无图形设备异步观测掉帧」教训,"
                "M3 多开应采用 keep-gfx 离屏渲染"
                % (win_fps,
                   hg.get("img_enc_none", {}).get("steps_per_s", 0) or -1,
                   ng.get("img_enc_none", {}).get("steps_per_s", 0) or -1))
            runner.item(6, "帧率实测(窗/headless×2 × img_enc)", True,
                        status=status, detail=fps_detail)

            # item5:重新拉起窗口 sim + 新 env,做断连恢复
            launched["proc"] = launch_sim(args.sim_app, port=args.port,
                                          log_path=os.path.join(OUT_DIR, "sim_smoke_windowed.log"))
            env = _make_env(args)
            env.reset()
            runner.item(5, "断连恢复(杀→拉起→看门狗重建)", True,
                        lambda: item5_disconnect_recovery(env, args, launched))

        if args.telemetry_fps and not args.sync and can_launch:
            runner.item(9, f"telemetry_fps={args.telemetry_fps} 探针(记录)", False,
                        lambda: item9_telemetry_fps_probe(args))
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:
                pass
        if launched.get("proc") is not None:
            stop_sim(proc=launched["proc"], port=args.port)
        elif wait_for_port(args.port, 0.5):
            stop_sim(port=args.port)

    result = {"meta": meta, "items": runner.items, "summary": runner.summary}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n=== smoke 完成:{runner.summary} → {args.out}")
    return 1 if runner.summary["mandatory_failed"] else 0


def item6_sync_throughput(args) -> dict:
    """sync 模式 item6:单配置吞吐量级检查(完整矩阵归 D2 bench)。

    用独立端口(args.port+2)拉 headless sim,不干扰窗口会话。
    """
    port = args.port + 11  # +10 段隔离(sim 占 port/port+1)
    proc = launch_sim(args.sim_app, port=port, headless=True,
                      log_path=os.path.join(OUT_DIR, "sim_smoke_sync_fps.log"))
    e = DonkeyDriftEnv(sim_host=args.host, sim_port=port, sim_path="remote",
                       obs_mode="state", img_enc="none", sync_mode=True,
                       sync_time_step=args.sync_time_step,
                       connect_timeout_s=90.0, name="smoke-sync-fps")
    try:
        e.reset(options={"spawn": True}, seed=1)
        d = _fps_probe(e, 300)
    finally:
        e.close()
        stop_sim(proc=proc)
    ok = d.get("steps_per_s", 0) >= 30
    return {"status": "pass" if ok else "fail", **d,
            "note": "sync 吞吐量级检查(≥30 步/s);完整矩阵见 rl_sync_bench.py"}


def item9_telemetry_fps_probe(args) -> dict:
    """可选举证:sim --telemetry_fps N 下异步步率(CLI > cam fps > 默认 20)。"""
    n = args.telemetry_fps
    proc = launch_sim(args.sim_app, port=args.port + 12, headless=True,
                      extra_args=["--telemetry_fps", str(n)],
                      log_path=os.path.join(OUT_DIR, "sim_smoke_tfps.log"))
    e = DonkeyDriftEnv(sim_host=args.host, sim_port=args.port + 12, sim_path="remote",
                       obs_mode="state", img_enc="none", sync_mode=False,
                       connect_timeout_s=90.0, name="smoke-tfps")
    try:
        e.reset()
        d = _fps_probe(e, 300)
    finally:
        e.close()
        stop_sim(proc=proc)
    return {"status": "record", **d,
            "expected_steps_per_s": n,
            "note": "记录性:CLI --telemetry_fps 优先级探针,非阻断"}


def _fps_session(args, headless: bool, keep_graphics: bool, log_name: str) -> dict:
    """独立 sim 会话:两档 img_enc 的帧率实测(item 6 headless 分片)。"""
    proc = None
    detail = {"headless": headless, "keep_graphics": keep_graphics}
    try:
        proc = launch_sim(args.sim_app, port=args.port, headless=headless,
                          keep_graphics=keep_graphics,
                          log_path=os.path.join(OUT_DIR, log_name))
        detail.update(_fps_pair_on_running_sim(args))
    except Exception as e:
        detail["error"] = f"{type(e).__name__}: {e}"
    finally:
        if proc is not None:
            stop_sim(proc=proc)
        else:
            stop_sim(port=args.port)
    return detail


if __name__ == "__main__":
    sys.exit(main())
