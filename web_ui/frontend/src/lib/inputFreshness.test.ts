import { describe, expect, it } from 'vitest';
import { freshControl, LOCAL_INPUT_STALE_MS } from './inputFreshness';

describe('freshControl（本地输入源新鲜度检查 #508）', () => {
  it('新鲜值原样透传，不误杀正常输入流', () => {
    const value = { angle: 0.4, throttle: 0.8, updatedAt: 10_000 };
    expect(freshControl(value, 10_000 + LOCAL_INPUT_STALE_MS)).toEqual({ angle: 0.4, throttle: 0.8 });
    // 恰好压线（<= 阈值）仍算新鲜
    expect(freshControl({ ...value, updatedAt: 0 }, LOCAL_INPUT_STALE_MS)).toEqual({ angle: 0.4, throttle: 0.8 });
  });

  it('停摆/断连后 ref 冻结：超过阈值即输出 0，不沿用旧油门', () => {
    const value = { angle: 0.4, throttle: 0.8, updatedAt: 10_000 };
    expect(freshControl(value, 10_000 + LOCAL_INPUT_STALE_MS + 1)).toEqual({ angle: 0, throttle: 0 });
    // 从未上报（updatedAt=0）同样输出 0
    expect(freshControl({ angle: 0, throttle: 0, updatedAt: 0 }, 1_000_000)).toEqual({ angle: 0, throttle: 0 });
  });

  it('支持自定义阈值（esp32 遥测断流用 ESP32_RC_STALE_MS 同款语义）', () => {
    const value = { angle: -0.2, throttle: 0.1, updatedAt: 0 };
    expect(freshControl(value, 400, 500)).toEqual({ angle: -0.2, throttle: 0.1 });
    expect(freshControl(value, 501, 500)).toEqual({ angle: 0, throttle: 0 });
  });
});
