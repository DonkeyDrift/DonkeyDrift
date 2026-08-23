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

export const consoleRequest = (ip: string, path: string, init?: RequestInit): Promise<Response> =>
  fetch(consoleProxyUrl(ip, path), init);

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
