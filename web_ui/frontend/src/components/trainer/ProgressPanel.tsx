import React from 'react';
import { Activity } from 'lucide-react';
import { TrainingJob } from '../../store/useStore';

interface ProgressPanelProps {
  job: TrainingJob | null;
}

export const ProgressPanel: React.FC<ProgressPanelProps> = ({ job }) => {
  const { progress, status, startedAt, finishedAt } = job ?? {};
  const percent = job
    ? Math.min(100, Math.max(0, progress!.globalPercent))
    : 0;

  const statusColor = job
    ? ({
        pending: 'text-yellow-400',
        running: 'text-cyan-400',
        completed: 'text-green-400',
        failed: 'text-red-400',
        stopped: 'text-orange-400',
      } as const)[status!]
    : '';

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
        <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">
          Training Status
        </h3>
        {job && (
          <span className={`text-sm font-bold ${statusColor}`}>{status!.toUpperCase()}</span>
        )}
      </div>

      {!job ? (
        <div className="p-6 flex flex-col items-center text-center space-y-3">
          <div className="w-10 h-10 rounded-full bg-zinc-800 flex items-center justify-center">
            <Activity className="w-5 h-5 text-zinc-500" />
          </div>
          <div>
            <div className="text-sm font-medium text-zinc-300">Training Idle</div>
            <div className="text-xs text-zinc-500 mt-1">
              Start a training job to see live progress metrics.
            </div>
          </div>
        </div>
      ) : (
        <div className="p-4 pt-0 space-y-3">
          {/* Progress bar */}
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-zinc-500">
              <span>Progress</span>
              <span>{percent.toFixed(1)}%</span>
            </div>
            <div className="h-2 bg-zinc-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-cyan-600 transition-all duration-300"
                style={{ width: `${percent}%` }}
              />
            </div>
          </div>

          {/* Metrics grid */}
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="bg-zinc-950 rounded px-3 py-2">
              <div className="text-xs text-zinc-500">Epoch</div>
              <div className="text-zinc-200">
                {progress!.currentEpoch}
                {progress!.totalEpochs > 0 ? ` / ${progress!.totalEpochs}` : ''}
              </div>
            </div>
            <div className="bg-zinc-950 rounded px-3 py-2">
              <div className="text-xs text-zinc-500">Step</div>
              <div className="text-zinc-200">
                {progress!.currentStep}
                {progress!.totalSteps > 0 ? ` / ${progress!.totalSteps}` : ''}
              </div>
            </div>
            <div className="bg-zinc-950 rounded px-3 py-2">
              <div className="text-xs text-zinc-500">Loss</div>
              <div className="text-zinc-200">
                {progress!.loss !== null ? progress!.loss.toFixed(4) : '--'}
              </div>
            </div>
            <div className="bg-zinc-950 rounded px-3 py-2">
              <div className="text-xs text-zinc-500">Duration</div>
              <div className="text-zinc-200">
                {mins}m {secs}s
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
