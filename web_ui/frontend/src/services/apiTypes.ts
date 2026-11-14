/**
 * API 类型定义（手写，与后端 Pydantic 模型对应）。
 *
 * Phase 2 P2-2：OpenAPI 自动生成的替代方案。
 * 当前后端导入链有问题（donkeycar.management.train_online 缺失），
 * 无法直接生成 OpenAPI schema。先手写关键接口类型，后续可替换为自动生成。
 */

// ── 通用 ──────────────────────────────────────────────────────────────────

export interface ApiResponse<T = unknown> {
  ok: boolean;
  data?: T;
  error?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

// ── Config ────────────────────────────────────────────────────────────────

export interface AppConfig {
  version: string;
  [key: string]: unknown;
}

// ── Tub ───────────────────────────────────────────────────────────────────

export interface TubSession {
  id: string;
  name: string;
  record_count: number;
  created_at: string;
}

export interface TubRecord {
  _index: number;
  image_path?: string;
  user_angle: number;
  user_throttle: number;
  [key: string]: unknown;
}

// ── Trainer ───────────────────────────────────────────────────────────────

export interface TrainerConfig {
  model_type: string;
  batch_size: number;
  epochs: number;
  [key: string]: unknown;
}

export interface ModelInfo {
  name: string;
  path: string;
  size_bytes: number;
  modified_at: string;
}

// ── Drive ─────────────────────────────────────────────────────────────────

export interface DriveWebRtcStats {
  browser_fps: number;
  browser_p95_frame_interval_ms: number;
  inbound_fps?: number;
  frames_dropped?: number;
  jitter_ms?: number;
  jitter_buffer_delay_ms?: number;
  e2e_latency_p50_ms?: number;
  e2e_latency_p95_ms?: number;
  e2e_samples?: number;
}

// ── Arena ─────────────────────────────────────────────────────────────────

export interface ArenaModel {
  name: string;
  path: string;
  model_type: string;
}

export interface ArenaPilot {
  id: string;
  model_path: string;
  model_type: string;
  loaded_at: string;
}

export interface ArenaPrediction {
  angle: number;
  throttle: number;
}

// ── AI Config ─────────────────────────────────────────────────────────────

export interface AiConfigProvider {
  id: string;
  name: string;
  api_key?: string;
  base_url?: string;
}

export interface AiConfigAccount {
  provider: string;
  account_id: string;
  access_token?: string;
  refresh_token?: string;
}
