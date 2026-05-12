import axios from 'axios';

const DEFAULT_API_BASE = '/api';
const RAW_API_BASE = import.meta.env.VITE_API_BASE_URL?.trim();
export const API_URL = RAW_API_BASE && RAW_API_BASE.length > 0 ? RAW_API_BASE.replace(/\/$/, '') : DEFAULT_API_BASE;

export const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const loadConfig = async (path: string) => {
  const response = await api.post('/config/load', { path });
  return response.data;
};

export const selectDirectory = async () => {
  const response = await api.get('/config/select_directory');
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

export const getImageUrl = (path: string) => {
  return `${API_URL}/tub/image?path=${encodeURIComponent(path)}`;
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
