import React, { useEffect, useCallback, useRef } from 'react';
import { useStore } from '../store/useStore';
import {
  getTrainerConfig,
  loadConfig,
  loadMyconfig,
  saveTrainingConfig,
  listTrainerTubs,
  type TrainerTub,
} from '../services/api';
import { ModeTabs } from '../components/trainer/ModeTabs';
import { LocalConfigForm } from '../components/trainer/LocalConfigForm';
import { RemoteConfigForm } from '../components/trainer/RemoteConfigForm';
import { ProgressPanel } from '../components/trainer/ProgressPanel';
import { LogPanel } from '../components/trainer/LogPanel';
import { ModelsList } from '../components/trainer/ModelsList';
import { useTrainingJob } from '../hooks/useTrainingJob';
import { useTranslation } from '@/i18n';
import type { TrainerMode } from '../components/trainer/ModeTabs';

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
  const { t } = useTranslation();
  const [mode, setMode] = React.useState<TrainerMode>('local');
  const { job, startLocal, startOnline, startMyPc, stopJob, isRunning } = useTrainingJob();
  const {
    configPath,
    trainerOnlineConfig, setTrainerOnlineConfig,
    trainerMyPcConfig, setTrainerMyPcConfig,
    trainerLocalConfig, setTrainerLocalConfig,
    tubPath,
  } = useStore();

  // Tub candidates for local training (fetched from /trainer/tubs)
  const [tubCandidates, setTubCandidates] = React.useState<TrainerTub[]>([]);
  const [currentTubPath, setCurrentTubPath] = React.useState('');
  // Don't re-autofill after the user has manually edited the tub path
  const tubManuallyEdited = useRef(false);

  // Remote form state (one per SSH target: user's own computer / cloud)
  const [onlineForm, setOnlineForm] = React.useState(trainerOnlineConfig);
  const [myPcForm, setMyPcForm] = React.useState(trainerMyPcConfig);

  // Load remote configs on mount
  useEffect(() => {
    getTrainerConfig('train_online.conf')
      .then((cfg) => {
        const next = {
          host: cfg.host,
          user: cfg.user,
          password: cfg.password,
          remoteDirBase: cfg.remote_dir_base,
          modelName: cfg.model_name,
          pythonPath: cfg.python_path,
        };
        setOnlineForm(next);
        setTrainerOnlineConfig(next);
      })
      .catch(() => {
        // use defaults if file doesn't exist yet
      });
    getTrainerConfig('train_my_pc.conf')
      .then((cfg) => {
        const next = {
          host: cfg.host,
          user: cfg.user,
          password: cfg.password,
          remoteDirBase: cfg.remote_dir_base,
          modelName: cfg.model_name,
          pythonPath: cfg.python_path,
        };
        setMyPcForm(next);
        setTrainerMyPcConfig(next);
      })
      .catch(() => {
        // use defaults if file doesn't exist yet
      });
  }, [setTrainerOnlineConfig, setTrainerMyPcConfig]);

  // Load tub candidates and auto-select the right tub on mount / when paths change
  useEffect(() => {
    let cancelled = false;

    listTrainerTubs(configPath || undefined)
      .then((data) => {
        if (cancelled) return;
        const tubs = data.tubs || [];
        setTubCandidates(tubs);
        setCurrentTubPath(data.current_tub_path || '');

        if (tubManuallyEdited.current) return;

        const candidates = tubs.map((c) => c.relative_path);
        let next: string | null = null;

        // Prefer the tub currently loaded in Tub Manager / Tub Navigator
        const loaded = tubPath || data.current_tub_path;
        if (loaded) {
          const match = tubs.find(
            (c) => c.absolute_path === loaded || c.relative_path === loaded
          );
          if (match) {
            next = match.relative_path;
          }
        }
        // Otherwise pick ./data if it is a tub, or the sole candidate
        if (next === null) {
          if (candidates.includes('./data')) {
            next = './data';
          } else if (candidates.length === 1) {
            next = candidates[0];
          }
        }

        if (next !== null && next !== trainerLocalConfig.tub) {
          setTrainerLocalConfig({ tub: next });
        }
      })
      .catch(() => {
        // Keep current value; tub path stays manually editable
      });

    return () => {
      cancelled = true;
    };
    // trainerLocalConfig.tub intentionally omitted: only auto-fill, never fight user edits
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configPath, tubPath, setTrainerLocalConfig]);

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
    setTrainerOnlineConfig(onlineForm);
    startOnline();
  }, [onlineForm, setTrainerOnlineConfig, startOnline]);

  const handleMyPcStart = useCallback(() => {
    setTrainerMyPcConfig(myPcForm);
    startMyPc();
  }, [myPcForm, setTrainerMyPcConfig, startMyPc]);

  const handleAction = useCallback(() => {
    if (isRunning) {
      stopJob();
    } else if (mode === 'local') {
      handleLocalStart();
    } else if (mode === 'mypc') {
      handleMyPcStart();
    } else {
      handleOnlineStart();
    }
  }, [isRunning, mode, stopJob, handleLocalStart, handleMyPcStart, handleOnlineStart]);

  return (
    <div className="space-y-6">
      {/* 页内标题已上移到统一流程页的 section 头（#178），此处只保留模式切换 */}
      <div className="flex flex-wrap items-center justify-end gap-2">
        <ModeTabs mode={mode} onChange={setMode} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="space-y-6">
          {mode === 'local' ? (
            <LocalConfigForm
              config={trainerLocalConfig}
              onConfigChange={(patch) => {
                if (patch.tub !== undefined) {
                  tubManuallyEdited.current = true;
                }
                setTrainerLocalConfig(patch);
              }}
              tubCandidates={tubCandidates}
              currentTubPath={currentTubPath}
            />
          ) : mode === 'mypc' ? (
            <RemoteConfigForm
              titleKey="trainer.myPcTraining"
              host={myPcForm.host}
              onHostChange={(v) => setMyPcForm((f) => ({ ...f, host: v }))}
              user={myPcForm.user}
              onUserChange={(v) => setMyPcForm((f) => ({ ...f, user: v }))}
              password={myPcForm.password}
              onPasswordChange={(v) => setMyPcForm((f) => ({ ...f, password: v }))}
              remoteDirBase={myPcForm.remoteDirBase}
              onRemoteDirBaseChange={(v) => setMyPcForm((f) => ({ ...f, remoteDirBase: v }))}
              modelName={myPcForm.modelName}
              onModelNameChange={(v) => setMyPcForm((f) => ({ ...f, modelName: v }))}
              pythonPath={myPcForm.pythonPath}
              onPythonPathChange={(v) => setMyPcForm((f) => ({ ...f, pythonPath: v }))}
            />
          ) : (
            <RemoteConfigForm
              host={onlineForm.host}
              onHostChange={(v) => setOnlineForm((f) => ({ ...f, host: v }))}
              user={onlineForm.user}
              onUserChange={(v) => setOnlineForm((f) => ({ ...f, user: v }))}
              password={onlineForm.password}
              onPasswordChange={(v) => setOnlineForm((f) => ({ ...f, password: v }))}
              remoteDirBase={onlineForm.remoteDirBase}
              onRemoteDirBaseChange={(v) => setOnlineForm((f) => ({ ...f, remoteDirBase: v }))}
              modelName={onlineForm.modelName}
              onModelNameChange={(v) => setOnlineForm((f) => ({ ...f, modelName: v }))}
              pythonPath={onlineForm.pythonPath}
              onPythonPathChange={(v) => setOnlineForm((f) => ({ ...f, pythonPath: v }))}
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
              ? t('trainer.stopTraining')
              : mode === 'local'
              ? t('trainer.startLocalTraining')
              : mode === 'mypc'
              ? t('trainer.startMyPcTraining')
              : t('trainer.startCloudTraining')}
          </button>

          <ModelsList />
        </div>
      </div>
    </div>
  );
};
