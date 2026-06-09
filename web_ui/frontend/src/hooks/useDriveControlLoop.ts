import { useEffect, useRef } from 'react';

export interface DriveControlPayload {
  angle: number;
  throttle: number;
  drive_mode: string;
  recording: boolean;
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
      send(getControlRef.current());
    }, intervalMs);

    return () => window.clearInterval(timer);
  }, [connected, intervalMs, send]);
};
