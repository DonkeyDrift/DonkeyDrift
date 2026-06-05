import { useEffect, useRef, useState, useCallback } from 'react';
import { API_URL } from '../services/api';

export interface CarState {
  online: boolean;
  driveMode: 'user' | 'local_angle' | 'local';
  recording: boolean;
  numRecords: number;
}

interface UseDriveWebsocketOptions {
  autoReconnect?: boolean;
  reconnectInterval?: number;
}

export const useDriveWebsocket = (options: UseDriveWebsocketOptions = {}) => {
  const { autoReconnect = true, reconnectInterval = 3000 } = options;
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [connected, setConnected] = useState(false);
  const [carState, setCarState] = useState<CarState>({
    online: false,
    driveMode: 'user',
    recording: false,
    numRecords: 0,
  });

  const wsUrl = `${API_URL.replace(/^http/, 'ws')}/drive/ws?role=client`;

  const clearTimers = () => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (heartbeatTimerRef.current) {
      clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
  };

  const connect = useCallback(() => {
    clearTimers();

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        // 心跳 15s 一次
        heartbeatTimerRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'heartbeat' }));
          }
        }, 15000);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'car_connection') {
            setCarState((prev) => ({ ...prev, online: !!msg.online }));
          }
          if (msg.type === 'car_state') {
            setCarState((prev) => ({
              ...prev,
              driveMode: msg.drive_mode ?? prev.driveMode,
              recording: !!msg.recording,
              numRecords: Number(msg.num_records) || 0,
            }));
          }
        } catch {
          // 忽略格式错误的消息
        }
      };

      ws.onclose = () => {
        setConnected(false);
        setCarState((prev) => ({ ...prev, online: false }));
        clearTimers();
        if (autoReconnect) {
          reconnectTimerRef.current = setTimeout(connect, reconnectInterval);
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      setConnected(false);
      if (autoReconnect) {
        reconnectTimerRef.current = setTimeout(connect, reconnectInterval);
      }
    }
  }, [wsUrl, autoReconnect, reconnectInterval]);

  const send = useCallback((data: Record<string, unknown>) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      return false;
    }
    try {
      wsRef.current.send(JSON.stringify(data));
      return true;
    } catch {
      return false;
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      clearTimers();
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  return {
    connected,
    carState,
    send,
    reconnect: connect,
  };
};
