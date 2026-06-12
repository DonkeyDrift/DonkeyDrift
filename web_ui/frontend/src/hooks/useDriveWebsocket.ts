import { useEffect, useRef, useState, useCallback } from 'react';
import { createDriveClientId, getDriveCarWebSocketUrl } from '../services/api';

export interface CarState {
  online: boolean;
  driveMode: 'user' | 'local_angle' | 'local';
  recording: boolean;
  numRecords: number;
}

export interface WebRtcSignal {
  type: 'webrtc_signal';
  signal_type: 'offer' | 'answer' | 'ice';
  session_id: string;
  sdp?: string;
  description_type?: 'offer' | 'answer';
  candidate?: RTCIceCandidateInit;
}

interface UseDriveWebsocketOptions {
  autoReconnect?: boolean;
  reconnectInterval?: number;
  onWebRtcSignal?: (signal: WebRtcSignal) => void;
  clientId?: string;
}

export const useDriveWebsocket = (options: UseDriveWebsocketOptions = {}) => {
  const { autoReconnect = true, reconnectInterval = 3000, onWebRtcSignal, clientId } = options;
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const clientIdRef = useRef(clientId ?? createDriveClientId());
  const mountedRef = useRef(false);
  const closingRef = useRef(false);

  const [connected, setConnected] = useState(false);
  const [carState, setCarState] = useState<CarState>({
    online: false,
    driveMode: 'user',
    recording: false,
    numRecords: 0,
  });

  const wsUrl = `${getDriveCarWebSocketUrl(clientIdRef.current)}&role=client`;

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
        if (wsRef.current !== ws || !mountedRef.current) return;
        setConnected(true);
        // 页面刷新后激活后端的模拟器自动恢复任务
        try {
          ws.send(JSON.stringify({ type: 'activate_sim_recovery' }));
        } catch {
          // ignore
        }
        // 心跳 5s 一次，更快感知断线与车端上线
        heartbeatTimerRef.current = setInterval(() => {
          if (wsRef.current === ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'heartbeat' }));
          }
        }, 5000);
      };

      ws.onmessage = (event) => {
        if (wsRef.current !== ws || !mountedRef.current) return;
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
          if (msg.type === 'webrtc_signal') {
            onWebRtcSignal?.(msg as WebRtcSignal);
          }
        } catch {
          // 忽略格式错误的消息
        }
      };

      ws.onclose = () => {
        if (wsRef.current !== ws || !mountedRef.current) return;
        setConnected(false);
        setCarState((prev) => ({ ...prev, online: false }));
        clearTimers();
        if (autoReconnect && !closingRef.current) {
          reconnectTimerRef.current = setTimeout(connect, reconnectInterval);
        }
      };

      ws.onerror = () => {
        if (wsRef.current !== ws || !mountedRef.current) return;
        ws.close();
      };
    } catch {
      setConnected(false);
      if (autoReconnect) {
        reconnectTimerRef.current = setTimeout(connect, reconnectInterval);
      }
    }
  }, [wsUrl, autoReconnect, reconnectInterval, onWebRtcSignal]);

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
    mountedRef.current = true;
    closingRef.current = false;
    connect();
    return () => {
      mountedRef.current = false;
      closingRef.current = true;
      clearTimers();
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify({ type: 'deactivate_sim_recovery' }));
        } catch {
          // ignore
        }
      }
      wsRef.current = null;
      if (ws) {
        ws.close();
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
