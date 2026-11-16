#!/usr/bin/env python3
"""M3 D0:BC 级遥测采样(键控走线驾驶,观测→动作配对)。

升级自 M1 版(β 采样):每帧同步落 image + state_vec + action + 遥测,
按局写 `bc_%05d.npz`(格式/列定义见 donkeydrifter/rl/bc_data.py),退出时
落 data_card.json(键名对齐 sdsandbox + 门判定)+ 4×4 蒙太奇 jpg;
同时写 teleop.npz(M1 β 口径兼容,rl_beta_analyze.py 可继续消费)。

**配对口径 = 观测→动作**(obs_k 配人对 obs_k 的反应 a_k),BC 训练直接用;
M1 版是「动作→结果」口径,meta 的 frame_id 使两种都可重建。

键控(终端 raw,松键保持):w/s 油门 a/d 转向 space 刹车 x 归零
  r = 复位并开新局(带 spawn 配置)  q = 退出落盘
模式:
  (默认)async 20fps 键控——人驾自然节拍,**不用 sync**(sync 步进由控制触发,
        人驾节拍不成立);
  --script demo|straight|circle|slalom —— 脚本化序列(管线自测,非人驾数据)。
spawn 起点:--spawn-node/--spawn-lateral/--spawn-heading/--spawn-seed
  (async 走 env reset options spawn_cfg,带字段才复位——M2 已核);
  每局 seed = --spawn-seed + ep 序号(起点随局变化)。
局切分:r 键手动 + --auto-episode-frames N 自动切段(不复位,连续驾驶分段,
  分层 val 用;边界有少量时间相邻泄漏,如实记录于 meta)。

用法:
    .venv/bin/python scripts/rl_teleop_record.py --out outputs/bc_data_run1
    .venv/bin/python scripts/rl_teleop_record.py --script demo --duration 20
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
sys.path.insert(0, os.path.dirname(_SCRIPTS_DIR))

from _sim_proc import launch_sim, resolve_sim_exe, stop_sim  # noqa: E402
from rl_teleop_keyctl import KeyTeleop, scripted_action, _NullCtx  # noqa: E402
# sys.path 卫生:scripts/ 有上游遗留 profile.py 遮蔽 stdlib(见 rl_train.py),
# 取完 scripts 内模块后立即移除该目录再 import 仓库包
sys.path[:] = [p for p in sys.path
               if os.path.abspath(p or os.getcwd()) != _SCRIPTS_DIR]

from donkeydrifter.rl import DonkeyDriftEnv  # noqa: E402
from donkeydrifter.rl.bc_data import (  # noqa: E402
    META_COLUMNS, EpisodeBuffer, compute_data_card, dump_card, load_dataset,
    make_montage, write_episode_npz)

DEFAULT_SIM_APP = "/Users/hwp/Dev/DKC/sdsandbox/build/donkey_sim.app"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sim-app", default=DEFAULT_SIM_APP)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9091)
    ap.add_argument("--remote", action="store_true", help="不拉 sim,连已运行的")
    ap.add_argument("--script", choices=["demo", "straight", "circle", "slalom"],
                    help="脚本化控制(管线自测,非人驾)")
    ap.add_argument("--duration", type=float, default=20.0, help="脚本模式时长(秒)")
    ap.add_argument("--out", default=None,
                    help="输出目录(默认 outputs/bc_data_<时间戳>)")
    ap.add_argument("--img-enc", default="jpg", choices=["jpg", "png"],
                    help="sim 出图编码(pixel 帧);'none' 无法采样")
    ap.add_argument("--auto-episode-frames", type=int, default=400,
                    help="自动切段帧数(20s@20fps;0=禁用,仅 r 键切局)")
    ap.add_argument("--max-frames", type=int, default=0, help="0=不限;>0 到帧即停")
    ap.add_argument("--spawn-node", type=int, default=None)
    ap.add_argument("--spawn-lateral", type=float, default=None)
    ap.add_argument("--spawn-heading", type=float, default=None)
    ap.add_argument("--spawn-seed", type=int, default=1000,
                    help="spawn 种子基数;每局 seed = 基数 + ep 序号")
    ap.add_argument("--car-name", default="bc-teleop")
    ap.add_argument("--eval-mode", action="store_true",
                    help="M4 D3:人驾基线模式——自动 12 局(spawn 序列与 RL held-out "
                         "完全同源:SpawnCurriculum(seed=50000) 默认档),局终判定与 "
                         "RL 相同(|锚定cte|>2 或 2000 帧),录全遥测供离线打分")
    ap.add_argument("--eval-episodes", type=int, default=12)
    ap.add_argument("--eval-seed-base", type=int, default=50000)
    ap.add_argument("--cte-anchor", default="docs/arch/rl-m4-driveline.json",
                    help="eval 模式的锚(与 RL 一致;设为空串=center)")
    args = ap.parse_args()

    out_dir = args.out or os.path.join(REPO_ROOT, "outputs",
                                       f"bc_data_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(out_dir, exist_ok=True)

    anchor_cfg = None
    if args.eval_mode and args.cte_anchor:
        with open(args.cte_anchor, encoding="utf-8") as f:
            doc = json.load(f)
        anchor_cfg = {"mode": "line", "offsets": doc["offsets"],
                      "cte_unit_gain": doc["cte_unit_gain"]}

    spawn_base = {}
    if args.spawn_node is not None:
        spawn_base["node_index"] = int(args.spawn_node)
    if args.spawn_lateral is not None:
        spawn_base["lateral_offset"] = float(args.spawn_lateral)
    if args.spawn_heading is not None:
        spawn_base["heading_noise"] = float(args.spawn_heading)
    has_spawn = bool(spawn_base)

    proc = None
    if not args.remote:
        proc = launch_sim(args.sim_app, port=args.port,
                          log_path=os.path.join(REPO_ROOT, "outputs",
                                                f"sim_bc_{int(time.time())}.log"))
    # async + pixel:人驾自然节拍;图像经 sim JPEG → cam.frame(160×120 uint8)
    from donkeydrifter.rl.curriculum import CurriculumConfig, SpawnCurriculum
    eval_curr = (SpawnCurriculum(CurriculumConfig(seed=args.eval_seed_base))
                 if args.eval_mode else None)
    env = DonkeyDriftEnv(sim_host=args.host, sim_port=args.port, sim_path="remote",
                         obs_mode="pixel", img_enc=args.img_enc,
                         sync_mode=False, connect_timeout_s=90.0,
                         frame_wait_timeout_s=2.0, cte_anchor=anchor_cfg,
                         name=args.car_name)
    meta_path = os.path.join(out_dir, "meta.json")
    eval_fh = None
    if args.eval_mode:
        eval_fh = open(os.path.join(out_dir, "eval_frames.jsonl"), "w", encoding="utf-8")
        print(f"[bc][eval] 人驾基线模式:{args.eval_episodes} 局,锚="
              f"{args.cte_anchor or 'center'},局终=|锚定cte|>2 或 2000 帧")
    print(f"[bc] 输出目录:{out_dir}")
    print(f"[bc] spawn:{'node/lateral/heading + seed' if has_spawn else '未指定→就近复位'}"
          f" | 键控:w/s 油门 a/d 转向 space 刹车 x 归零 r 新局 q 退出")

    ep_index = 0
    buf = EpisodeBuffer(ep_index)
    ep_files: list = []
    ep_records: list = []
    all_steer, all_thr, all_brake = [], [], []
    img_std_samples: list = []
    dropped = 0
    disconnects = 0
    spawn_points = []
    t_start = time.perf_counter()
    prev_a = (0.0, 0.0)
    obs_image = None

    def snap_obs():
        """当前帧快照:image copy + state_vec(口径 = env.state_vector)。"""
        img = np.array(env._cam.frame, dtype=np.uint8, copy=True)
        svec = env.state_vector(prev_action=prev_a)
        tele = dict(getattr(env._cam, "info", {}) or {})
        return img, svec, tele

    def do_reset(ep_i: int) -> dict:
        if args.eval_mode:
            # 与 RL held-out 同源:SpawnCurriculum(seed=50000) 逐局 sample
            cfg = eval_curr.sample()
            _, info = env.reset(options={"spawn_cfg": cfg}, seed=None)
            spawn_points.append({"ep": ep_i, "cfg": cfg,
                                 "pos": [round(float(x), 3) for x in info["pos"][:2]]})
            return info
        if has_spawn:
            cfg = dict(spawn_base)
            opts = {"spawn_cfg": cfg}
            seed = int(args.spawn_seed) + ep_i
        else:
            opts, seed = None, None
        _, info = env.reset(options=opts, seed=seed)
        return info

    try:
        info = do_reset(ep_index)
        spawn_points.append({"ep": ep_index, "pos": [round(float(x), 3) for x in info["pos"][:2]],
                             "cfg": dict(spawn_base) if has_spawn else None,
                             "seed": (int(args.spawn_seed) + ep_index) if has_spawn else None})
        obs_image, _, _ = snap_obs()
        print(f"[bc] ep{ep_index} 复位完成(mode={info.get('rl/reset_mode')});"
              + (f"脚本 {args.script} {args.duration}s" if args.script else "开始键控"))
        teleop = KeyTeleop() if not args.script else None
        last_t = time.perf_counter()
        t0 = t_start
        frames_ep = 0
        with (teleop if teleop else _NullCtx()) as kt:
            while True:
                now = time.perf_counter()
                dt, last_t = now - last_t, now
                elapsed = now - t0
                if args.script:
                    if elapsed > args.duration:
                        break
                    a = scripted_action(args.script, elapsed)
                    steer, throttle, brake = a
                else:
                    kt.poll(dt)
                    if kt.quit:
                        break
                    steer, throttle, brake = kt.action()
                    if "r" in getattr(kt, "last_keys", ""):
                        # 新局:r 键复位(带 spawn),本帧不入数据
                        write_episode_npz(out_dir, buf)
                        if len(buf):
                            ep_files.append(f"bc_{buf.ep_id:05d}.npz")
                            ep_records.append({"ep": buf.ep_id, "frames": len(buf)})
                        ep_index += 1
                        buf = EpisodeBuffer(ep_index)
                        prev_a = (0.0, 0.0)
                        frames_ep = 0
                        info = do_reset(ep_index)
                        spawn_points.append({"ep": ep_index,
                                             "pos": [round(float(x), 3) for x in info["pos"][:2]],
                                             "cfg": dict(spawn_base) if has_spawn else None,
                                             "seed": (int(args.spawn_seed) + ep_index) if has_spawn else None})
                        obs_image, _, _ = snap_obs()
                        print(f"[bc] ep{ep_index} 新局复位(mode={info.get('rl/reset_mode')})")
                        kt.last_keys = ""
                        continue

                tele = dict(getattr(env._cam, "info", {}) or {})
                if args.eval_mode:
                    # D3:录全遥测(锚定 cte 在 tele["cte"],raw 在 cte_raw)
                    row = {"ep": ep_index, "t": round(time.perf_counter() - t_start, 4),
                           "frame_id": tele.get("frame_id"),
                           "pos": list(tele.get("pos", ())), "speed": tele.get("speed"),
                           "forward_vel": tele.get("forward_vel"),
                           "cte": tele.get("cte"), "cte_raw": tele.get("cte_raw"),
                           "active_node": tele.get("active_node"),
                           "vel": list(tele.get("vel", ())),
                           "gyro": list(tele.get("gyro", ())),
                           "accel": list(tele.get("accel", ())),
                           "rpy": list(tele.get("car", ())),
                           "action": [steer, throttle, brake]}
                    eval_fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    steps_ep += 1
                    end = None
                    try:
                        if tele.get("cte") is not None and abs(float(tele["cte"])) > 2.0:
                            end = "cte_limit"
                    except (TypeError, ValueError):
                        pass
                    if end is None and steps_ep >= 2000:
                        end = "step_budget"
                    prev_a = (steer, throttle)
                    obs_image, _, _ = snap_obs()
                    if end is not None:
                        ep_records.append({"ep": ep_index, "frames": steps_ep,
                                           "end_reason": end})
                        print(f"[bc][eval] ep{ep_index} 终止({end}) {steps_ep} 帧")
                        ep_index += 1
                        steps_ep = 0
                        prev_a = (0.0, 0.0)
                        if ep_index >= args.eval_episodes:
                            break
                        info = do_reset(ep_index)
                        obs_image, _, _ = snap_obs()
                        print(f"[bc][eval] ep{ep_index} 复位完成")
                    else:
                        tok = env._frame_token()
                        env._cam.run_threaded(steer, throttle, brake)
                        if not env._wait_new_frame(tok, 2.0):
                            dropped += 1
                        if int(steps_ep * 2) != int((steps_ep - 1) * 2):
                            print(f"[bc][eval] ep{ep_index} {steps_ep} 帧 "
                                  f"cte'={tele.get('cte')}")
                    continue

                # 记录 obs_k → a_k(观测→动作配对;label 为本循环读到的动作)
                fid = tele.get("frame_id")
                svec = env.state_vector(prev_action=prev_a)
                buf.add(obs_image if obs_image is not None else np.zeros((120, 160, 3), np.uint8),
                        svec, (steer, throttle, brake), tele, fid,
                        time.perf_counter() - t_start)
                all_steer.append(steer)
                all_thr.append(throttle)
                all_brake.append(brake)
                if len(buf) % 40 == 0:  # 全局 img std 抽样(每 40 帧)
                    img_std_samples.append(float(np.asarray(obs_image, dtype=float).std()))
                frames_ep += 1
                total_frames = len(all_steer)

                # 喂动作 → 等下一帧
                tok = env._frame_token()
                env._cam.run_threaded(steer, throttle, brake)
                if not env._wait_new_frame(tok, 2.0):
                    dropped += 1
                if not env.sim_connected:
                    disconnects += 1
                prev_a = (steer, throttle)
                obs_image, _, _ = snap_obs()  # 下一循环的 obs_k(含 prev=本次动作)

                if args.eval_mode:
                    pass
                elif args.auto_episode_frames and frames_ep >= args.auto_episode_frames:
                    write_episode_npz(out_dir, buf)
                    if len(buf):
                        ep_files.append(f"bc_{buf.ep_id:05d}.npz")
                        ep_records.append({"ep": buf.ep_id, "frames": len(buf)})
                    ep_index += 1
                    buf = EpisodeBuffer(ep_index)
                    frames_ep = 0
                if args.max_frames and total_frames >= args.max_frames:
                    break
                if args.script and int(elapsed * 2) != int((elapsed - dt) * 2):
                    print(f"[bc] {elapsed:5.1f}s/{args.duration}s 帧={total_frames} "
                          f"ep={ep_index} drop={dropped}")
    finally:
        write_episode_npz(out_dir, buf)
        if len(buf):
            ep_files.append(f"bc_{buf.ep_id:05d}.npz")
            ep_records.append({"ep": buf.ep_id, "frames": len(buf)})
        env.close()
        if proc is not None:
            stop_sim(proc=proc)

    n = len(all_steer)
    if args.eval_mode:
        if eval_fh is not None:
            eval_fh.flush(); eval_fh.close()
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"mode": "eval", "args": vars(args), "episodes": ep_records,
                       "anchor": args.cte_anchor,
                       "eval_seed_base": args.eval_seed_base,
                       "wall_s": round(time.perf_counter() - t_start, 1)},
                      f, ensure_ascii=False, indent=2)
        print(f"[bc][eval] 完成 {len(ep_records)} 局 → {meta_path}")
        return
    if n == 0:
        print("[bc] 无数据,不落盘")
        return
    # teleop.npz 兼容(M1 rl_beta_analyze 可读;列为 M1 口径)+ data card + 蒙太奇
    montage, img_std_last = None, float("nan")
    try:
        ds = load_dataset(out_dir)
        imgs, metas = ds["image"], ds["meta"]
        np.savez_compressed(
            os.path.join(out_dir, "teleop.npz"),
            t=metas[:, 2], frame_id=metas[:, 1],
            pos=metas[:, 3:6], speed=metas[:, 6], forward_vel=metas[:, 7],
            cte=metas[:, 8], gyro=metas[:, 10:13], accel=metas[:, 13:16],
            vel=metas[:, 9:12], rpy=metas[:, 18:21],
            action=np.stack([ds["steer"], ds["throttle"], ds["brake"]], axis=1))
        montage = make_montage(imgs, os.path.join(out_dir, "montage.jpg"))
        img_std_last = float(np.asarray(imgs[-300:], dtype=float).std())
        card_meta = metas
    except Exception as e:
        card_meta = np.zeros((0, len(META_COLUMNS)), np.float32)
        montage = f"(失败: {e})"

    fps_measured = round(n / max(time.perf_counter() - t_start, 1e-6), 2)
    card = compute_data_card(
        steer=np.asarray(all_steer), throttle=np.asarray(all_thr),
        brake=np.asarray(all_brake),
        meta=card_meta,
        img_std_samples=img_std_samples, img_std_last_shard=img_std_last,
        fps_measured=fps_measured, dropped_frames=dropped,
        disconnects=disconnects, spawn_points=spawn_points,
        extra={"sim_app": resolve_sim_exe(args.sim_app), "script": args.script,
               "img_enc": args.img_enc, "auto_episode_frames": args.auto_episode_frames,
               "montage": os.path.basename(montage) if isinstance(montage, str) else montage,
               "recorded_at": time.strftime("%F %T")})
    dump_card(out_dir, card)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"args": vars(args), "out_dir": out_dir,
                   "episodes": ep_records, "frames_total": n},
                  f, ensure_ascii=False, indent=2)
    print(f"[bc] {n} 帧 / {card['episodes']} 局 → {out_dir}")
    print(f"[bc] 门判定:{json.dumps(card['gates'], ensure_ascii=False)}")
    print(f"[bc] hard gates 全过:{card['gates_pass_all_hard']}")


if __name__ == "__main__":
    main()
