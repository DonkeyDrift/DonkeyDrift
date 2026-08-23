import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import {
  createSimCollectEventStream,
  getApiErrorMessage,
  getSimCollectStatus,
  startSimCollect,
  stopSimCollect,
  type SimCollectJobState,
  type SimCollectResult,
  type SimCollectStartParams,
  type SimCollectStatus,
} from '../services/api';
import { useTranslation } from '@/i18n';

export interface SimCollectJobView {
  jobId: string | null;
  status: SimCollectJobState;
  step: number;
  total: number;
  cte: number | null;
  speed: number | null;
  result: SimCollectResult | null;
  error: string | null;
  logs: string[];
}

type SimCollectEvent = {
  type: 'log' | 'progress' | 'status';
  line?: string;
  step?: number;
  total?: number;
  cte?: number;
  speed?: number;
  status?: SimCollectJobState;
  result?: SimCollectResult;
  error?: string;
};

const TERMINAL_STATUSES: SimCollectJobState[] = ['done', 'error', 'stopped'];

const isTerminal = (status: SimCollectJobState) => TERMINAL_STATUSES.includes(status);

/**
 * 模拟器采集任务状态：自包含 local state，SSE 优先推送进度/日志，
 * SSE 断开且任务未到终态时自动降级为 2s 轮询 status 接口兜底。
 */
export const useSimCollectJob = () => {
  const { t } = useTranslation();
  const [job, setJob] = useState<SimCollectJobView | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const jobRef = useRef<SimCollectJobView | null>(null);

  useEffect(() => {
    jobRef.current = job;
  }, [job]);

  const clearSubscriptions = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const applyStatus = useCallback((status: SimCollectStatus) => {
    setJob({
      jobId: status.job_id,
      status: status.status,
      step: status.step ?? 0,
      total: status.steps_total ?? 0,
      cte: status.cte ?? null,
      speed: status.speed ?? null,
      result: status.result ?? null,
      error: status.error ?? null,
      logs: status.logs ?? [],
    });
  }, []);

  const pollStatus = useCallback((jobId: string) => {
    const loadStatus = async () => {
      try {
        const status = await getSimCollectStatus(jobId);
        applyStatus(status);
        if (isTerminal(status.status)) {
          clearSubscriptions();
        }
      } catch (error) {
        setJob((prev) => (prev ? { ...prev, error: getApiErrorMessage(error) } : prev));
        clearSubscriptions();
      }
    };

    void loadStatus();
    pollTimerRef.current = setInterval(() => {
      void loadStatus();
    }, 2000);
  }, [applyStatus, clearSubscriptions]);

  const subscribeEvents = useCallback((jobId: string) => {
    clearSubscriptions();
    const eventSource = createSimCollectEventStream(jobId);
    eventSourceRef.current = eventSource;

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as SimCollectEvent;
        if (data.type === 'log' && data.line != null) {
          setJob((prev) => (prev ? { ...prev, logs: [...prev.logs.slice(-199), data.line ?? ''] } : prev));
        } else if (data.type === 'progress') {
          setJob((prev) => (prev
            ? {
                ...prev,
                step: typeof data.step === 'number' ? data.step : prev.step,
                total: typeof data.total === 'number' ? data.total : prev.total,
                cte: typeof data.cte === 'number' ? data.cte : prev.cte,
                speed: typeof data.speed === 'number' ? data.speed : prev.speed,
              }
            : prev));
        } else if (data.type === 'status' && data.status) {
          const nextStatus = data.status;
          setJob((prev) => (prev
            ? {
                ...prev,
                status: nextStatus,
                result: data.result ?? prev.result,
                error: data.error ?? prev.error,
              }
            : prev));
          if (isTerminal(nextStatus)) {
            clearSubscriptions();
            // 终态后再拉一次完整状态，补齐 result/logs 等字段
            void getSimCollectStatus(jobId).then(applyStatus).catch(() => {});
          }
        }
      } catch {
        // 忽略格式错误的事件
      }
    };

    eventSource.onerror = () => {
      // 终态事件已处理时订阅已清空；ref 仍在说明任务可能还在跑 → 降级轮询
      if (eventSourceRef.current) {
        clearSubscriptions();
        pollStatus(jobId);
      }
    };
  }, [applyStatus, clearSubscriptions, pollStatus]);

  const start = useCallback(async (params: SimCollectStartParams = {}) => {
    clearSubscriptions();
    try {
      const result = await startSimCollect(params);
      setJob({
        jobId: result.job_id,
        status: result.status,
        step: 0,
        total: params.steps ?? 0,
        cte: null,
        speed: null,
        result: null,
        error: null,
        logs: [],
      });
      subscribeEvents(result.job_id);
    } catch (error) {
      const message = axios.isAxiosError(error) && error.response?.status === 409
        ? t('drive.simCollectAlreadyRunning')
        : getApiErrorMessage(error);
      setJob({
        jobId: null,
        status: 'error',
        step: 0,
        total: 0,
        cte: null,
        speed: null,
        result: null,
        error: message,
        logs: [],
      });
    }
  }, [clearSubscriptions, subscribeEvents, t]);

  const stop = useCallback(async () => {
    const jobId = jobRef.current?.jobId;
    if (!jobId) return;
    try {
      await stopSimCollect(jobId);
      // 终态由 SSE status 事件（或轮询兜底）推送，这里不本地改状态
    } catch (error) {
      setJob((prev) => (prev ? { ...prev, error: getApiErrorMessage(error) } : prev));
    }
  }, []);

  const reset = useCallback(() => {
    clearSubscriptions();
    setJob(null);
  }, [clearSubscriptions]);

  useEffect(() => clearSubscriptions, [clearSubscriptions]);

  return { job, start, stop, reset };
};
