import { useCallback, useEffect, useRef } from 'react';
import { useStore, TrainingJob, TrainerOnlineConfig, TrainerMyPcConfig } from '../store/useStore';
import {
  startLocalTrain,
  startOnlineTrain,
  startMyPcTrain,
  resumeMyPcTrain,
  stopTrain,
  getJobStatus,
  createLogStream,
  setTrainerConfig,
} from '../services/api';

export function useTrainingJob() {
  const {
    trainingJob,
    setTrainingJob,
    setActiveTraining,
    clearActiveTraining,
    appendTrainingLog,
    updateTrainingProgress,
    finishTrainingJob,
    configPath,
  } = useStore();

  const eventSourceRef = useRef<EventSource | null>(null);

  const connectSSE = useCallback((jobId: string, job: TrainingJob) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const es = createLogStream(jobId);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'log') {
          appendTrainingLog([msg.line]);
        } else if (msg.type === 'progress') {
          const d = msg.data || {};
          updateTrainingProgress({
            currentEpoch: d.currentEpoch ?? 0,
            totalEpochs: d.totalEpochs ?? 0,
            currentStep: d.currentStep ?? 0,
            totalSteps: d.totalSteps ?? 0,
            loss: d.loss ?? null,
            globalPercent: d.globalPercent ?? 0,
          });
        } else if (msg.type === 'error') {
          // 后端训练流程异常时推送的 error 消息，显示到日志面板，避免静默失败
          appendTrainingLog([msg.message || 'Unknown error']);
        } else if (msg.type === 'status') {
          if (['completed', 'failed', 'stopped'].includes(msg.status)) {
            finishTrainingJob(msg.status, msg.error ?? null);
            es.close();
            eventSourceRef.current = null;
          }
        }
      } catch {
        // ignore malformed messages
      }
    };

    es.onerror = () => {
      // Auto-reconnect or close on terminal state
      if (['completed', 'failed', 'stopped'].includes(job.status)) {
        es.close();
        eventSourceRef.current = null;
      }
    };
  }, [appendTrainingLog, updateTrainingProgress, finishTrainingJob]);

  // 刷新页面后恢复训练进度：activeTraining 已持久化（id + 模式），
  // 据此从 /status 拉回进度快照并重连 SSE 继续收实时事件。
  const rehydratedRef = useRef(false);
  useEffect(() => {
    if (rehydratedRef.current) return;
    rehydratedRef.current = true;

    const active = useStore.getState().activeTraining;
    if (!active) return;
    // 已经在跑（例如刚启动后立刻刷新前的残留），避免重复订阅
    if (useStore.getState().trainingJob) return;

    getJobStatus(active.id)
      .then((status) => {
        const job: TrainingJob = {
          id: active.id,
          mode: active.mode,
          status: status.status,
          progress: {
            currentEpoch: status.progress?.currentEpoch ?? 0,
            totalEpochs: status.progress?.totalEpochs ?? 0,
            currentStep: status.progress?.currentStep ?? 0,
            totalSteps: status.progress?.totalSteps ?? 0,
            loss: status.progress?.loss ?? null,
            globalPercent: status.progress?.globalPercent ?? 0,
          },
          logs: [],
          startedAt: status.started_at ?? new Date().toISOString(),
          finishedAt: status.finished_at,
          errorMessage: status.error ?? null,
        };
        setTrainingJob(job);
        if (status.status === 'running') {
          connectSSE(active.id, job);
        } else {
          // 已终态：展示一次结果即可，清掉持久化 id 避免下次刷新再复活
          clearActiveTraining();
        }
      })
      .catch(() => {
        // 任务已不存在（后端重启等）：清掉失效 id，回到空闲态
        clearActiveTraining();
      });
  }, [setTrainingJob, clearActiveTraining, connectSSE]);

  const startLocal = useCallback(async (params: {
    tub: string;
    model: string;
    model_type: string;
    transfer?: string;
  }) => {
    if (trainingJob && trainingJob.status === 'running') {
      return;
    }

    const { job_id } = await startLocalTrain({
      ...params,
      working_dir: configPath,
    });

    const job: TrainingJob = {
      id: job_id,
      mode: 'local',
      status: 'running',
      progress: {
        currentEpoch: 0,
        totalEpochs: 0,
        currentStep: 0,
        totalSteps: 0,
        loss: null,
        globalPercent: 0,
      },
      logs: [],
      startedAt: new Date().toISOString(),
      errorMessage: null,
    };

    setTrainingJob(job);
    setActiveTraining(job_id, 'local');
    connectSSE(job_id, job);
  }, [trainingJob, configPath, setTrainingJob, setActiveTraining, connectSSE]);

  // Shared pipeline for SSH-based training ('online' = cloud server,
  // 'mypc' = the user's own computer, reached via SSH callback).
  // cfg 由调用方传入（而非读 store），避免闭包拿到旧的 store 值。
  const startSshTraining = useCallback(async (
    mode: 'online' | 'mypc',
    configFile: string,
    cfg: TrainerOnlineConfig & { tub?: string },
    start: typeof startOnlineTrain,
  ) => {
    if (trainingJob && trainingJob.status === 'running') {
      return;
    }

    // 非敏感设置持久化到 conf；密码只在会话内随请求传递，不落盘。
    await setTrainerConfig({
      host: cfg.host,
      user: cfg.user,
      remote_dir_base: cfg.remoteDirBase,
      model_name: cfg.modelName,
      python_path: cfg.pythonPath,
      key_path: cfg.keyPath,
    }, configFile);

    const { job_id } = await start({
      config_file: configFile,
      working_dir: configPath,
      tub: cfg.tub || undefined,
      ssh: {
        host: cfg.host,
        user: cfg.user,
        password: cfg.password,
      },
    });

    const job: TrainingJob = {
      id: job_id,
      mode,
      status: 'running',
      progress: {
        currentEpoch: 0,
        totalEpochs: 0,
        currentStep: 0,
        totalSteps: 0,
        loss: null,
        globalPercent: 0,
      },
      logs: [],
      startedAt: new Date().toISOString(),
      errorMessage: null,
    };

    setTrainingJob(job);
    setActiveTraining(job_id, mode);
    connectSSE(job_id, job);
  }, [trainingJob, configPath, setTrainingJob, setActiveTraining, connectSSE]);

  const startOnline = useCallback(async (cfg: TrainerOnlineConfig) =>
    startSshTraining('online', 'train_online.conf', cfg, startOnlineTrain),
  [startSshTraining]);

  const startMyPc = useCallback(async (cfg: TrainerMyPcConfig) =>
    startSshTraining('mypc', 'train_my_pc.conf', cfg, startMyPcTrain),
  [startSshTraining]);

  const resumeMyPc = useCallback(async (cfg: TrainerMyPcConfig) =>
    startSshTraining('mypc', 'train_my_pc.conf', cfg, resumeMyPcTrain),
  [startSshTraining]);

  const stopJob = useCallback(async () => {
    if (!trainingJob || trainingJob.status !== 'running') {
      return;
    }
    await stopTrain(trainingJob.id);
    finishTrainingJob('stopped');
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, [trainingJob, finishTrainingJob]);

  return {
    job: trainingJob,
    isRunning: trainingJob?.status === 'running',
    startLocal,
    startOnline,
    startMyPc,
    resumeMyPc,
    stopJob,
  };
}
