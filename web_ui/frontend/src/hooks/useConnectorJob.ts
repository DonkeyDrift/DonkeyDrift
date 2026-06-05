import { useCallback, useEffect, useRef, useState } from 'react';
import {
  createConnectorJobStream,
  getApiErrorMessage,
  getConnectorJobStatus,
  stopConnectorJob,
  type ConnectorJobState,
  type ConnectorJobStatus,
} from '../services/api';

type ConnectorJobEvent = {
  type: 'progress' | 'log' | 'status' | 'drive_pid';
  progress?: number;
  line?: string;
  status?: ConnectorJobState;
  error?: string | null;
  pid?: number;
};

type StartConnectorJobResult = {
  job_id: string;
  status: ConnectorJobState;
};

type StartConnectorJobOptions = {
  onCompleted?: (status: ConnectorJobStatus | null) => void | Promise<void>;
  onFinished?: (status: ConnectorJobStatus | null) => void | Promise<void>;
};

type UseConnectorJobOptions = {
  onDrivePid?: (pid: number) => void;
  onFinished?: (status: ConnectorJobStatus | null) => void | Promise<void>;
};

const TERMINAL_STATUSES: ConnectorJobState[] = ['completed', 'failed', 'stopped'];

export const useConnectorJob = (options: UseConnectorJobOptions = {}) => {
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<ConnectorJobStatus | null>(null);
  const [jobProgress, setJobProgress] = useState(0);
  const [jobLogs, setJobLogs] = useState<string[]>([]);
  const eventSourceRef = useRef<EventSource | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startOptionsRef = useRef<StartConnectorJobOptions>({});
  const optionsRef = useRef(options);

  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

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

  const finishJob = useCallback(async (status: ConnectorJobStatus | null) => {
    clearSubscriptions();
    if (status?.status === 'completed') {
      setJobProgress(100);
      await startOptionsRef.current.onCompleted?.(status);
    }
    await startOptionsRef.current.onFinished?.(status);
    await optionsRef.current.onFinished?.(status);
  }, [clearSubscriptions]);

  const applyStatus = useCallback((status: ConnectorJobStatus) => {
    setJobStatus(status);
    setJobProgress(status.progress);
    setJobLogs(status.logs);
  }, []);

  const pollJobStatus = useCallback((jobId: string) => {
    const loadStatus = async () => {
      try {
        const status = await getConnectorJobStatus(jobId);
        applyStatus(status);
        if (TERMINAL_STATUSES.includes(status.status)) {
          await finishJob(status);
        }
      } catch (error) {
        setJobLogs([`任务状态读取失败: ${getApiErrorMessage(error)}`]);
        clearSubscriptions();
      }
    };

    void loadStatus();
    pollTimerRef.current = setInterval(() => {
      void loadStatus();
    }, 2000);
  }, [applyStatus, clearSubscriptions, finishJob]);

  const subscribeJobEvents = useCallback((jobId: string) => {
    clearSubscriptions();
    const eventSource = createConnectorJobStream(jobId);
    eventSourceRef.current = eventSource;

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as ConnectorJobEvent;
        if (data.type === 'progress' && typeof data.progress === 'number') {
          setJobProgress(data.progress);
        } else if (data.type === 'log' && data.line) {
          setJobLogs((prev) => [...prev.slice(-199), data.line || '']);
        } else if (data.type === 'drive_pid' && typeof data.pid === 'number') {
          optionsRef.current.onDrivePid?.(data.pid);
        } else if (data.type === 'status' && data.status) {
          const nextStatus: ConnectorJobStatus = {
            id: jobId,
            kind: jobStatus?.kind ?? '',
            status: data.status,
            progress: data.status === 'completed' ? 100 : jobProgress,
            logs: jobLogs,
            error: data.error,
            started_at: jobStatus?.started_at ?? new Date().toISOString(),
          };
          setJobStatus(nextStatus);
          if (TERMINAL_STATUSES.includes(data.status)) {
            void finishJob(nextStatus);
          }
        }
      } catch {
        // 忽略格式错误的事件
      }
    };

    eventSource.onerror = () => {
      clearSubscriptions();
      pollJobStatus(jobId);
    };
  }, [clearSubscriptions, finishJob, jobLogs, jobProgress, jobStatus, pollJobStatus]);

  const startJob = useCallback(async (
    action: () => Promise<StartConnectorJobResult>,
    startOptions: StartConnectorJobOptions = {},
  ) => {
    clearSubscriptions();
    startOptionsRef.current = startOptions;
    setJobLogs([]);
    setJobProgress(0);
    try {
      const result = await action();
      const initialStatus: ConnectorJobStatus = {
        id: result.job_id,
        kind: '',
        status: result.status,
        progress: 0,
        logs: [],
        started_at: new Date().toISOString(),
      };
      setActiveJobId(result.job_id);
      setJobStatus(initialStatus);
      subscribeJobEvents(result.job_id);
    } catch (error) {
      setJobLogs([`启动失败: ${getApiErrorMessage(error)}`]);
    }
  }, [clearSubscriptions, subscribeJobEvents]);

  const cancelJob = useCallback(async () => {
    if (!activeJobId) return;
    await stopConnectorJob(activeJobId);
  }, [activeJobId]);

  const resetJob = useCallback(() => {
    clearSubscriptions();
    setActiveJobId(null);
    setJobStatus(null);
    setJobProgress(0);
    setJobLogs([]);
  }, [clearSubscriptions]);

  useEffect(() => clearSubscriptions, [clearSubscriptions]);

  return {
    activeJobId,
    jobStatus,
    jobProgress,
    jobLogs,
    isJobRunning: jobStatus?.status === 'running' || jobStatus?.status === 'pending',
    startJob,
    cancelJob,
    resetJob,
  };
};
