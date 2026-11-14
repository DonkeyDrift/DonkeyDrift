# -*- coding: utf-8 -*-
"""模拟器帧到达时刻侧信道（进程内单例）。

DonkeyGymEnv 的 update 线程每收到一帧模拟器 obs 就记录到达时刻；同进程内的
DriveVideoFrameBuffer 读取该值，作用有二：

1. 作为帧时间戳（后续印章/RTP pts 都用它）——「模拟器出帧 → 车辆循环轮询」
   这段等待计入端到端时延口径，徽标不再虚低；
2. 按到达时刻去重——车辆循环按 DRIVE_LOOP_HZ 高频轮询同帧时不再刷新
   frame_id，source_fps/sent_fps 反映真实新帧率，旧帧不再被重复编码发送。

仅模拟器模式（进程内存在 DonkeyGymEnv）时有值；实车相机路径始终为 None，
帧缓冲回退到 update 时钟与不去重的原行为，互不影响。
"""
import time
from threading import Lock
from typing import Optional

_lock = Lock()
_arrival: Optional[float] = None


def set_source_arrival(ts: Optional[float] = None) -> float:
    """记录最近一帧模拟器 obs 的到达时刻（默认取当前时钟），返回记录值。

    单调保护：时钟回拨时保留较大值，保证去重比较与 pts 单调。
    """
    value = time.time() if ts is None else float(ts)
    with _lock:
        global _arrival
        if _arrival is not None and value < _arrival:
            value = _arrival
        _arrival = value
        return value


def get_source_arrival() -> Optional[float]:
    """返回最近到达时刻；进程内无模拟器（实车/测试）时为 None。"""
    with _lock:
        return _arrival


def reset_source_arrival() -> None:
    """清空侧信道（测试隔离用）。"""
    global _arrival
    with _lock:
        _arrival = None
