#!/usr/bin/env python3
"""M2 D3:SB3 PPO 冒烟训练(state obs × sync 0.05 × Phase A reward)。

铁律(内置,不是可选项;sdsandbox 2026-10-18/19 实战沉淀):
- --lr 默认 **1e-4**:PPO 默认 3e-4 对续训/热启动必过热发散(ep_len/ep_rew
  单 rollout 内单调跌 >30% 即止损),一律 1e-4 起步;
- --steps 语义 = **新增步数**:本脚本对 resume 显式换算
  learn 目标 = 当前终身计数 + steps;日志 total_timesteps 是终身计数,
  进度 = total_timesteps - resume 点计数;
- eval 过门立即**独立命名快照**(snap_<steps>/,禁止同路径覆盖——
  EvalCallback 同路径覆盖丢过一次 1816 步模型的教训);
- learn() 包 try/except,任何异常/中断自动存 *.crash 保命档;
- --run-name 隔离 tb/输出目录;收尾 close 优雅→兜底,sim 按子进程/端口清;
- 活性监控:steps/s 落出带宽(<30 或 >2000)、ep_rew 冻结、连续无 episode
  收束、sim 失联 → loud 报警并退出,绝不静默空转。

规模:~100k 步冒烟——目的 = 管线活着 + reward 分量行为合理,不是练好策略。
reward:Phase A(w_drift=0 循线向)+ w_done 显式开(撞墙必须有直接代价);
每步 reward 分量逐项落盘 run_dir/components.jsonl。
出生课程:node 随机(sim 侧 seed 抽)+ lateral 带符号 ±(训练侧 SpawnCurriculum,
防单侧偏科)+ heading_noise;默认 ±1.0m/±8° 为占位超参非标定。
收尾校准闸(弱版):straight demo 过 env+reward,累计 >0 且分量符号正确。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import traceback

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
sys.path.insert(0, os.path.dirname(_SCRIPTS_DIR))

from _sim_proc import launch_sim, stop_sim  # noqa: E402

# sys.path 卫生:scripts/ 里有上游遗留的 profile.py(TF profiling 演示),
# 会遮蔽 stdlib profile 并炸掉 torch→cProfile 的导入链——取到 _sim_proc
# 后立即移除该目录再 import torch/SB3(2026-11-02 实测教训)
sys.path[:] = [p for p in sys.path
               if os.path.abspath(p or os.getcwd()) != _SCRIPTS_DIR]

import numpy as np  # noqa: E402
import gymnasium as gym  # noqa: E402

from donkeydrifter.rl import DonkeyDriftEnv  # noqa: E402
from donkeydrifter.rl.curriculum import CurriculumConfig, SpawnCurriculum  # noqa: E402
from donkeydrifter.rl.rewards import DecomposedRewardWrapper, RewardConfig  # noqa: E402

DEFAULT_SIM_APP = "/Users/hwp/Dev/DKC/sdsandbox/build/donkey_sim.app"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_ROOT = os.path.join(REPO_ROOT, "outputs")

# 活性监控带宽(sync 0.05 state 实测 ~335 步/s;余量取整)
FPS_MIN, FPS_MAX = 30.0, 2000.0
NO_EPISODE_STEPS_LIMIT = 20000   # 连续无 episode 收束步数上限(cte 撞线通常几百步)
EP_REW_FREEZE_EPS = 1e-6
EP_REW_FREEZE_ROUNDS = 3


def _reward_cfg() -> RewardConfig:
    """Phase A:w_drift=0(循线向)+ w_done 显式开(撞墙必须有直接代价)。"""
    return RewardConfig(w_done=1.0)


class ComponentLogger(gym.Wrapper):
    """每步把分解 reward 的各分量落 jsonl(逐项记账,M2 验收数据源)。"""

    def __init__(self, env, log_path: str):
        super().__init__(env)
        self._fh = open(log_path, "w", encoding="utf-8")
        self._n = 0
        self._ep_rew = 0.0
        self._ep_steps = 0

    def reset(self, **kwargs):
        self._ep_rew = 0.0
        self._ep_steps = 0
        return self.env.reset(**kwargs)

    def step(self, action):
        obs, rew, term, trunc, info = self.env.step(action)
        comps = info.get("reward_components") or {}
        self._ep_rew += rew
        self._ep_steps += 1
        self._n += 1
        rec = {"i": self._n, "step_index": info.get("rl/step_index"),
               "reward": round(float(rew), 5),
               "raw_reward": round(float(info.get("raw_reward", 0.0)), 5),
               "ep_rew": round(self._ep_rew, 3), "ep_steps": self._ep_steps,
               "terminated": bool(term), "truncated": bool(trunc)}
        for k in ("cte", "progress", "drift", "overspeed", "step", "timeout", "done"):
            v = comps.get(k)
            if v is not None:
                rec[k] = round(float(v), 5)
        if comps.get("progress_method"):
            rec["progress_method"] = comps["progress_method"]
        self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if self._n % 256 == 0:
            self._fh.flush()
        return obs, rew, term, trunc, info

    def close(self):
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass
        return self.env.close()


class LivenessMonitor:
    """活性监控(由 SB3 适配器每步喂):fps 带宽/sim 失联/ep_rew 冻结/
    无 episode 收束 → loud 抛错退出,绝不静默空转。"""

    def __init__(self, env_ref, check_interval_s: float = 5.0):
        self._env_ref = env_ref
        self._interval = check_interval_s
        self._last_t = None
        self._last_steps = 0
        self._episode_rews: list = []
        self._cur_ep_rew = 0.0
        self._steps_since_episode = 0
        self._freeze_rounds = 0

    def reset_window(self) -> None:
        """eval-gate 等训练外耗时(拉 sim/评测/停 sim ≈10s)结束后重置 fps
        窗口,否则该段零步进会被算成「假步进」误报(2026-11-02 实测假阳性)。"""
        self._last_t = None

    def feed(self, num_timesteps: int, dones, infos) -> None:
        for info in (infos or []):
            comps = info.get("reward_components") or {}
            self._cur_ep_rew += comps.get("total", 0.0)
        if dones is not None and len(dones) and dones[0]:
            self._episode_rews.append(self._cur_ep_rew)
            self._cur_ep_rew = 0.0
            self._steps_since_episode = 0
        else:
            self._steps_since_episode += 1

        now = time.time()
        if self._last_t is None:
            self._last_t, self._last_steps = now, num_timesteps
            return
        if now - self._last_t < self._interval:
            return
        fps = (num_timesteps - self._last_steps) / max(now - self._last_t, 1e-6)
        self._last_t, self._last_steps = now, num_timesteps

        env = self._env_ref()
        connected = bool(env is not None and env.sim_connected)
        last_rew = self._episode_rews[-1] if self._episode_rews else float("nan")
        print(f"[liveness] steps={num_timesteps} fps={fps:.1f} "
              f"sim_connected={connected} episodes={len(self._episode_rews)} "
              f"last_ep_rew={last_rew:.2f}", flush=True)

        problems = []
        if not (FPS_MIN <= fps <= FPS_MAX):
            problems.append(f"steps/s={fps:.1f} 落出带宽 [{FPS_MIN},{FPS_MAX}](假步进/卡死嫌疑)")
        if not connected:
            problems.append("sim 连接失活")
        if self._steps_since_episode > NO_EPISODE_STEPS_LIMIT:
            problems.append(f"{self._steps_since_episode} 步无 episode 收束")
        if len(self._episode_rews) >= 10:
            m_r = statistics.mean(self._episode_rews[-5:])
            m_p = statistics.mean(self._episode_rews[-10:-5])
            if abs(m_r - m_p) < EP_REW_FREEZE_EPS:
                self._freeze_rounds += 1
            else:
                self._freeze_rounds = 0
            if self._freeze_rounds >= EP_REW_FREEZE_ROUNDS:
                problems.append(f"ep_rew 冻结 {self._freeze_rounds} 轮(近5局均值 {m_r:.3f})")
        if problems:
            print("\n!!!!!!!! 活性告警(loud)!!!!!!!!", flush=True)
            for p in problems:
                print("!! " + p, flush=True)
            print("!!!!!!!! 按纪律退出,绝不静默空转 !!!!!!!!\n", flush=True)
            raise RuntimeError("liveness: " + "; ".join(problems))


class KLToBCMonitor:
    """policy‖BC 的高斯 KL 只监控不进损失(prereg:默认 off,判定不用 KL,
    只做事后解读)。每 --kl-every 步对当前 rollout obs 采一条:
    KL(current DiagGaussian ‖ BC DiagGaussian) → jsonl + 周期打印。"""

    def __init__(self, ref_zip: str, log_path: str, every: int = 1000):
        from stable_baselines3 import PPO
        self.ref = PPO.load(ref_zip, device="cpu").policy
        self.ref.eval()
        self.every = max(1, int(every))
        self._fh = open(log_path, "w", encoding="utf-8")
        self._n = 0
        self._buf: list = []

    def feed(self, model, obs) -> None:
        self._n += 1
        if self._n % self.every:
            return
        import torch
        with torch.no_grad():
            ot, _ = model.policy.obs_to_tensor(np.asarray(obs)[None])
            kl = float(model.policy.get_distribution(ot).kl_loss(
                self.ref.get_distribution(ot)).item())
        self._buf.append(kl)
        self._fh.write(json.dumps({"step": self._n, "kl": round(kl, 6)}) + "\n")
        if len(self._buf) % 5 == 0:
            mean = statistics.mean(self._buf[-10:])
            print(f"[kl] step~{self._n} KL(policy‖BC) recent-mean={mean:.4f}", flush=True)

    def close(self):
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass


class EvalGate:
    """定期评测过门;过门 → 立即独立命名快照(禁止同路径覆盖)。

    评测用**独立 sim 实例**(独立端口),避免与训练 env 双车共用一条
    连接(同 guid/车名冲突风险);每个过门点快照到 snap_<steps>/ 新目录。
    """

    def __init__(self, sim_app: str, port: int, time_step: float,
                 episodes: int, run_dir: str, max_episode_steps: int,
                 curriculum_seed_offset: int = 5000):
        self.sim_app = sim_app
        self.port = port
        self.time_step = time_step
        self.episodes = episodes
        self.run_dir = run_dir
        self.max_episode_steps = max_episode_steps
        self.seed_offset = curriculum_seed_offset
        self.best = float("-inf")
        self.history: list = []

    def run(self, model, num_timesteps: int) -> None:
        proc = launch_sim(self.sim_app, port=self.port, headless=True,
                          log_path=os.path.join(OUT_ROOT, f"sim_evalgate_{self.port}.log"))
        env = DonkeyDriftEnv(sim_port=self.port, sim_path="remote", obs_mode="state",
                             img_enc="none", sync_mode=True, sync_time_step=self.time_step,
                             cte_limit=2.0, max_episode_steps=self.max_episode_steps,
                             spawn_curriculum=SpawnCurriculum(CurriculumConfig(
                                 seed=self.seed_offset + num_timesteps)),
                             connect_timeout_s=90.0, name="rl-evalgate")
        rews = []
        try:
            for ep in range(self.episodes):
                obs, _info = env.reset()
                done = False
                total = 0.0
                while not done:
                    action, _ = model.predict(obs, deterministic=True)
                    obs, r, term, trunc, _info2 = env.step(action)
                    total += r
                    done = term or trunc
                rews.append(total)
        finally:
            env.close()
            stop_sim(proc=proc)
        mean = float(np.mean(rews)) if rews else float("-inf")
        improved = mean > self.best
        snap_name = None
        if improved:
            self.best = mean
            snap_dir = os.path.join(self.run_dir, f"snap_{num_timesteps}")
            os.makedirs(snap_dir, exist_ok=True)
            model.save(os.path.join(snap_dir, "model"))
            snap_name = f"snap_{num_timesteps}"
        self.history.append({"steps": num_timesteps, "mean_rew": round(mean, 3),
                             "episodes": [round(x, 3) for x in rews],
                             "snapshot": snap_name})
        with open(os.path.join(self.run_dir, "eval_gate.json"), "w", encoding="utf-8") as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)
        print(f"[eval-gate] steps={num_timesteps} mean_rew={mean:.2f} "
              f"episodes={[round(x, 1) for x in rews]} -> "
              f"{'独立快照 ' + snap_name if improved else '未过门'}", flush=True)


def calibration_gate(sim_app: str, port: int, run_dir: str, time_step: float) -> dict:
    """弱版校准闸:straight demo 过 env+reward,累计 >0 且分量符号正确。

    ⚠ reset 必须带 spawn 字段(2026-11-02 实测):sync 下**裸 reset_car**
    (无字段)不会把车放回出生点(车留在原位,cte 残留旧值,出生即
    trunc)——带字段 spawn 在 M1/M2 反复验证可用。校准闸用固定起点
    (node 0 / lateral 0 / heading 0)保证「直线 demo」语义可复现。
    """
    proc = launch_sim(sim_app, port=port, headless=True,
                      log_path=os.path.join(OUT_ROOT, f"sim_gate_{port}.log"))
    env = DonkeyDriftEnv(sim_port=port, sim_path="remote", obs_mode="state",
                         img_enc="none", sync_mode=True, sync_time_step=time_step,
                         connect_timeout_s=90.0, name="rl-gate")
    try:
        wrapped = DecomposedRewardWrapper(env, cfg=_reward_cfg())
        wrapped.reset(options={"spawn_cfg": {"node_index": 0, "lateral_offset": 0.0,
                                             "heading_noise": 0.0}, "seed": 123})
        total = 0.0
        acc = {"cte": 0.0, "progress": 0.0, "drift": 0.0, "overspeed": 0.0, "done": 0.0}
        n = 120
        methods = set()
        for _ in range(n):
            _, r, term, trunc, info = wrapped.step((0.0, 0.5))
            total += r
            comps = info.get("reward_components") or {}
            for k in acc:
                acc[k] += comps.get(k, 0.0)
            if comps.get("progress_method"):
                methods.add(comps["progress_method"])
            if term or trunc:
                break
        checks = {
            "total_positive": total > 0,
            "progress_nonneg": acc["progress"] > 0,
            "drift_off_phaseA": acc["drift"] == 0.0,
            "overspeed_nonpos": acc["overspeed"] <= 0.0,
        }
        ok = all(checks.values())
        out = {"status": "pass" if ok else "fail", "steps": n,
               "cumulative_reward": round(total, 3),
               "component_sums": {k: round(v, 3) for k, v in acc.items()},
               "progress_methods": sorted(methods), "checks": checks}
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "calibration_gate.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("[gate] " + json.dumps(out, ensure_ascii=False), flush=True)
        return out
    finally:
        env.close()
        stop_sim(proc=proc)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sim-app", default=DEFAULT_SIM_APP)
    ap.add_argument("--port", type=int, default=9091)
    ap.add_argument("--steps", type=int, default=100_000,
                    help="新增步数(非绝对累计;resume 时换算为终身计数目标)")
    ap.add_argument("--lr", type=float, default=1e-4,
                    help="PPO 学习率;默认 1e-4(3e-4 过热发散铁律)")
    ap.add_argument("--run-name", default="rl_m2_smoke", help="tb/输出目录隔离名")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--time-step", type=float, default=0.05, help="sync 步长(0.05/0.02)")
    ap.add_argument("--resume", default=None, help="续训模型路径(不带 .zip,SB3 自动补)")
    ap.add_argument("--max-episode-steps", type=int, default=2000)
    ap.add_argument("--eval-every", type=int, default=50_000)
    ap.add_argument("--gate-episodes", type=int, default=3)
    ap.add_argument("--curriculum-lateral", type=float, default=1.0,
                    help="出生横向 ± 幅度(米,占位超参非标定)")
    ap.add_argument("--curriculum-heading", type=float, default=8.0,
                    help="出生朝向噪声上限(度,占位超参非标定)")
    ap.add_argument("--skip-gate", action="store_true", help="跳过收尾校准闸")
    ap.add_argument("--kl-monitor", action="store_true",
                    help="M3 D3:KL(policy‖BC) 只监控不进损失(默认 off;参照 = --resume)")
    ap.add_argument("--kl-every", type=int, default=1000)
    args = ap.parse_args()

    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback
    from stable_baselines3.common.vec_env import DummyVecEnv

    run_dir = os.path.join(OUT_ROOT, "rl_runs", args.run_name)
    os.makedirs(run_dir, exist_ok=True)
    print(f"[train] run_dir={run_dir} lr={args.lr} 新增步数={args.steps}", flush=True)

    curriculum = SpawnCurriculum(CurriculumConfig(
        lateral=args.curriculum_lateral, heading=args.curriculum_heading,
        seed=args.seed))
    sim_proc = launch_sim(args.sim_app, port=args.port, headless=True,
                          log_path=os.path.join(OUT_ROOT, f"sim_train_{args.port}.log"))

    def _make_env():
        env = DonkeyDriftEnv(
            sim_port=args.port, sim_path="remote", obs_mode="state", img_enc="none",
            sync_mode=True, sync_time_step=args.time_step,
            cte_limit=2.0, max_episode_steps=args.max_episode_steps,
            spawn_curriculum=curriculum, connect_timeout_s=90.0,
            frame_wait_timeout_s=2.0, name=f"rl-{args.run_name}")
        return ComponentLogger(DecomposedRewardWrapper(env, cfg=_reward_cfg()),
                               log_path=os.path.join(run_dir, "components.jsonl"))

    vec = DummyVecEnv([_make_env])
    eval_gate = EvalGate(args.sim_app, args.port + 4, args.time_step,
                         args.gate_episodes, run_dir, args.max_episode_steps)
    liveness = LivenessMonitor(env_ref=lambda: vec.envs[0].unwrapped,
                               check_interval_s=5.0)

    kl_mon = None
    if args.kl_monitor:
        ref = args.resume or (args.run_name and None)
        if not ref:
            raise SystemExit("--kl-monitor 需要 --resume <bc.zip> 作为 KL 参照")
        kl_mon = KLToBCMonitor(ref, os.path.join(run_dir, "kl_monitor.jsonl"),
                               every=args.kl_every)
        print(f"[kl] 监控开启(参照 {ref};只记录不进损失)", flush=True)

    class _Adapter(BaseCallback):
        """把 SB3 每步喂给监控与过门(本文件逻辑不直接继承 SB3,便于离线测)。"""

        def __init__(self):
            super().__init__()
            self._gate_at = args.eval_every

        def _on_step(self) -> bool:
            liveness.feed(self.num_timesteps, self.locals.get("dones"),
                          self.locals.get("infos"))
            if kl_mon is not None:
                new_obs = self.locals.get("new_obs")
                if new_obs is not None and len(new_obs):
                    kl_mon.feed(self.model, new_obs[0])
            if self.num_timesteps >= self._gate_at:
                self._gate_at += args.eval_every
                eval_gate.run(self.model, self.num_timesteps)
                liveness.reset_window()  # gate 耗时不计入 fps 带宽判定
            return True

    model = None
    exit_code = 0
    try:
        if args.resume:
            model = PPO.load(args.resume, env=vec, seed=args.seed,
                             custom_objects={"learning_rate": args.lr})
            model.learning_rate = args.lr  # 铁律:续训一律 1e-4 起步
            print(f"[train] resume {args.resume}(lr 重置为 {args.lr})", flush=True)
        else:
            model = PPO("MlpPolicy", vec, seed=args.seed, learning_rate=args.lr,
                        n_steps=2048, batch_size=64, gamma=0.99,
                        tensorboard_log=run_dir, verbose=0)
        total_target = args.steps + (model.num_timesteps if args.resume else 0)
        print(f"[train] learn 目标(终身计数)={total_target}"
              f"(新增 {args.steps})", flush=True)

        ckpt = CheckpointCallback(save_freq=max(1, 25_000),
                                  save_path=os.path.join(run_dir, "ckpt"),
                                  name_prefix="ppo")
        t0 = time.time()
        try:
            model.learn(total_timesteps=total_target,
                        callback=[ckpt, _Adapter()],
                        tb_log_name=args.run_name)
        except Exception as e:
            # 保命档:任何异常/中断自动存 *.crash(丢过 1816 步模型的教训)
            crash = os.path.join(run_dir, f"model_{int(time.time())}.crash")
            try:
                model.save(crash)
            except Exception as se:
                print(f"[train] crash 档保存失败: {se}", flush=True)
            print(f"[train] learn 异常退出(已存 {crash}): {type(e).__name__}: {e}",
                  flush=True)
            traceback.print_exc()
            exit_code = 2
            return
        wall = time.time() - t0

        final = os.path.join(run_dir, "final_model")
        model.save(final)
        fps = model.num_timesteps / max(wall, 1e-6)
        meta = {"run_name": args.run_name, "new_steps": args.steps,
                "total_timesteps": model.num_timesteps, "lr": args.lr,
                "seed": args.seed, "time_step": args.time_step,
                "wall_s": round(wall, 1), "steps_per_s_incl_updates": round(fps, 1),
                "sb3": __import__("stable_baselines3").__version__,
                "torch": __import__("torch").__version__,
                "reward_cfg": str(_reward_cfg()),
                "curriculum": {"lateral": args.curriculum_lateral,
                               "heading": args.curriculum_heading, "seed": args.seed},
                "finished_at": time.strftime("%F %T")}
        with open(os.path.join(run_dir, "train_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"[train] 完成:终身 {model.num_timesteps} 步 / {wall:.0f}s "
              f"= {fps:.1f} 步/s(含更新)→ {final}", flush=True)

        if not args.skip_gate:
            calibration_gate(args.sim_app, args.port + 5, run_dir, args.time_step)
    finally:
        # 收尾:优雅 close(带超时)→ sim 按子进程/端口清(纪律红线,零 pkill)
        try:
            vec.close()
        except Exception as e:
            print(f"[train] vec.close 异常(忽略): {e}", flush=True)
        if kl_mon is not None:
            kl_mon.close()
        stop_sim(proc=sim_proc, port=args.port)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
