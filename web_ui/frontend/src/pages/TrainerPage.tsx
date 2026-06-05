import React, { useEffect, useCallback } from 'react';
import { useStore } from '../store/useStore';
import { getTrainerConfig, loadConfig, loadMyconfig, saveTrainingConfig } from '../services/api';
import { ModeTabs } from '../components/trainer/ModeTabs';
import { LocalConfigForm } from '../components/trainer/LocalConfigForm';
import { RemoteConfigForm } from '../components/trainer/RemoteConfigForm';
import { ProgressPanel } from '../components/trainer/ProgressPanel';
import { LogPanel } from '../components/trainer/LogPanel';
import { ModelsList } from '../components/trainer/ModelsList';
import { useTrainingJob } from '../hooks/useTrainingJob';

type TrainerMode = 'local' | 'online';

const TRAINING_KEYS = [
  'BATCH_SIZE',
  'TRAIN_TEST_SPLIT',
  'MAX_EPOCHS',
  'SHOW_PLOT',
  'USE_EARLY_STOP',
  'EARLY_STOP_PATIENCE',
  'LEARNING_RATE',
  'CREATE_TF_LITE',
  'PRUNE_VAL_LOSS_DEGRADATION_LIMIT',
];

export const TrainerPage: React.FC = () => {
  const [mode, setMode] = React.useState<TrainerMode>('local');
  const { job, startLocal, startOnline, stopJob, isRunning } = useTrainingJob();
  const { configPath, trainerOnlineConfig, setTrainerOnlineConfig, trainerLocalConfig, setTrainerLocalConfig } = useStore();

  // Remote form state
  const [host, setHost] = React.useState(trainerOnlineConfig.host);
  const [user, setUser] = React.useState(trainerOnlineConfig.user);
  const [password, setPassword] = React.useState(trainerOnlineConfig.password);
  const [remoteDirBase, setRemoteDirBase] = React.useState(trainerOnlineConfig.remoteDirBase);
  const [modelName, setModelName] = React.useState(trainerOnlineConfig.modelName);
  const [pythonPath, setPythonPath] = React.useState(trainerOnlineConfig.pythonPath);

  // Load remote config on mount
  useEffect(() => {
    getTrainerConfig('train_online.conf')
      .then((cfg) => {
        setHost(cfg.host);
        setUser(cfg.user);
        setPassword(cfg.password);
        setRemoteDirBase(cfg.remote_dir_base);
        setModelName(cfg.model_name);
        setPythonPath(cfg.python_path);
        setTrainerOnlineConfig({
          host: cfg.host,
          user: cfg.user,
          password: cfg.password,
          remoteDirBase: cfg.remote_dir_base,
          modelName: cfg.model_name,
          pythonPath: cfg.python_path,
        });
      })
      .catch(() => {
        // use defaults if file doesn't exist yet
      });
  }, [setTrainerOnlineConfig]);

  // Load training config from myconfig.py on mount / when configPath changes
  useEffect(() => {
    if (!configPath) return;

    Promise.all([loadConfig(configPath), loadMyconfig(configPath)])
      .then(([mergedData, myconfigData]) => {
        const merged = mergedData.config || {};
        const myconfig = myconfigData.config || {};
        const updates: Partial<typeof trainerLocalConfig> = {};

        // Read training config values (prefer myconfig.py overrides)
        if (merged.BATCH_SIZE !== undefined) updates.batchSize = merged.BATCH_SIZE;
        if (merged.TRAIN_TEST_SPLIT !== undefined) updates.trainTestSplit = merged.TRAIN_TEST_SPLIT;
        if (merged.MAX_EPOCHS !== undefined) updates.maxEpochs = merged.MAX_EPOCHS;
        if (merged.SHOW_PLOT !== undefined) updates.showPlot = merged.SHOW_PLOT;
        if (merged.USE_EARLY_STOP !== undefined) updates.useEarlyStop = merged.USE_EARLY_STOP;
        if (merged.EARLY_STOP_PATIENCE !== undefined) updates.earlyStopPatience = merged.EARLY_STOP_PATIENCE;
        if (merged.LEARNING_RATE !== undefined) updates.learningRate = merged.LEARNING_RATE;
        if (merged.CREATE_TF_LITE !== undefined) updates.createTfLite = merged.CREATE_TF_LITE;
        if (merged.PRUNE_VAL_LOSS_DEGRADATION_LIMIT !== undefined) updates.pruneValLossDegradationLimit = merged.PRUNE_VAL_LOSS_DEGRADATION_LIMIT;
        if (merged.DEFAULT_MODEL_TYPE !== undefined) updates.modelType = merged.DEFAULT_MODEL_TYPE;

        // Determine if advanced options are enabled based on myconfig.py overrides
        const hasAdvancedOverrides = TRAINING_KEYS.some((k) => k in myconfig);
        if (hasAdvancedOverrides) {
          updates.advancedEnabled = true;
        }

        if (Object.keys(updates).length > 0) {
          setTrainerLocalConfig(updates);
        }
      })
      .catch(() => {
        // Fall back to localStorage persisted values
      });
  }, [configPath, setTrainerLocalConfig]);

  const handleLocalStart = useCallback(async () => {
    const modelName = trainerLocalConfig.model.trim() || `pilot_${Date.now()}`;

    // Save training config to myconfig.py
    const trainingConfig: Record<string, string | number | boolean> = {};
    if (trainerLocalConfig.advancedEnabled) {
      trainingConfig['BATCH_SIZE'] = trainerLocalConfig.batchSize;
      trainingConfig['TRAIN_TEST_SPLIT'] = trainerLocalConfig.trainTestSplit;
      trainingConfig['MAX_EPOCHS'] = trainerLocalConfig.maxEpochs;
      trainingConfig['SHOW_PLOT'] = trainerLocalConfig.showPlot;
      trainingConfig['USE_EARLY_STOP'] = trainerLocalConfig.useEarlyStop;
      trainingConfig['EARLY_STOP_PATIENCE'] = trainerLocalConfig.earlyStopPatience;
      trainingConfig['LEARNING_RATE'] = trainerLocalConfig.learningRate;
      trainingConfig['CREATE_TF_LITE'] = trainerLocalConfig.createTfLite;
      trainingConfig['PRUNE_VAL_LOSS_DEGRADATION_LIMIT'] = trainerLocalConfig.pruneValLossDegradationLimit;
    }

    await saveTrainingConfig({
      path: configPath,
      enabled: trainerLocalConfig.advancedEnabled,
      config: trainingConfig,
    });

    startLocal({
      tub: trainerLocalConfig.tub,
      model: `./models/${modelName}`,
      model_type: trainerLocalConfig.modelType,
      transfer: trainerLocalConfig.transfer.trim() || undefined,
    });
  }, [trainerLocalConfig, configPath, startLocal]);

  const handleOnlineStart = useCallback(() => {
    setTrainerOnlineConfig({
      host,
      user,
      password,
      remoteDirBase,
      modelName,
      pythonPath,
    });
    startOnline();
  }, [host, user, password, remoteDirBase, modelName, pythonPath, setTrainerOnlineConfig, startOnline]);

  const handleAction = useCallback(() => {
    if (isRunning) {
      stopJob();
    } else if (mode === 'local') {
      handleLocalStart();
    } else {
      handleOnlineStart();
    }
  }, [isRunning, mode, stopJob, handleLocalStart, handleOnlineStart]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-zinc-100">Trainer</h1>
        <ModeTabs mode={mode} onChange={setMode} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="space-y-6">
          {mode === 'local' ? (
            <LocalConfigForm
              config={trainerLocalConfig}
              onConfigChange={setTrainerLocalConfig}
            />
          ) : (
            <RemoteConfigForm
              host={host}
              onHostChange={setHost}
              user={user}
              onUserChange={setUser}
              password={password}
              onPasswordChange={setPassword}
              remoteDirBase={remoteDirBase}
              onRemoteDirBaseChange={setRemoteDirBase}
              modelName={modelName}
              onModelNameChange={setModelName}
              pythonPath={pythonPath}
              onPythonPathChange={setPythonPath}
            />
          )}

          <LogPanel job={job} />
        </div>

        <div className="space-y-6">
          <ProgressPanel job={job} />

          <button
            onClick={handleAction}
            className={`w-full px-4 py-2 rounded-md font-medium transition-colors text-white ${
              isRunning
                ? 'bg-red-600 hover:bg-red-700'
                : 'bg-cyan-600 hover:bg-cyan-700'
            }`}
          >
            {isRunning
              ? 'Stop Training'
              : mode === 'local'
              ? 'Start Local Training'
              : 'Start Cloud Training'}
          </button>

          <ModelsList />
        </div>
      </div>
    </div>
  );
};
