import React, { useEffect, useReducer } from 'react';
import { Activity } from 'lucide-react';
import { SectionCardTitle } from '../ui/SectionCardTitle';
import { TrainingJob } from '../../store/useStore';
import { useTranslation } from '@/i18n';

interface ProgressPanelProps {
  job: TrainingJob | null;
}

export const ProgressPanel: React.FC<ProgressPanelProps> = ({ job }) => {
  const { t } = useTranslation();
  // running 时每秒强制重渲染一次，让「时长」平滑走秒；非 running 不起定时器
  const [, forceTick] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    if (job?.status !== 'running') return;
    const timer = setInterval(forceTick, 1000);
    return () => clearInterval(timer);
  }, [job?.status]);
  const { progress, status, startedAt, finishedAt } = job ?? {};
  const rawPercent = job
    ? Math.min(100, Math.max(0, progress!.globalPercent))
    : 0;
  // 小百分比时进度条至少显示一点宽度，避免视觉上一直 0%
  const barPercent =
    job && progress!.totalSteps > 0 && rawPercent < 0.1
      ? Math.max(2, rawPercent)
      : rawPercent;
  const isInitializing = job && status === 'running' && progress!.totalSteps === 0;
  const isSmallPercent = job && progress!.totalSteps > 0 && rawPercent < 0.1;
  const percentLabel = isSmallPercent ? rawPercent.toFixed(2) : rawPercent.toFixed(1);

  const statusColor = job
    ? ({
        pending: 'text-yellow-400',
        running: 'text-cyan-400',
        completed: 'text-green-400',
        failed: 'text-red-400',
        stopped: 'text-orange-400',
      } as const)[status!]
    : '';

  const statusLabel: Record<TrainingJob['status'], string> = {
    pending: t('trainer.statusPending'),
    running: t('trainer.statusRunning'),
    completed: t('trainer.statusCompleted'),
    failed: t('trainer.statusFailed'),
    stopped: t('trainer.statusStopped'),
  };

  const duration = startedAt
    ? Math.floor(
        (new Date(finishedAt || Date.now()).getTime() - new Date(startedAt).getTime()) / 1000
      )
    : 0;
  const mins = Math.floor(duration / 60);
  const secs = duration % 60;

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg">
      <div className="px-4 pt-4 pb-2 flex items-center justify-between">
        <SectionCardTitle
          icon={<Activity className="w-5 h-5" />}
          title={t('trainer.trainingStatus')}
          subtitle={t('trainer.trainingStatusSubtitle')}
        />
        {job && (
          <span className={`text-sm font-bold ${statusColor}`}>{statusLabel[status!]}</span>
        )}
      </div>

      {!job ? (
        <div className="p-6 flex flex-col items-center text-center space-y-3">
          <div className="w-10 h-10 rounded-full bg-zinc-800 flex items-center justify-center">
            <Activity className="w-5 h-5 text-zinc-500" />
          </div>
          <div>
            <div className="text-sm font-medium text-zinc-300">{t('trainer.trainingIdle')}</div>
            <div className="text-xs text-zinc-500 mt-1">
              {t('trainer.idleHint')}
            </div>
          </div>
        </div>
      ) : (
        <div className="p-4 pt-0 space-y-3">
          {/* Progress bar */}
          <div className="space-y-1">
            {isInitializing ? (
              <div className="flex justify-between text-xs text-zinc-400">
                <span className="animate-pulse">{t('trainer.initializing')}</span>
              </div>
            ) : (
              <div className="flex justify-between text-xs text-zinc-500">
                <span>{t('trainer.progress')}</span>
                <span>{percentLabel}%</span>
              </div>
            )}
            <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
              {isInitializing ? (
                <div
                  className="h-full bg-cyan-600 animate-pulse"
                  style={{ width: '8%' }}
                />
              ) : (
                <div
                  className="h-full bg-cyan-600 transition-all duration-300"
                  style={{ width: `${barPercent}%` }}
                />
              )}
            </div>
          </div>

          {/* Metrics grid */}
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="bg-zinc-950 rounded px-3 py-2">
              <div className="text-xs text-zinc-500">{t('trainer.epoch')}</div>
              <div className="text-zinc-200">
                {progress!.currentEpoch}
                {progress!.totalEpochs > 0 ? ` / ${progress!.totalEpochs}` : ''}
              </div>
            </div>
            <div className="bg-zinc-950 rounded px-3 py-2">
              <div className="text-xs text-zinc-500">{t('trainer.step')}</div>
              <div className="text-zinc-200">
                {progress!.currentStep}
                {progress!.totalSteps > 0 ? ` / ${progress!.totalSteps}` : ''}
              </div>
            </div>
            <div className="bg-zinc-950 rounded px-3 py-2">
              <div className="text-xs text-zinc-500">{t('trainer.loss')}</div>
              <div className="text-zinc-200">
                {progress!.loss !== null ? progress!.loss.toFixed(4) : '--'}
              </div>
            </div>
            <div className="bg-zinc-950 rounded px-3 py-2">
              <div className="text-xs text-zinc-500">{t('trainer.duration')}</div>
              <div className="text-zinc-200">
                {mins}m {secs}s
              </div>
            </div>
          </div>

          {/* 失败原因：训练失败时直接显示 SSE status 消息带来的真实原因，可选中复制 */}
          {status === 'failed' && job.errorMessage && (
            <div className="bg-red-950/40 border border-red-900/60 rounded px-3 py-2">
              <div className="text-xs text-red-400 mb-0.5">{t('trainer.failureReason')}</div>
              <div className="text-sm text-red-200 break-all select-text">{job.errorMessage}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
