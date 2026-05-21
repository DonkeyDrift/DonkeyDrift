import React, { useState } from 'react';
import { ModeTabs } from '../components/trainer/ModeTabs';
import { LocalConfigForm } from '../components/trainer/LocalConfigForm';
import { RemoteConfigForm } from '../components/trainer/RemoteConfigForm';
import { ProgressPanel } from '../components/trainer/ProgressPanel';
import { LogPanel } from '../components/trainer/LogPanel';
import { ModelsList } from '../components/trainer/ModelsList';
import { useTrainingJob } from '../hooks/useTrainingJob';

type TrainerMode = 'local' | 'online';

export const TrainerPage: React.FC = () => {
  const [mode, setMode] = useState<TrainerMode>('local');
  const { job, startLocal, startOnline, stopJob, isRunning } = useTrainingJob();

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-zinc-100">Trainer</h1>
        <ModeTabs mode={mode} onChange={setMode} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          {mode === 'local' ? (
            <LocalConfigForm onStart={startLocal} isRunning={isRunning} />
          ) : (
            <RemoteConfigForm onStart={startOnline} isRunning={isRunning} />
          )}

          <button
            onClick={stopJob}
            disabled={!isRunning || !job}
            className="w-full px-4 py-2 bg-red-600 hover:bg-red-700 disabled:bg-zinc-800 disabled:text-zinc-600 text-white rounded-md font-medium transition-colors"
          >
            {!job ? 'No Active Training' : isRunning ? 'Stop Training' : 'Training Finished'}
          </button>

          <LogPanel job={job} />
        </div>

        <div className="lg:col-span-1 space-y-6">
          <ProgressPanel job={job} />
          <ModelsList />
        </div>
      </div>
    </div>
  );
};
