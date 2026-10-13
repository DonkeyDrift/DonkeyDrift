import time


class SteeringSmoother:
    """转向通道平滑：EMA 低通 + slew-rate 限幅。

    滤掉上游瞬时跳变（虚拟摇杆微释放拍零、控制链路抖动造成的单帧毛刺），
    避免转向阶跃直达执行器/模拟器引发车身弹跳。
    None 直通（上游未就绪时不污染状态）。
    """

    def __init__(self, alpha=0.35, slew_per_sec=8.0):
        # EMA 系数：越大越跟手，越小越平滑。60Hz 下 0.35 ≈ 31ms 时间常数
        self.alpha = float(alpha)
        # 变化率上限（满量程/秒）：8.0 = 从左满打到右满打最快 250ms
        self.slew_per_sec = float(slew_per_sec)
        self.value = 0.0
        self.initialized = False
        self._last_ts = None

    def run(self, angle):
        if angle is None:
            return angle
        now = time.time()
        if not self.initialized:
            self.value = float(angle)
            self.initialized = True
            self._last_ts = now
            return self.value
        dt = now - self._last_ts
        self._last_ts = now
        if self.alpha >= 1.0:
            v = float(angle)
        else:
            v = self.alpha * angle + (1.0 - self.alpha) * self.value
        if self.slew_per_sec > 0.0:
            max_delta = self.slew_per_sec * max(dt, 1e-3)
            delta = v - self.value
            if delta > max_delta:
                v = self.value + max_delta
            elif delta < -max_delta:
                v = self.value - max_delta
        self.value = v
        return v

    def shutdown(self):
        pass
