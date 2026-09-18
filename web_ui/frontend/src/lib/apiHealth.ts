/**
 * 极简 API 健康观测：只统计「在飞的请求数」与「最近一次失败」，供 apple 象限的
 * 统一加载骨架 / 错误提示条使用。
 *
 * 设计约束（本轮任务）：**不重构数据流、不改任何 API 调用**。这里只是给既有的
 * axios 实例挂两个拦截器做旁路观测，请求与响应原样透传；失败信息不落 DOM 原文
 * （不回显后端 detail），只把「有失败」这一事实交给 UI，文案走 i18n。
 */
export interface ApiHealthState {
  /** 在飞请求数（>0 = 正在加载） */
  pending: number;
  /** 已经成功完成过至少一次响应（用于区分「首屏加载中」与「后台刷新中」） */
  sawSuccess: boolean;
  /** 最近一次失败的时间戳（0 = 无失败） */
  lastErrorAt: number;
}

let state: ApiHealthState = { pending: 0, sawSuccess: false, lastErrorAt: 0 };
const listeners = new Set<(s: ApiHealthState) => void>();

const emit = (next: Partial<ApiHealthState>): void => {
  state = { ...state, ...next };
  for (const listener of listeners) listener(state);
};

export const getApiHealth = (): ApiHealthState => state;

export const subscribeApiHealth = (listener: (s: ApiHealthState) => void): (() => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};

/** 重试入口：清掉错误标记并重载当前页（不重放请求、不臆造数据）。 */
export const retryApiRequests = (): void => {
  emit({ lastErrorAt: 0 });
  try {
    window.location.reload();
  } catch {
    /* 无 window（测试/SSR）：只清标记 */
  }
};

export const dismissApiError = (): void => emit({ lastErrorAt: 0 });

let installed = false;

/** axios 实例的最小结构（避免为观测层把 axios 类型拉进来）。 */
interface TrackableClient {
  interceptors: {
    request: { use: (onFulfilled: (config: unknown) => unknown) => unknown };
    response: { use: (onFulfilled: (r: unknown) => unknown, onRejected: (e: unknown) => unknown) => unknown };
  };
}

/**
 * 给既有 axios 实例挂旁路观测（幂等）。由 services/api.ts 在创建实例后调用一次；
 * 测试里 services/api 常被整体 mock，此时根本不会调用到这里，观测层自然缺席。
 */
export const registerApiClient = (client: TrackableClient): void => {
  if (installed || !client || typeof client.interceptors?.request?.use !== 'function' || typeof client.interceptors?.response?.use !== 'function') {
    return;
  }
  installed = true;
  client.interceptors.request.use((config) => {
    emit({ pending: state.pending + 1 });
    return config;
  });
  client.interceptors.response.use(
    (response) => {
      // 任一请求成功即清掉错误标记：瞬时失败不该长期挂着红条
      emit({ pending: Math.max(0, state.pending - 1), sawSuccess: true, lastErrorAt: 0 });
      return response;
    },
    (error) => {
      emit({ pending: Math.max(0, state.pending - 1), ...(isDataLoadFailure(error) ? { lastErrorAt: Date.now() } : {}) });
      return Promise.reject(error);
    },
  );
};

/**
 * 只有「加载数据失败」才算失败：
 * - 只认 GET（POST 等动作类请求有自己的就地错误处理，且「无相机/未配置」这类 4xx 是
 *   预期状态——实测 `POST /api/drive/webrtc/session` 在无相机环境恒 400，若算失败会让
 *   正常使用中常挂一条红条）；
 * - 只认网络错误（无响应）或 5xx，4xx 通常是「尚未配置」而非「服务不可用」。
 */
const isDataLoadFailure = (error: unknown): boolean => {
  const e = error as { response?: { status?: number }; config?: { method?: string } } | null;
  if (!e || typeof e !== 'object') return false;
  const method = (e.config?.method || 'get').toLowerCase();
  if (method !== 'get') return false;
  const status = e.response?.status;
  if (status === undefined) return true; // 网络层失败（断连/超时/被 abort）
  return status >= 500;
};

/** 仅供测试：重置内部状态（含 install 幂等标记，便于用假 axios 客户端重挂拦截器）。 */
export const __resetApiHealth = (): void => {
  installed = false;
  state = { pending: 0, sawSuccess: false, lastErrorAt: 0 };
  for (const listener of listeners) listener(state);
};
