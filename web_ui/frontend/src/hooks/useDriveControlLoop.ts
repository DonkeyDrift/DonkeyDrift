import { useEffect, useRef } from 'react';

export interface DriveControlPayload extends Record<string, unknown> {
  angle: number;
  throttle: number;
  drive_mode: string;
  recording?: boolean;
}

interface UseDriveControlLoopOptions {
  connected: boolean;
  send: (payload: Record<string, unknown>) => boolean;
  getControl: () => DriveControlPayload;
  intervalMs?: number;
}

const CONTROL_INTERVAL_MS = 1000 / 60;

export const useDriveControlLoop = ({
  connected,
  send,
  getControl,
  intervalMs = CONTROL_INTERVAL_MS,
}: UseDriveControlLoopOptions) => {
  const getControlRef = useRef(getControl);

  useEffect(() => {
    getControlRef.current = getControl;
  }, [getControl]);

  useEffect(() => {
    if (!connected) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      // 后台页签暂停发送：挂着不动的页签不再以 60Hz 发 0 抢占驾驶权
      // （后端多客户端仲裁的配合措施）
      if (document.hidden) return;
      send(getControlRef.current());
    }, intervalMs);

    return () => window.clearInterval(timer);
  }, [connected, intervalMs, send]);
};
