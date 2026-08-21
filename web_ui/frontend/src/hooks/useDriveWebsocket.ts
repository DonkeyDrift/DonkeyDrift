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

/**
 * 车端上报的遥测数据（曲线图用）。字段均为可选——车端只发送非 None 字段。
 * 对齐 RFC telemetry-chart-migration.md 改动1 的消息体。
 */
export interface Telemetry {
  type: 'telemetry';
  t?: number;
  gz?: number;
  gx?: number;
  gy?: number;
  ax?: number;
  ay?: number;
  az?: number;
  steering?: number;
  throttle?: number;
  pilot_angle?: number;
  pilot_throttle?: number;
  rc_steering?: number;
  rc_throttle?: number;
  /** 固件驾驶模式（0=手动/1=半自动/2=全自动），来自 M<m>:P<p> 帧 */
  rc_mode?: number;
  /** 固件 Park 手刹状态（1=锁定，油门被钳 0），来自 M<m>:P<p> 帧 */
  rc_park?: number;
}

interface UseDriveWebsocketOptions {
  autoReconnect?: boolean;
  reconnectInterval?: number;
  onWebRtcSignal?: (signal: WebRtcSignal) => void;
  onTelemetry?: (t: Telemetry) => void;
  clientId?: string;
  /** 是否启用连接（如 Drive section 滚出视口时传 false 断开，停止后台收发） */
  enabled?: boolean;
}

export const useDriveWebsocket = (options: UseDriveWebsocketOptions = {}) => {
  const { autoReconnect = true, reconnectInterval = 3000, onWebRtcSignal, onTelemetry, clientId, enabled = true } = options;
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
            setCarState((prev) => {
              const online = !!msg.online;
              if (online === prev.online) return prev;
              return { ...prev, online };
            });
          }
          if (msg.type === 'car_state') {
            setCarState((prev) => {
              const driveMode = msg.drive_mode ?? prev.driveMode;
              const recording = !!msg.recording;
              const numRecords = Number(msg.num_records) || 0;
              // 控制循环 60Hz 会让后端原样回广播 car_state；值未变时返回原引用，
              // 让 React 跳过重渲染，避免 60Hz 重渲染整个 DrivePage（#135 第八轮）。
              if (driveMode === prev.driveMode && recording === prev.recording && numRecords === prev.numRecords) {
                return prev;
              }
              return { ...prev, driveMode, recording, numRecords };
            });
          }
          if (msg.type === 'webrtc_signal') {
            onWebRtcSignal?.(msg as WebRtcSignal);
          }
          if (msg.type === 'telemetry') {
            onTelemetry?.(msg as Telemetry);
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
  }, [wsUrl, autoReconnect, reconnectInterval, onWebRtcSignal, onTelemetry]);

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
    if (!enabled) {
      // 不可见（如 Drive section 滚出视口）时主动断开：停止遥测/信令收发，
      // 避免后台持续 setState 重渲染拖慢整页（#135 收尾修复）。
      mountedRef.current = false;
      closingRef.current = true;
      clearTimers();
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws) {
        // 连接尚未建立时直接 close() 会让 Chrome 报
        // "WebSocket is closed before the connection is established"，
        // 等 onopen 后再关即可避免（StrictMode 双挂载时常见）。
        if (ws.readyState === WebSocket.CONNECTING) {
          ws.onopen = () => ws.close();
        } else {
          ws.close();
        }
      }
      setConnected(false);
      setCarState((prev) => ({ ...prev, online: false }));
      return undefined;
    }

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
        // 连接尚未建立时直接 close() 会让 Chrome 报
        // "WebSocket is closed before the connection is established"，
        // 等 onopen 后再关即可避免（StrictMode 双挂载时常见）。
        if (ws.readyState === WebSocket.CONNECTING) {
          ws.onopen = () => ws.close();
        } else {
          ws.close();
        }
      }
    };
  }, [connect, enabled]);

  return {
    connected,
    carState,
    send,
    reconnect: connect,
  };
};
