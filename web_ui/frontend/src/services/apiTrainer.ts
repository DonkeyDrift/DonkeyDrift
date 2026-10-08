/**
 * Trainer & Model API 客户端。
 *
 * 从 api.ts 抽取的训练配置、模型管理、MyPc 远程训练接口。
 */

import { api, API_URL, getApiErrorMessage } from "./api"

export const saveTrainingConfig = async (payload: {
  path: string;
  enabled: boolean;
  config: Record<string, string | number | boolean>;
}) => {
  const response = await api.post('/config/save_training', payload);
  return response.data;
};

export const downloadTubSession = (
  tubPath: string,
  sessionId: string,
  startTimeMs: number | null,
) => {
  const params = new URLSearchParams({ tubPath, sessionId });
  if (startTimeMs != null) {
    params.set('startTimeMs', String(startTimeMs));
  }
  const link = document.createElement('a');
  link.href = `${API_URL}/tub/download_session?${params.toString()}`;
  // Let the server set the filename via Content-Disposition
  link.download = '';
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
};

export interface TrainerConfig {
  host: string;
  user: string;
  remote_dir_base: string;
  model_name: string;
  python_path: string;
  /** 模型类型（linear/categorical/...），远程训练命令 --type 参数 */
  model_type?: string;
  /** SSH 私钥路径（可选，留空用密码认证） */
  key_path?: string;
}

export interface SSHCredentials {
  host?: string;
  user?: string;
  password?: string;
  key_filename?: string;
}

export const getTrainerConfig = async (configFile = 'train_online.conf') => {
  const response = await api.get('/trainer/config', { params: { config_file: configFile } });
  return response.data;
};

export const setTrainerConfig = async (cfg: TrainerConfig, configFile = 'train_online.conf') => {
  const response = await api.post('/trainer/config', cfg, { params: { config_file: configFile } });
  return response.data;
};

export interface MyPcProbeCheck {
  name: string;
  status: 'ok' | 'warn' | 'fail' | 'info';
  message: string;
  hint: string;
}

export interface MyPcProbeResult {
  ok: boolean;
  platform: string;
  shell: string;
  python_path: string;
  checks: MyPcProbeCheck[];
  suggestions: string[];
}

export const probeMyPc = async (cfg: {
  host: string;
  user: string;
  password: string;
  port?: number;
  remote_dir_base?: string;
  python_path?: string;
  key_path?: string;
}): Promise<MyPcProbeResult> => {
  const response = await api.post('/trainer/mypc/probe', cfg);
  return response.data;
};

export interface MyPcClientInfo {
  ip: string;
  is_loopback: boolean;
  hostname: string;
  username: string;
  verified: boolean;
  ssh: string; // '' | 'ok' | 'auth_failed' | 'unreachable'
}

export async function getMyPcClientInfo(password?: string): Promise<MyPcClientInfo> {
  // POST + JSON body（而非 GET query）：密码绝不进访问日志
  const response = await api.post('/trainer/mypc/client-info', {
    password: password || '',
  });
  return response.data;
}

export interface MyPcKnownHost {
  host: string;
  user: string;
  python_path: string;
  remote_dir_base: string;
  last_used_at: number;
  reachable: boolean;
  // 安全约束：历史记录不含密码，前端永远不要从这里取密码
}

export async function getMyPcKnownHosts(): Promise<MyPcKnownHost[]> {
  const response = await api.get('/trainer/mypc/known-hosts');
  return response.data.hosts;
}

export const installMyPc = async (cfg: {
  host: string;
  user: string;
  password: string;
  port?: number;
  python_path: string;
  key_path?: string;
}) => {
  const response = await api.post('/trainer/mypc/install', cfg);
  return response.data as { job_id: string; status: string };
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

// FormData 上传统一配置：显式置空 Content-Type。axios 实例默认带
// application/json，若随请求发出，后端按 JSON 解析 multipart 体会直接 422
// （「导入失败: Request failed with status code 422」）。置 null 后 axios 在
// toJSON 阶段丢弃该头，交给浏览器/XHR 按 FormData 自动生成带 boundary 的
// multipart/form-data；不能手动设成 multipart/form-data——那样会丢 boundary。
const formDataRequestConfig = {
  headers: { 'Content-Type': null },
} as const;

export const importModel = async (
  file: File,
  workingDir?: string,
  lossImage?: File,
  metaJson?: File,
) => {
  const form = new FormData();
  form.append('file', file);
  if (lossImage) {
    form.append('loss_image', lossImage);
  }
  if (metaJson) {
    form.append('meta_json', metaJson);
  }
  if (workingDir) {
    form.append('working_dir', workingDir);
  }
  const response = await api.post('/trainer/models/import', form, formDataRequestConfig);
  return response.data;
};

export const uploadModelLoss = async (
  name: string,
  workingDir?: string,
  lossImage?: File,
  metaJson?: File,
) => {
  const form = new FormData();
  if (lossImage) {
    form.append('loss_image', lossImage);
  }
  if (metaJson) {
    form.append('meta_json', metaJson);
  }
  if (workingDir) {
    form.append('working_dir', workingDir);
  }
  const response = await api.post(
    `/trainer/models/${encodeURIComponent(name)}/loss`,
    form,
    formDataRequestConfig,
  );
  return response.data;
};

export const loadModelToCar = async (modelPath: string, workingDir?: string) => {
  const response = await api.post('/drive/load_model', { model_path: modelPath, working_dir: workingDir });
  return response.data;
};

export interface TrainerTub {
  name: string;
  relative_path: string;
  absolute_path: string;
}

export const listTrainerTubs = async (workingDir?: string): Promise<{ tubs: TrainerTub[]; current_tub_path: string }> => {
  const response = await api.get('/trainer/tubs', { params: workingDir ? { working_dir: workingDir } : {} });
  return response.data as { tubs: TrainerTub[]; current_tub_path: string };
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
  ssh?: SSHCredentials;
  tub?: string;
}) => {
  const response = await api.post('/trainer/train/online', params);
  return response.data;
};

export const startMyPcTrain = async (params: {
  config_file?: string;
  working_dir?: string;
  ssh?: SSHCredentials;
  tub?: string;
}) => {
  const response = await api.post('/trainer/train/mypc', params);
  return response.data;
};

// mypc 断点续训：请求体/响应结构与 startMyPcTrain 完全一致

export const resumeMyPcTrain = async (params: {
  config_file?: string;
  working_dir?: string;
  ssh?: SSHCredentials;
  tub?: string;
}) => {
  const response = await api.post('/trainer/train/mypc/resume', params);
  return response.data;
};

export const stopTrain = async (jobId: string) => {
  const response = await api.post(`/trainer/train/${jobId}/stop`);
  return response.data;
};

export const listConnectorModels = async () => {
  const response = await api.get('/connector/remote/models');
  return response.data as { items: string[] };
};

export const downloadHarness = async (harnessId: string, componentId: string) => {
  const response = await api.post('/harness/download', {
    harness_id: harnessId,
    component_id: componentId,
  });
  return response.data as { status: string; path?: string; url?: string; message: string };
};

export interface ArenaModel {
  name: string;
  path: string;
  format: string;
  size: number;
  modified: string;
  compatible: boolean;
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

