import axios from 'axios';

const DEFAULT_API_BASE = '/api';
const RAW_API_BASE = import.meta.env.VITE_API_BASE_URL?.trim();
export const API_URL = RAW_API_BASE && RAW_API_BASE.length > 0 ? RAW_API_BASE.replace(/\/$/, '') : DEFAULT_API_BASE;

export type DriveVideoTransport = 'auto' | 'webrtc' | 'mjpeg';

export const getDriveVideoTransport = (): DriveVideoTransport => {
  const value = import.meta.env.VITE_DRIVE_VIDEO_TRANSPORT?.trim().toLowerCase();
  return value === 'webrtc' || value === 'mjpeg' ? value : 'auto';
};

export const createDriveClientId = (): string => {
  const key = 'donkeydrifter_drive_client_id';
  try {
    const existing = window.sessionStorage.getItem(key);
    if (existing) {
      return existing;
    }
    const created = crypto.randomUUID();
    window.sessionStorage.setItem(key, created);
    return created;
  } catch {
    return crypto.randomUUID();
  }
};

export const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const getDriveCarWebSocketUrl = (clientId?: string) => {
  const apiBase = API_URL.replace(/\/$/, '');
  const query = clientId ? `?client_id=${encodeURIComponent(clientId)}` : '';
  if (apiBase.startsWith('http://') || apiBase.startsWith('https://')) {
    return `${apiBase.replace(/^http/, 'ws')}/drive/ws${query}`;
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.hostname;
  const backendPort = window.location.port === '5188' ? '8000' : window.location.port;
  const port = backendPort ? `:${backendPort}` : '';
  return `${protocol}//${host}${port}${apiBase}/drive/ws${query}`;
};

export const getApiErrorMessage = (error: unknown, fallback = '未知错误') => {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    return typeof detail === 'string' ? detail : error.message || fallback;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return fallback;
};

export const loadConfig = async (path: string) => {
  const response = await api.post('/config/load', { path });
  return response.data;
};

export const loadMyconfig = async (path: string) => {
  const response = await api.post('/config/load_myconfig', { path });
  return response.data;
};

export const saveTrainingConfig = async (payload: {
  path: string;
  enabled: boolean;
  config: Record<string, string | number | boolean>;
}) => {
  const response = await api.post('/config/save_training', payload);
  return response.data;
};

export const selectDirectory = async () => {
  const response = await api.get('/config/select_directory');
  return response.data;
};

export const browseDirectory = async (path?: string) => {
  const response = await api.get('/config/browser', { params: { path } });
  return response.data;
};

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

export const getImageUrl = (path: string, tubPath?: string) => {
  let url = `${API_URL}/tub/image?path=${encodeURIComponent(path)}`;
  if (tubPath) {
    url += `&tubPath=${encodeURIComponent(tubPath)}`;
  }
  return url;
};

// ------------------------------------------------------------------
// Trainer APIs
// ------------------------------------------------------------------
export interface TrainerConfig {
  host: string;
  user: string;
  password: string;
  remote_dir_base: string;
  model_name: string;
  python_path: string;
}

export const getTrainerConfig = async (configFile = 'train_online.conf') => {
  const response = await api.get('/trainer/config', { params: { config_file: configFile } });
  return response.data;
};

export const setTrainerConfig = async (cfg: TrainerConfig, configFile = 'train_online.conf') => {
  const response = await api.post('/trainer/config', cfg, { params: { config_file: configFile } });
  return response.data;
};

export const listModels = async (workingDir?: string) => {
  const response = await api.get('/trainer/models', { params: workingDir ? { working_dir: workingDir } : {} });
  return response.data;
};

export const downloadModelUrl = (path: string): string => {
  return `${API_URL}/trainer/models/download?path=${encodeURIComponent(path)}`;
};

export const deleteModel = async (path: string) => {
  const response = await api.delete('/trainer/models', { params: { path } });
  return response.data;
};

export const loadModelToCar = async (modelPath: string, workingDir?: string) => {
  const response = await api.post('/drive/load_model', { model_path: modelPath, working_dir: workingDir });
  return response.data;
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

export const createDriveWebRtcSession = async (clientId: string = crypto.randomUUID()) => {
  const response = await api.post('/drive/webrtc/session', { client_id: clientId });
  return response.data as { success: boolean; session_id: string; single_client: boolean };
};

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

export const sendCalibrate = async (params: Record<string, number | boolean>) => {
  const response = await api.post('/drive/calibrate', params);
  return response.data;
};

export const listBackups = async (workingDir?: string) => {
  const response = await api.get('/trainer/backups', { params: workingDir ? { working_dir: workingDir } : {} });
  return response.data;
};

export const startLocalTrain = async (params: {
  tub: string;
  model: string;
  model_type: string;
  transfer?: string;
  working_dir?: string;
}) => {
  const response = await api.post('/trainer/train/local', params);
  return response.data;
};

export const startOnlineTrain = async (params: {
  config_file?: string;
  working_dir?: string;
}) => {
  const response = await api.post('/trainer/train/online', params);
  return response.data;
};

export const stopTrain = async (jobId: string) => {
  const response = await api.post(`/trainer/train/${jobId}/stop`);
  return response.data;
};

export const getJobStatus = async (jobId: string) => {
  const response = await api.get(`/trainer/train/${jobId}/status`);
  return response.data;
};

export const createLogStream = (jobId: string) => {
  return new EventSource(`${API_URL}/trainer/train/${jobId}/logs`);
};

// ------------------------------------------------------------------
// Car Connector APIs
// ------------------------------------------------------------------
export interface ConnectorConfig {
  host: string;
  user: string;
  port: number;
  car_dir: string;
  key_path?: string | null;
}

export type ConnectorJobState = 'pending' | 'running' | 'completed' | 'failed' | 'stopped';

export interface ConnectorJobStatus {
  id: string;
  kind: string;
  status: ConnectorJobState;
  progress: number;
  logs: string[];
  error?: string | null;
  started_at: string;
  finished_at?: string | null;
}

export const getConnectorConfig = async () => {
  const response = await api.get('/connector/config');
  return response.data as { config: ConnectorConfig };
};

export const setConnectorConfig = async (config: ConnectorConfig) => {
  const response = await api.post('/connector/config', config);
  return response.data as { config: ConnectorConfig };
};

export const checkConnectorStatus = async () => {
  const response = await api.post('/connector/status');
  return response.data as { online: boolean; message: string };
};

export const listConnectorTubs = async () => {
  const response = await api.get('/connector/remote/tubs');
  return response.data as { items: string[] };
};

export const listConnectorModels = async () => {
  const response = await api.get('/connector/remote/models');
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

export const pushConnectorPilots = async (payload: {
  local_models_path: string;
  formats: string[];
  car_dir?: string;
}) => {
  const response = await api.post('/connector/pilots/push', payload);
  return response.data as { job_id: string; status: ConnectorJobState };
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

export const getConnectorJobStatus = async (jobId: string) => {
  const response = await api.get(`/connector/jobs/${jobId}/status`);
  return response.data as ConnectorJobStatus;
};

export const stopConnectorJob = async (jobId: string) => {
  const response = await api.post(`/connector/jobs/${jobId}/stop`);
  return response.data;
};

export const createConnectorJobStream = (jobId: string) => {
  return new EventSource(`${API_URL}/connector/jobs/${jobId}/events`);
};

// ------------------------------------------------------------------
// Pilot Arena APIs
// ------------------------------------------------------------------
export interface ArenaModel {
  name: string;
  path: string;
  format: string;
  size: number;
  modified: string;
  compatible: boolean;
}

export interface ArenaPilot {
  id: string;
  name: string;
  model_path: string;
  model_type: string;
  loaded_at: string;
}

export interface ArenaPrediction {
  status: boolean;
  record_index: number;
  user: { angle: number; throttle: number };
  pilot: { angle: number; throttle: number };
}

export interface ArenaPredictionPoint {
  index: number;
  user_angle: number;
  user_throttle: number;
  pilot_angle: number;
  pilot_throttle: number;
}

export const listArenaModelTypes = async () => {
  const response = await api.get('/arena/model-types');
  return response.data;
};

export const listArenaModels = async (params: { workingDir?: string; modelType?: string } = {}) => {
  const response = await api.get('/arena/models', {
    params: {
      ...(params.workingDir ? { working_dir: params.workingDir } : {}),
      ...(params.modelType ? { model_type: params.modelType } : {}),
    },
  });
  return response.data as { models: ArenaModel[] };
};

export const loadArenaPilot = async (payload: {
  model_path: string;
  model_type: string;
  config_path?: string;
}) => {
  const response = await api.post('/arena/pilots/load', payload);
  return response.data as { status: boolean; pilot: ArenaPilot };
};

export const unloadArenaPilot = async (pilotId: string) => {
  const response = await api.delete(`/arena/pilots/${pilotId}`);
  return response.data;
};

export const predictArenaPilot = async (pilotId: string, payload: {
  record_index: number;
  config_path?: string;
  user_angle_field?: string;
  user_throttle_field?: string;
  pre_transformations?: string[];
  augmentations?: string[];
  post_transformations?: string[];
  brightness?: number | null;
  blur?: number | null;
}) => {
  const response = await api.post(`/arena/pilots/${pilotId}/predict`, payload);
  return response.data as ArenaPrediction;
};

export const getArenaPreviewUrl = (pilotId: string, params: {
  recordIndex: number;
  configPath?: string;
  userAngleField?: string;
  userThrottleField?: string;
  preTransformations?: string[];
  augmentations?: string[];
  postTransformations?: string[];
  brightness?: number | null;
  blur?: number | null;
}) => {
  const search = new URLSearchParams({
    record_index: String(params.recordIndex),
    t: String(Date.now()),
  });
  if (params.configPath) search.set('config_path', params.configPath);
  if (params.userAngleField) search.set('user_angle_field', params.userAngleField);
  if (params.userThrottleField) search.set('user_throttle_field', params.userThrottleField);
  if (params.preTransformations?.length) search.set('pre_transformations', params.preTransformations.join(','));
  if (params.augmentations?.length) search.set('augmentations', params.augmentations.join(','));
  if (params.postTransformations?.length) search.set('post_transformations', params.postTransformations.join(','));
  if (params.brightness !== undefined && params.brightness !== null) search.set('brightness', String(params.brightness));
  if (params.blur !== undefined && params.blur !== null) search.set('blur', String(params.blur));
  return `${API_URL}/arena/pilots/${pilotId}/preview?${search.toString()}`;
};

export const getArenaPredictions = async (pilotId: string, payload: {
  config_path?: string;
  start?: number;
  limit?: number;
  user_angle_field?: string;
  user_throttle_field?: string;
  pre_transformations?: string[];
  augmentations?: string[];
  post_transformations?: string[];
  brightness?: number | null;
  blur?: number | null;
}) => {
  const response = await api.post(`/arena/pilots/${pilotId}/predictions`, payload);
  return response.data as { status: boolean; limit: number; points: ArenaPredictionPoint[] };
};

// ------------------------------------------------------------------
// Simulator Discovery APIs
// ------------------------------------------------------------------
export interface SimulatorHost {
  ip: string;
  port: number;
  latency_ms: number;
  reachable: boolean;
}

export const discoverSimulator = async (carPath?: string) => {
  const response = await api.post('/config/discover_simulator', { car_path: carPath });
  return response.data as { status: boolean; found: SimulatorHost[]; count: number; scanned: number; message: string };
};

export const saveSimulatorConfig = async (payload: {
  path: string;
  config: Record<string, string | number | boolean>;
}) => {
  const response = await api.post('/config/save_simulator', payload);
  return response.data as { status: boolean; message: string };
};
