import { create } from 'zustand';
import type { Telemetry } from '../hooks/useDriveWebsocket';

/**
 * 100Hz 遥测的「旁路」通道（#135 第八轮）。
 *
 * 车端遥测以 ~100Hz 上报，若像之前那样在 DrivePage 用 `setTelemetry` 存成 state，
 * 会让整个 DrivePage（视频流、两张曲线图、摇杆抽屉、参数面板等）每秒重渲染 100 次，
 * 把主线程占满，点击顶栏导航（如 Donkey / Drifter Console）时事件被饿死，表现为
 * “点了很久才动、一动就瞬跳”。
 *
 * 这里把遥测推进一个不触发 React 重渲染的 store：曲线图用 `subscribe` 自行订阅并
 * 按 10fps 节流重绘；DrivePage 只把 rc_mode/rc_park 这类低频字段在“值变化”时才
 * 落一次 state。这样 100Hz 遥测不再驱动整页重渲染。
 */
interface TelemetryStore {
  /** 最新一帧遥测（仅供 subscribe / getState 读取，不做 selector 订阅）。 */
  latest: Telemetry | null;
  /** 推入新一帧遥测（不触发组件重渲染，仅通知订阅者）。 */
  push: (t: Telemetry) => void;
  /** 清空最新帧（测试/复位用）。 */
  reset: () => void;
}

export const useTelemetryStore = create<TelemetryStore>((set) => ({
  latest: null,
  push: (t) => set({ latest: t }),
  reset: () => set({ latest: null }),
}));
