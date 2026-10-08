/**
 * Tub & Records API 客户端。
 *
 * 从 api.ts 抽取的 Tub 会话、记录、AI 清洗接口。
 */

import { api, API_URL, getApiErrorMessage } from "./api"
import type { ConnectorJobState } from "./api";
import { generateUuid } from "./api";

export const loadTub = async (path: string) => {
  const response = await api.post('/tub/load', { path });
  return response.data;
};

export const getRecords = async (offset = 0, limit = 100) => {
  const response = await api.get('/tub/records', { params: { offset, limit } });
  return response.data;
};

export const deleteRecords = async (indexes: number[]) => {
  const response = await api.post('/tub/delete', { indexes });
  return response.data;
};

export const restoreRecords = async (indexes: number[]) => {
  const response = await api.post('/tub/restore', { indexes });
  return response.data;
};

export interface TubSession {
  session_id: string;
  record_count: number;
  first_index: number;
  last_index: number;
  start_time_ms: number | null;
  end_time_ms: number | null;
}

export interface TubRecord {
  [key: string]: unknown;
  _index?: number;
  _session_id?: string;
  _timestamp_ms?: number;
}

export const listTubSessions = async (tubPath: string) => {
  const response = await api.get('/tub/sessions', { params: { tubPath } });
  return response.data as { status: boolean; path: string; sessions: TubSession[] };
};

export const getSessionRecords = async (tubPath: string, sessionId: string) => {
  const response = await api.get('/tub/session_records', {
    params: { tubPath, sessionId },
  });
  return response.data as { status: boolean; path: string; records: TubRecord[] };
};

export const deleteTubSession = async (tubPath: string, sessionId: string) => {
  const response = await api.post('/tub/delete_session', {
    tub_path: tubPath,
    session_id: sessionId,
  });
  return response.data as {
    status: boolean;
    message: string;
    deleted_count: number;
    record_count: number | null;
    deleted_indexes: number[] | null;
  };
};

export const getImageUrl = (path: string, tubPath?: string) => {
  let url = `${API_URL}/tub/image?path=${encodeURIComponent(path)}`;
  if (tubPath) {
    url += `&tubPath=${encodeURIComponent(tubPath)}`;
  }
  return url;
};

// ------------------------------------------------------------------
// AI Clean APIs（AI 一键批量清理「碰撞后倒车」数据，issue #373）
// ------------------------------------------------------------------

export interface AiCleanCandidate {
  path: string;
  name: string;
  is_current: boolean;
}

export interface AiCleanSegment {
  start_index: number;
  end_index: number;
  frame_count: number;
  indexes: number[];
  reason_code: 'stop_then_reverse' | 'plunge_reverse' | string;
  detail: {
    collision_index?: number | null;
    reverse_start_index?: number | null;
    reverse_frames?: number | null;
    peak_forward_throttle?: number | null;
  };
}

export interface AiCleanTubScan {
  tub_path: string;
  record_count?: number;
  segments?: AiCleanSegment[];
  segment_count?: number;
  frame_count?: number;
  error?: string;
}

export interface AiCleanExecuteResult {
  tub_path: string;
  deleted_count?: number;
  error?: string;
}

export const listAiCleanCandidates = async (tubPath: string) => {
  const response = await api.get('/tub/ai_clean/candidates', { params: { tubPath } });
  return response.data as { status: boolean; current: string; tubs: AiCleanCandidate[] };
};

export const scanAiClean = async (tubPaths: string[], sessionId?: string | null) => {
  const response = await api.post('/tub/ai_clean/scan', {
    tub_paths: tubPaths,
    ...(sessionId ? { session_id: sessionId } : {}),
  });
  return response.data as {
    status: boolean;
    tubs: AiCleanTubScan[];
    total_segments: number;
    total_frames: number;
  };
};

export const executeAiClean = async (
  deletions: { tub_path: string; indexes: number[] }[],
) => {
  const response = await api.post('/tub/ai_clean/execute', { deletions });
  return response.data as {
    status: boolean;
    results: AiCleanExecuteResult[];
    total_deleted: number;
    record_count: number | null;
    deleted_indexes: number[] | null;
  };
};

// ------------------------------------------------------------------
// Trainer APIs
// ------------------------------------------------------------------

export const createDriveWebRtcSession = async (clientId: string = generateUuid()) => {
  const response = await api.post('/drive/webrtc/session', { client_id: clientId });
  return response.data as { success: boolean; session_id: string; single_client: boolean };
};

export const listConnectorTubs = async () => {
  const response = await api.get('/connector/remote/tubs');
  return response.data as { items: string[] };
};

export const pullConnectorTub = async (payload: {
  remote_tub: string;
  local_data_path: string;
  create_new_dir: boolean;
  car_dir?: string;
}) => {
  const response = await api.post('/connector/tub/pull', payload);
  return response.data as { job_id: string; status: ConnectorJobState };
};

