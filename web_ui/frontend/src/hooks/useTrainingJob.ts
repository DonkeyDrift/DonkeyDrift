import { useCallback, useRef } from 'react';
import { useStore, TrainingJob } from '../store/useStore';
import {
  startLocalTrain,
  startOnlineTrain,
  stopTrain,
  createLogStream,
  setTrainerConfig,
} from '../services/api';

export function useTrainingJob() {
  const {
    trainingJob,
    setTrainingJob,
    appendTrainingLog,
    updateTrainingProgress,
    finishTrainingJob,
    configPath,
    trainerOnlineConfig,
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
        } else if (msg.type === 'status') {
          if (['completed', 'failed', 'stopped'].includes(msg.status)) {
            finishTrainingJob(msg.status);
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
    };

    setTrainingJob(job);
    connectSSE(job_id, job);
  }, [trainingJob, configPath, setTrainingJob, connectSSE]);

  const startOnline = useCallback(async () => {
    if (trainingJob && trainingJob.status === 'running') {
      return;
    }

    // Save config first
    await setTrainerConfig({
      host: trainerOnlineConfig.host,
      user: trainerOnlineConfig.user,
      password: trainerOnlineConfig.password,
      remote_dir_base: trainerOnlineConfig.remoteDirBase,
      model_name: trainerOnlineConfig.modelName,
      python_path: trainerOnlineConfig.pythonPath,
    }, 'train_online.conf');

    const { job_id } = await startOnlineTrain({
      config_file: 'train_online.conf',
      working_dir: configPath,
    });

    const job: TrainingJob = {
      id: job_id,
      mode: 'online',
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
    };

    setTrainingJob(job);
    connectSSE(job_id, job);
  }, [trainingJob, configPath, trainerOnlineConfig, setTrainingJob, connectSSE]);

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
    stopJob,
  };
}
