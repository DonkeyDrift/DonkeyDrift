/**
 * Drive API 客户端。
 *
 * 从 api.ts 抽取的驾驶视频传输、WebSocket、控制接口。
 */

import { api, API_URL, getApiErrorMessage } from "./api"
import type { ConnectorJobState } from "./api";

export type DriveVideoTransport = 'auto' | 'webrtc' | 'mjpeg';

export const getDriveVideoTransport = (): DriveVideoTransport => {
  const value = import.meta.env.VITE_DRIVE_VIDEO_TRANSPORT?.trim().toLowerCase();
  return value === 'webrtc' || value === 'mjpeg' ? value : 'auto';
};

/**
 * 生成 UUID v4，兼容非安全上下文（HTTP + 非 localhost）。
 * crypto.randomUUID() 仅在 secure context（HTTPS 或 localhost）下可用，
 * 通过局域网 IP 访问时需回退到 crypto.getRandomValues()。
 */
const generateUuid = (): string => {
  if (typeof crypto?.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, '0'));
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`;
};

export const createDriveClientId = (): string => {
  const key = 'donkeydrifter_drive_client_id';
  try {
    const existing = window.sessionStorage.getItem(key);
    if (existing) {
      return existing;
    }
    const created = generateUuid();
    window.sessionStorage.setItem(key, created);
    return created;
  } catch {
    return generateUuid();
  }
};

export const getDriveCarWebSocketUrl = (clientId?: string) => {
  const apiBase = API_URL.replace(/\/$/, '');
  const query = clientId ? `?client_id=${encodeURIComponent(clientId)}` : '';
  // 显式指定了 http(s) 后端地址（VITE_API_BASE_URL）：直接用，把 http 换成 ws
  if (apiBase.startsWith('http://') || apiBase.startsWith('https://')) {
    return `${apiBase.replace(/^http/, 'ws')}/drive/ws${query}`;
  }
  // 未显式指定：用相对 /api 路径，走 Vite 代理（vite.config.ts 的 ws:true 转发到后端）。
  // 这样浏览器 ws 连自身端口的 /api/drive/ws，由 Vite 代理转给 --backend-port 选定的后端，
  // 不再硬编码 8000，与 donkey web --backend-port 联动一致。
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host; // hostname:port（含 dev 服务器端口）
  return `${protocol}//${host}${apiBase}/drive/ws${query}`;
};

export interface DriveWebRtcStats {
  active: boolean;
  session_id: string | null;
  webrtc_available: boolean;
  source_fps: number;
  sent_fps: number;
  browser_fps: number;
  browser_p95_frame_interval_ms: number;
  disconnect_count: number;
  stale_frames?: number;
  peer_connection_state?: string | null;
  ice_connection_state?: string | null;
  ice_gathering_state?: string | null;
  local_description_error?: string | null;
  local_description_elapsed_ms?: number | null;
  answer_sent_elapsed_ms?: number | null;
  local_candidates_sent?: number;
  offer_to_answer_elapsed_ms?: number | null;
  inbound_fps?: number;
  frames_dropped?: number;
  jitter_ms?: number;
  jitter_buffer_delay_ms?: number;
  transport: 'webrtc' | 'mjpeg';
  degraded: boolean;
}

export const sendDriveWebRtcOffer = async (sessionId: string, sdp: string) => {
  const response = await api.post('/drive/webrtc/offer', { session_id: sessionId, sdp, type: 'offer' });
  return response.data as { success: boolean };
};

export const sendDriveWebRtcIce = async (sessionId: string, candidate: RTCIceCandidateInit) => {
  const response = await api.post('/drive/webrtc/ice', { session_id: sessionId, source: 'client', candidate });
  return response.data as { success: boolean };
};

export const sendDriveWebRtcBrowserStats = async (
  sessionId: string,
  metrics: {
    browser_fps: number;
    browser_p95_frame_interval_ms: number;
    inbound_fps?: number;
    frames_dropped?: number;
    jitter_ms?: number;
    jitter_buffer_delay_ms?: number;
  }
) => {
  const response = await api.post('/drive/webrtc/browser-stats', { session_id: sessionId, ...metrics });
  return response.data as { success: boolean };
};

export const getDriveWebRtcStats = async () => {
  const response = await api.get('/drive/webrtc/stats');
  return response.data as DriveWebRtcStats;
};

export const startConnectorDrive = async (payload: {
  model_type?: string;
  pilot?: string;
  bridge_server_url?: string;
  car_dir?: string;
}) => {
  const response = await api.post('/connector/drive/start', payload);
  return response.data as { job_id: string; status: ConnectorJobState };
};

export const stopConnectorDrive = async (payload: { pid?: number; car_dir?: string } = {}) => {
  const response = await api.post('/connector/drive/stop', payload);
  return response.data as { job_id: string; status: ConnectorJobState };
};

export const getConnectorDriveStatus = async () => {
  const response = await api.get('/connector/drive/status');
  return response.data as { pid: number | null };
};

