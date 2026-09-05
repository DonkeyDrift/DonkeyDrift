"""AI 清理引擎：识别 tub 中「碰撞后倒车」的有害数据片段（issue #373）。

识别器独立成模块，当前实现为可解释的启发式规则引擎
（``CollisionReverseHeuristic``），以后可以直接换成模型推理实现——
只要提供同样的 ``detect(records) -> List[CleanSegment]`` 接口即可。

识别思路（纯规则、阈值均为可调常量，见 ``AiCleanConfig``）：

1. 先找「倒车段」：连续多帧油门为负（<= reverse_throttle_max）且长度
   >= min_reverse_frames；
2. 再要求倒车段之前紧邻「碰撞特征」——两种形态：
   - 急停后倒车（stop_then_reverse）：倒车起点前 collision_lookback_frames
     范围内存在一个急停帧（|油门| <= stop_throttle_max），且急停前
     drop_window_frames 内有正向行驶（>= forward_throttle_min）；
   - 直接坠入倒车（plunge_reverse）：倒车起点前 drop_window_frames 内
     就是正向行驶（前进直接被打成倒车，中间没有停稳过程）；
3. 片段边界由碰撞点向前 pre_pad_frames、倒车段尾向后 post_pad_frames
   适度扩展，把碰撞瞬间与起步恢复一并圈进待删范围；
4. 同一会话内重叠/相邻（<= merge_gap_frames）的片段合并为一段。

「纯倒车」（起步直接倒车，前方无正向行驶）与「正常行驶」不会产生任何
片段；录制会话（_session_id）边界会重置状态，跨会话不关联、不合并。
"""

import logging
from dataclasses import dataclass, field
from itertools import groupby
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class AiCleanConfig:
    """识别阈值（帧数按录制频率折算，实车 ~20Hz / 模拟器 ~60Hz）。"""

    # 视为正向行驶的最小油门
    forward_throttle_min: float = 0.15
    # 视为停稳的最大 |油门|
    stop_throttle_max: float = 0.05
    # 视为倒车的最大油门（负值）
    reverse_throttle_max: float = -0.05
    # 碰撞特征的回看窗口（急停前 / 坠入前须在此窗口内出现正向行驶）
    drop_window_frames: int = 5
    # 碰撞点距倒车起点最多相隔的帧数（驾驶员反应时间，~2s@20Hz）
    collision_lookback_frames: int = 40
    # 倒车段最短持续帧数，过滤误触
    min_reverse_frames: int = 3
    # 片段边界向前/向后扩展帧数
    pre_pad_frames: int = 5
    post_pad_frames: int = 5
    # 同一会话内间隔小于等于该帧数的相邻片段合并为一段
    merge_gap_frames: int = 10


@dataclass
class CleanSegment:
    """一段待删除的「碰撞后倒车」片段（索引均为物理 _index）。"""

    start_index: int
    end_index: int
    frame_count: int
    indexes: List[int] = field(default_factory=list)
    reason_code: str = "collision_reverse"  # stop_then_reverse / plunge_reverse
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_index": self.start_index,
            "end_index": self.end_index,
            "frame_count": self.frame_count,
            "indexes": self.indexes,
            "reason_code": self.reason_code,
            "detail": self.detail,
        }


def _throttle_of(record: Dict[str, Any]) -> Optional[float]:
    """取记录油门：优先 user/throttle，其次 pilot/throttle；非数值返回 None。"""
    for key in ("user/throttle", "pilot/throttle"):
        value = record.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


class CollisionReverseHeuristic:
    """启发式「碰撞后倒车」识别器（规则引擎，可被模型实现替换）。"""

    def __init__(self, config: AiCleanConfig = AiCleanConfig()):
        self.config = config

    def detect(self, records: Iterable[Dict[str, Any]]) -> List[CleanSegment]:
        """对一批记录（catalog 顺序的存活记录）识别待删片段。

        按 _session_id 分段逐段识别，会话边界不传递状态；不同会话的
        物理 _index 区间不相交，结果直接按起点升序拼接。
        """
        segments: List[CleanSegment] = []
        ordered = list(records)
        for _, group in groupby(
            ordered, key=lambda r: str(r.get("_session_id", ""))
        ):
            segments.extend(self._detect_session(list(group)))
        segments.sort(key=lambda s: s.start_index)
        return segments

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _detect_session(self, records: List[Dict[str, Any]]) -> List[CleanSegment]:
        cfg = self.config
        # (物理 _index, 油门或 None) 序列，位置空间与 records 下标一致
        seq: List[Tuple[int, Optional[float]]] = [
            (int(r.get("_index", pos)), _throttle_of(r))
            for pos, r in enumerate(records)
        ]
        n = len(seq)
        if n == 0:
            return []

        def is_forward(v: Optional[float]) -> bool:
            return v is not None and v >= cfg.forward_throttle_min

        def is_stop(v: Optional[float]) -> bool:
            return v is not None and abs(v) <= cfg.stop_throttle_max

        def is_reverse(v: Optional[float]) -> bool:
            return v is not None and v <= cfg.reverse_throttle_max

        # 1. 连续倒车段 [r0, r1]（位置空间），长度须达到 min_reverse_frames
        runs: List[Tuple[int, int]] = []
        i = 0
        while i < n:
            if is_reverse(seq[i][1]):
                j = i
                while j + 1 < n and is_reverse(seq[j + 1][1]):
                    j += 1
                if j - i + 1 >= cfg.min_reverse_frames:
                    runs.append((i, j))
                i = j + 1
            else:
                i += 1

        # 2. 每个倒车段须能找到前置碰撞特征，否则视为「纯倒车」跳过；
        #    命中后按 pad 扩展为位置区间 (start, end, kind, anchor, r0, r1)
        spans: List[Tuple[int, int, str, int, int, int]] = []
        for r0, r1 in runs:
            anchor: Optional[int] = None
            kind = ""
            lookback_lo = max(0, r0 - cfg.collision_lookback_frames)
            # 形态一：急停后倒车——倒车起点前最近的停稳帧，回溯到该段
            # 连续停稳区间的首帧（碰撞瞬间），且停稳前有正向行驶
            for s in range(r0 - 1, lookback_lo - 1, -1):
                if is_stop(seq[s][1]):
                    # 回溯不越过 lookback 窗口：停稳区间比窗口还长说明
                    # 碰撞发生得太早，与本次倒车不再关联
                    while s - 1 >= lookback_lo and is_stop(seq[s - 1][1]):
                        s -= 1
                    w0 = max(0, s - cfg.drop_window_frames)
                    if any(is_forward(seq[k][1]) for k in range(w0, s)):
                        anchor, kind = s, "stop_then_reverse"
                    break
            # 形态二：直接坠入倒车——倒车起点前紧邻正向行驶
            if anchor is None:
                w0 = max(0, r0 - cfg.drop_window_frames)
                if any(is_forward(seq[k][1]) for k in range(w0, r0)):
                    anchor, kind = r0, "plunge_reverse"
            if anchor is None:
                continue

            start = max(0, anchor - cfg.pre_pad_frames)
            end = min(n - 1, r1 + cfg.post_pad_frames)
            spans.append((start, end, kind, anchor, r0, r1))

        # 3. 位置空间内合并重叠/相邻区间（间隙帧一并圈入），再生成片段；
        #    合并后 anchor/r0 取最早（首个碰撞点），r1 取最晚（倒车段尾）
        spans.sort(key=lambda s: s[0])
        merged: List[Tuple[int, int, str, int, int, int]] = []
        for span in spans:
            if merged and span[0] <= merged[-1][1] + cfg.merge_gap_frames:
                prev = merged[-1]
                merged[-1] = (prev[0], max(prev[1], span[1]), prev[2],
                              prev[3], prev[4], max(prev[5], span[5]))
            else:
                merged.append(span)

        segments: List[CleanSegment] = []
        for start, end, kind, anchor, r0, r1 in merged:
            w0 = max(0, anchor - cfg.drop_window_frames)
            forward_vals = [
                seq[k][1] for k in range(w0, anchor) if is_forward(seq[k][1])
            ]
            segments.append(
                CleanSegment(
                    start_index=seq[start][0],
                    end_index=seq[end][0],
                    frame_count=end - start + 1,
                    indexes=[seq[k][0] for k in range(start, end + 1)],
                    reason_code=kind,
                    detail={
                        "collision_index": seq[anchor][0],
                        "reverse_start_index": seq[r0][0],
                        "reverse_frames": r1 - r0 + 1,
                        "peak_forward_throttle": round(max(forward_vals), 3)
                        if forward_vals
                        else None,
                    },
                )
            )
        return segments
