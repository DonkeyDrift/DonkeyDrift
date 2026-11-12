/** 本地输入源（joystick/keyboard/gamepad/gyro）停摆判定阈值（#508）。
 * 各输入 hook 以约 60Hz 连续上报（值不变也上报，见各 hook 的心跳说明），
 * 超过该间隔未更新视为源停摆（section 滚出视口后 hook 停摆 #178、手柄断连、
 * 键盘 blur 等），mux 输出 0，不沿用冻结的旧油门/转向。 */
export const LOCAL_INPUT_STALE_MS = 300;

export interface InputControlValue {
  angle: number;
  throttle: number;
  updatedAt: number;
}

/**
 * 输入源新鲜度检查：fresh 时原样透传，stale 时输出 0（与 esp32 遥测断流
 * 的 ESP32_RC_STALE_MS 检查同款语义）。now/staleMs 可注入便于测试。
 */
export const freshControl = (
  value: InputControlValue,
  now: number = Date.now(),
  staleMs: number = LOCAL_INPUT_STALE_MS,
): { angle: number; throttle: number } => {
  if (now - value.updatedAt <= staleMs) {
    return { angle: value.angle, throttle: value.throttle };
  }
  return { angle: 0, throttle: 0 };
};
