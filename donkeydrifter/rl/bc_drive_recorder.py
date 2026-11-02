"""M3 D0 补丁(2026-11-03):Drive 管线内嵌 BC 录制器——网页驾驶采样用。

背景:用户的驾驶入口是 DonkeyDrift 网页控制台(DriveApiBridge → vehicle →
dgym part → sim),终端键控不适用;sdsim 的 ``observe_player`` 只能重绑到本地
玩家车(TcpCarHandler.cs:634,cars[0]),旁观者路线对网页驾驶的 TCP 车不通。
故把录制做成 drive vehicle 里的一个 part,用户驾驶流零改动:

- 数据源 = dgym part 的 ``info``/``frame``(**与 DonkeyDriftEnv 同一来源**),
  state_vec 由 :func:`donkeydrifter.rl.env.build_state_vector` 产出——训练
  state obs 的同一纯函数,口径强制一致;
- 配对 = ``(obs_k, u_k)``:obs_k 为本 tick 最新遥测/图像(由上一条动作产
  生,state_vec 的 prev_action 分量 = u_{k-1}),与 ``DonkeyDriftEnv.step``
  训练语义一致(M3 prereg 的 state-BC 数据契约);
- 节拍 = vehicle 主循环(DRIVE_LOOP_HZ,默认 20Hz)≈ sim 遥测节拍;遥测
  frame_id 未前进的重复 tick 跳过并计数(逐帧一对一记录);
  ⚠ 已知口径注记:threaded cam 与主循环并发,u_k 偶尔已在本 tick 早段被
  cam 线程消费,个别帧退化为「动作→结果」配对——donkeycar tub 录制的
  固有模糊,生态默认口径,接受并在此留痕;
- 分局 = 帧数自动切段(连续驾驶不复位;边界少量相邻泄漏,bc_data 文档
  约定已声明,分层 val 用整局切分);
- 落盘 = bc_%05d.npz + data_card.json + 蒙太奇(donkeydrifter.rl.bc_data,
  D2 bc_train 直接消费);停驾(Vehicle.stop → shutdown)触发落卡并打印
  门判定(hard_frac≥15% 等硬门,过门才允许进 A/B)。

接线:templates/simulator.py(DONKEY_GYM 分支,tub 之后);开关 =
``cfg.BC_RECORD_OUT``(myconfig 设置输出目录,None=关)。
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Tuple

import numpy as np

from .bc_data import (
    EpisodeBuffer,
    compute_data_card,
    dump_card,
    load_dataset,
    make_montage,
    write_episode_npz,
)
from .env import build_state_vector

__all__ = ["DriveBcRecorder"]


class DriveBcRecorder:
    """donkeycar vehicle part:``run(user/angle, user/throttle)`` 逐 tick 记录。

    与 TubWriter 并存(tub 是车链路资产,本录制器是 RL BC 数据契约:
    image + state_vec + 动作三元组,格式 D2 直接消费)。不依赖 web 页的
    record 开关——开着就录,停驾即落卡。
    """

    def __init__(self, cam: Any, out_dir: str, auto_episode_frames: int = 400):
        self._cam = cam
        self.out_dir = str(out_dir)
        os.makedirs(self.out_dir, exist_ok=True)
        self.auto_episode_frames = max(0, int(auto_episode_frames))
        self._buf = EpisodeBuffer(0)
        self._ep_index = 0
        self._frames_ep = 0
        self._prev_a: Tuple[float, float] = (0.0, 0.0)
        self._last_fid: Any = None
        self._t0 = time.perf_counter()
        self._steer: List[float] = []
        self._thr: List[float] = []
        self._brake: List[float] = []
        self._img_std_samples: List[float] = []
        self._skipped_stale = 0
        self._defect_ticks = 0
        self._shutdown_done = False

    # ------------------------------------------------------------------
    # vehicle part 协议
    # ------------------------------------------------------------------

    def run(self, angle: float, throttle: float) -> None:
        if self._shutdown_done:
            return
        info: Dict[str, Any] = dict(getattr(self._cam, "info", {}) or {})
        frame = getattr(self._cam, "frame", None)
        fid = info.get("frame_id")
        if frame is None:
            # 相机未就绪(连接建立初期):不记录,但动作链照常推进
            self._prev_a = (float(angle), float(throttle))
            return
        if self._last_fid is not None and fid == self._last_fid:
            # 遥测未前进的重复 tick:跳过(与终端采样器口径一致,逐帧一对一)
            self._skipped_stale += 1
            self._prev_a = (float(angle), float(throttle))
            return

        img = np.array(frame, dtype=np.uint8, copy=True)
        svec, defects = build_state_vector(info, self._prev_a)
        if defects:
            self._defect_ticks += 1
        self._buf.add(img, svec, (float(angle), float(throttle), 0.0),
                      info, fid, time.perf_counter() - self._t0)
        self._steer.append(float(angle))
        self._thr.append(float(throttle))
        self._brake.append(0.0)
        if len(self._buf) % 40 == 0:  # 全局 img std 抽样(每 40 帧)
            self._img_std_samples.append(float(img.astype(np.float32).std()))
        self._prev_a = (float(angle), float(throttle))
        self._last_fid = fid
        self._frames_ep += 1
        if self.auto_episode_frames and self._frames_ep >= self.auto_episode_frames:
            self._flush_episode()

    def shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self._flush_episode()
        n = len(self._steer)
        if n == 0:
            print(f"[bc-recorder] 无数据,不落卡({self.out_dir})")
            return
        montage, img_std_last = "(跳过)", float("nan")
        meta = np.zeros((0, 1), np.float32)
        try:
            ds = load_dataset(self.out_dir)  # 回读自证文件可读(D2 同款消费口径)
            meta = ds["meta"]
            montage = make_montage(ds["image"],
                                   os.path.join(self.out_dir, "montage.jpg"))
            img_std_last = float(np.asarray(ds["image"][-300:], np.float32).std())
        except Exception as e:  # noqa: BLE001 —— 落卡失败不应阻断 drive 收尾
            montage = f"(失败: {e})"
        fps = n / max(time.perf_counter() - self._t0, 1e-6)
        montage_name = (os.path.basename(montage)
                        if isinstance(montage, str) and montage.endswith(".jpg")
                        else montage)
        card = compute_data_card(
            steer=np.asarray(self._steer), throttle=np.asarray(self._thr),
            brake=np.asarray(self._brake), meta=meta,
            img_std_samples=self._img_std_samples, img_std_last_shard=img_std_last,
            fps_measured=round(fps, 2), dropped_frames=self._skipped_stale,
            disconnects=0, spawn_points=[],
            extra={"source": "web_drive",
                   "skipped_stale_ticks": self._skipped_stale,
                   "state_defect_ticks": self._defect_ticks,
                   "montage": montage_name,
                   "recorded_at": time.strftime("%F %T")})
        dump_card(self.out_dir, card)
        print(f"[bc-recorder] {n} 帧 / {card['episodes']} 局 → {self.out_dir}")
        print(f"[bc-recorder] 门判定:{card['gates']}")
        print(f"[bc-recorder] hard gates 全过:{card['gates_pass_all_hard']}")

    # ------------------------------------------------------------------

    def _flush_episode(self) -> None:
        write_episode_npz(self.out_dir, self._buf)
        if len(self._buf):
            print(f"[bc-recorder] ep{self._buf.ep_id} 落盘({len(self._buf)} 帧)")
        self._ep_index += 1
        self._buf = EpisodeBuffer(self._ep_index)
        self._frames_ep = 0
