// drivehooks namespace: zh values mirror the current UI strings verbatim (the
// "Chinese interface" is exactly today's mixed zh/en UI); en values are the
// full English translation of every entry.
export const drivehooks: { zh: Record<string, string>; en: Record<string, string> } = {
  zh: {
    'driveHooks.webRtcConnectFailed': 'WebRTC 视频连接失败',
    'driveHooks.setAnswerFailed': '设置 WebRTC answer 失败',
    'driveHooks.addIceCandidateFailed': '添加 ICE candidate 失败',
  },
  en: {
    'driveHooks.webRtcConnectFailed': 'WebRTC video connection failed',
    'driveHooks.setAnswerFailed': 'Failed to set WebRTC answer',
    'driveHooks.addIceCandidateFailed': 'Failed to add ICE candidate',
  },
};
