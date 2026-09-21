import { API_URL } from './api';

// Drifter Console（DC）车端 HTTP API 的轻量访问层。所有请求都经 DD 后端
// `/api/console/proxy/<ip>/<path>` 同源代理转发到车端，规避浏览器跨域限制
// （Issue #234）。

export type ConsoleDevice = {
  ip: string;
  port: number;
  reachable: boolean;
};

export type ConsoleDiscovery = {
  status: boolean;
  found: ConsoleDevice[];
  count: number;
  scanned: number;
  message: string;
};

/** 车端遥测一条 sample 的字段（与 DC /api/data JSON 的 latest 对齐）。 */
export interface ConsoleTelemetry {
  seq?: number;
  t?: number;
  dt?: number;
  thr?: number;
  str?: number;
  gz?: number;
  gx?: number;
  gy?: number;
  ax?: number;
  ay?: number;
  az?: number;
  mode?: number;
  park?: number;
  ch1?: number;
  ch2?: number;
  ch3?: number;
  ch4?: number;
  ch5?: number;
  ch6?: number;
  vol?: number;
  pseudoSpeed?: number;
  sd?: number;
  ed?: number;
  sm?: number;
  mm?: number;
  de?: number;
  da?: number;
  dc?: number;
  gzf?: number;
  dye?: number;
  dtm?: number;
  [key: string]: unknown;
}

export const consoleProxyUrl = (ip: string, path: string): string =>
  `${API_URL}/console/proxy/${encodeURIComponent(ip)}/${path.replace(/^\//, '')}`;

// 代理请求兜底超时（毫秒）：车端 IP 失效/网络黑洞时 fetch 可能长时间挂起，
// 导致调用方（静音/DEV/OTA）的失败分支永远不触发、按钮卡死在禁用态。
// 后端代理本身有 10s 超时，这里取 12s 留出余量；调用方显式传入 signal 时尊重之。
export const CONSOLE_REQUEST_TIMEOUT_MS = 12000;

export const consoleRequest = (ip: string, path: string, init?: RequestInit): Promise<Response> => {
  const hasSignal = init && init.signal !== undefined && init.signal !== null;
  if (hasSignal) {
    return fetch(consoleProxyUrl(ip, path), init);
  }
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), CONSOLE_REQUEST_TIMEOUT_MS);
  return fetch(consoleProxyUrl(ip, path), { ...init, signal: controller.signal }).finally(() =>
    window.clearTimeout(timer),
  );
};

const ensureOk = async (res: Response): Promise<Response> => {
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res;
};

export const consoleGetText = async (ip: string, path: string): Promise<string> => {
  const res = await consoleRequest(ip, path);
  await ensureOk(res);
  return res.text();
};

export const consoleGetJson = async <T>(ip: string, path: string): Promise<T> => {
  const res = await consoleRequest(ip, path);
  await ensureOk(res);
  return (await res.json()) as T;
};

export const consolePostText = async (
  ip: string,
  path: string,
  body: string,
  contentType = 'text/plain;charset=UTF-8',
): Promise<string> => {
  const res = await consoleRequest(ip, path, {
    method: 'POST',
    headers: { 'Content-Type': contentType },
    body,
  });
  await ensureOk(res);
  return res.text();
};

export const consolePostForm = async (
  ip: string,
  path: string,
  form: URLSearchParams | FormData,
): Promise<string> => {
  const res = await consoleRequest(ip, path, { method: 'POST', body: form });
  await ensureOk(res);
  return res.text();
};
