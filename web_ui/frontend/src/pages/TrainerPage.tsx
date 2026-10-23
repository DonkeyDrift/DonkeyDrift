import React, { useEffect, useCallback, useMemo, useRef, useState } from 'react';
import { useStore } from '../store/useStore';
import {
  getTrainerConfig,
  getMyPcKnownHosts,
  loadConfig,
  loadMyconfig,
  saveTrainingConfig,
  listTrainerTubs,
  type FamilyTubSession,
  type TrainerTub,
} from '../services/api';
import { AdvancedOptions } from '../components/trainer/AdvancedOptions';
import { LocalConfigForm } from '../components/trainer/LocalConfigForm';
import { RemoteConfigForm } from '../components/trainer/RemoteConfigForm';
import { MyPcProbePanel } from '../components/trainer/MyPcProbePanel';
import { TubSelector } from '../components/trainer/TubSelector';
import { SectionCardTitle } from '../components/ui/SectionCardTitle';
import { SessionFilterPicker, type SessionFilterState } from '../components/trainer/SessionFilterPicker';
import { ProgressPanel } from '../components/trainer/ProgressPanel';
import { LogPanel } from '../components/trainer/LogPanel';
import { ModelsList } from '../components/trainer/ModelsList';
import { useTrainingJob } from '../hooks/useTrainingJob';
import { useMyPcProbe } from '../hooks/useMyPcProbe';
import { useTranslation } from '@/i18n';
import { Cpu, Database, SlidersHorizontal } from 'lucide-react';

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

export const TrainerPage = React.memo(function TrainerPage() {
  const { t } = useTranslation();
  // 训练模式挂全局 store：ModeTabs 在 FlowPage 的 trainer section 头（#178），
  // 切走再切回、或从其它入口进来时模式都保持
  const mode = useStore((s) => s.trainerMode);
  const { job, startLocal, startOnline, startMyPc, resumeMyPc, stopJob, isRunning } = useTrainingJob();
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
  // 录制会话筛选（仅本地训练）：默认不启用 = 训练全部记录
  const [sessionFilter, setSessionFilter] = React.useState<SessionFilterState>({
    enabled: false,
    selected: [],
    isFullSelection: false,
  });
  const resetSessionFilter = useCallback(() => {
    setSessionFilter({ enabled: false, selected: [], isFullSelection: false });
  }, []);
  // 家族会话列表（SessionFilterPicker 上报）：渲染「训练数据范围」摘要用，
  // 与 Picker 共享同一份拉取结果，避免重复请求
  const [sessionFilterList, setSessionFilterList] = useState<{
    path: string;
    sessions: FamilyTubSession[];
  } | null>(null);
  const handleFilterSessionsChange = useCallback(
    (path: string, sessions: FamilyTubSession[]) => {
      setSessionFilterList({ path, sessions });
    },
    []
  );
  // Picker 的拉取路径（与 SessionFilterPicker 内同一规则）：摘要只在
  // 上报路径与当前路径一致时渲染，避免 tub 切换瞬间残留旧家族数据
  const sessionFilterFetchPath = useMemo(() => {
    const candidate = tubCandidates.find(
      (c) =>
        c.relative_path === trainerLocalConfig.tub ||
        c.absolute_path === trainerLocalConfig.tub
    );
    return candidate ? candidate.absolute_path : trainerLocalConfig.tub;
  }, [tubCandidates, trainerLocalConfig.tub]);
  // Don't re-autofill after the user has manually edited the tub path
  const tubManuallyEdited = useRef(false);
  // Don't overwrite mypc host/user/password once the user has typed anything
  const myPcEditedRef = useRef(false);
  // Don't re-autofill the mypc tub once the user has picked one manually
  const myPcTubEditedRef = useRef(false);

  // Remote form state (one per SSH target: user's own computer / cloud)
  const [onlineForm, setOnlineForm] = React.useState(trainerOnlineConfig);
  const [myPcForm, setMyPcForm] = React.useState(trainerMyPcConfig);

  // mypc env readiness: null = 未检测过, false = 检测未就绪, true = 已就绪
  const [myPcEnvReady, setMyPcEnvReady] = useState<boolean | null>(null);
  const myPcProbe = useMyPcProbe();

  // 跑一次环境检测并把结果显示到高级选项里的环境检测面板；
  // 检测通过且后端发现更合适的 python 时自动应用到表单
  const runMyPcProbe = useCallback(async () => {
    const data = await myPcProbe.runProbe({
      host: myPcForm.host,
      user: myPcForm.user,
      password: myPcForm.password,
      remoteDirBase: myPcForm.remoteDirBase,
      pythonPath: myPcForm.pythonPath,
      keyPath: myPcForm.keyPath,
    });
    if (data) {
      setMyPcEnvReady(data.ok);
      if (data.ok && data.python_path && data.python_path !== myPcForm.pythonPath) {
        setMyPcForm((f) => ({ ...f, pythonPath: data.python_path }));
      }
    }
    return data;
  }, [myPcForm, myPcProbe]);

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
          modelType: cfg.model_type ?? 'linear',
          pythonPath: cfg.python_path,
          keyPath: cfg.key_path ?? '',
        };
        setOnlineForm(next);
        setTrainerOnlineConfig(next);
      })
      .catch(() => {
        // use defaults if file doesn't exist yet
      });
    getTrainerConfig('train_my_pc.conf')
      .then((cfg) => {
        setMyPcForm((f) => {
          const next = {
            ...f,
            host: cfg.host,
            user: cfg.user,
            password: cfg.password,
            remoteDirBase: cfg.remote_dir_base,
            modelName: cfg.model_name,
            modelType: cfg.model_type ?? f.modelType,
            pythonPath: cfg.python_path,
            keyPath: cfg.key_path ?? '',
          };
          setTrainerMyPcConfig(next);
          return next;
        });
      })
      .catch(() => {
        // use defaults if file doesn't exist yet
      })
      .then(() => getMyPcKnownHosts())
      .then((hosts) => {
        // 连接记忆自动填充：填「最近使用且当前在线」的电脑
        // （host/user/python_path/remote_dir_base）。
        // 安全约束：历史记录不存密码，密码永远由用户手填。
        const rec = (hosts || []).find((h) => h.reachable);
        if (!rec || myPcEditedRef.current) return;
        setMyPcForm((f) => {
          if (myPcEditedRef.current) return f;
          const next = {
            ...f,
            host: rec.host,
            user: rec.user,
            pythonPath: rec.python_path || f.pythonPath,
            remoteDirBase: rec.remote_dir_base || f.remoteDirBase,
          };
          setTrainerMyPcConfig(next);
          return next;
        });
      })
      .catch(() => {
        // no known hosts or history read failed — leave the form as-is
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
          // tub 由自动填充切换时同样重置会话筛选，避免残留旧 tub 的勾选
          resetSessionFilter();
        }
        if (next !== null && !myPcTubEditedRef.current) {
          setMyPcForm((f) => {
            if (f.tub === next) return f;
            setTrainerMyPcConfig({ tub: next });
            return { ...f, tub: next };
          });
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
  }, [configPath, tubPath, setTrainerLocalConfig, setTrainerMyPcConfig]);

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

    // 勾选子集且启用筛选时按 tub 分组（复合键拆回 {tub绝对路径: [session_id]}）：
    // _session_id 跨 tub 撞名，平坦列表会让 CLI 对每个 tub 都放行同名会话；
    // 全选/未启用不传（家族全量，由后端展开家族 tub 后训练）
    const filterSubset =
      sessionFilter.enabled &&
      !sessionFilter.isFullSelection &&
      sessionFilter.selected.length > 0;
    const sessionFilterPayload = filterSubset
      ? sessionFilter.selected.reduce<Record<string, string[]>>((acc, key) => {
          const sep = key.indexOf('::');
          const tubPath = key.slice(0, sep);
          const sid = key.slice(sep + 2);
          if (tubPath && sid) {
            (acc[tubPath] ??= []).push(sid);
          }
          return acc;
        }, {})
      : undefined;

    startLocal({
      tub: trainerLocalConfig.tub,
      model: `./models/${modelName}`,
      model_type: trainerLocalConfig.modelType,
      transfer: trainerLocalConfig.transfer.trim() || undefined,
      session_filter: sessionFilterPayload,
    });
  }, [trainerLocalConfig, configPath, startLocal, sessionFilter]);

  const handleOnlineStart = useCallback(() => {
    setTrainerOnlineConfig(onlineForm);
    startOnline(onlineForm);
  }, [onlineForm, setTrainerOnlineConfig, startOnline]);

  const handleMyPcStart = useCallback(async () => {
    let cfg = myPcForm;
    if (myPcEnvReady !== true) {
      // 还没检测过（或上次未就绪）：先自动跑环境检测，通过才开始训练
      const data = await runMyPcProbe();
      if (!data) return; // 检测请求失败，错误已显示在环境检测面板
      if (data.python_path && data.python_path !== cfg.pythonPath) {
        cfg = { ...cfg, pythonPath: data.python_path }; // 用检测到的正确路径开始训练
      }
      if (!data.ok) return; // 未就绪：结果显示在环境检测面板，不开始训练
    }
    setTrainerMyPcConfig(cfg);
    startMyPc(cfg);
  }, [myPcForm, myPcEnvReady, runMyPcProbe, setTrainerMyPcConfig, startMyPc]);

  // 断点续训：镜像 handleMyPcStart（含环境检测门槛），但走后端续训接口
  const handleMyPcResume = useCallback(async () => {
    let cfg = myPcForm;
    if (myPcEnvReady !== true) {
      // 还没检测过（或上次未就绪）：先自动跑环境检测，通过才继续训练
      const data = await runMyPcProbe();
      if (!data) return; // 检测请求失败，错误已显示在环境检测面板
      if (data.python_path && data.python_path !== cfg.pythonPath) {
        cfg = { ...cfg, pythonPath: data.python_path }; // 用检测到的正确路径继续训练
      }
      if (!data.ok) return; // 未就绪：结果显示在环境检测面板，不继续训练
    }
    setTrainerMyPcConfig(cfg);
    resumeMyPc(cfg);
  }, [myPcForm, myPcEnvReady, runMyPcProbe, setTrainerMyPcConfig, resumeMyPc]);

  const handleAction = useCallback(async () => {
    if (isRunning) {
      stopJob();
    } else if (mode === 'local') {
      handleLocalStart();
    } else if (mode === 'mypc') {
      // mypc 下已停止的任务「继续」走断点续训；其它模式的「继续」维持全新开始
      if (job?.status === 'stopped') {
        await handleMyPcResume();
      } else {
        await handleMyPcStart();
      }
    } else {
      handleOnlineStart();
    }
  }, [isRunning, mode, job?.status, stopJob, handleLocalStart, handleMyPcStart, handleMyPcResume, handleOnlineStart]);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="space-y-6">
          {mode === 'local' ? (
            <>
              <LocalConfigForm
                config={trainerLocalConfig}
                onConfigChange={(patch) => {
                  if (patch.tub !== undefined) {
                    tubManuallyEdited.current = true;
                    // 切换 tub 后旧 tub 的会话勾选不再有意义，重置筛选状态
                    resetSessionFilter();
                  }
                  setTrainerLocalConfig(patch);
                }}
                tubCandidates={tubCandidates}
                currentTubPath={currentTubPath}
              />
              <SessionFilterPicker
                tub={trainerLocalConfig.tub}
                tubCandidates={tubCandidates}
                enabled={sessionFilter.enabled}
                selected={sessionFilter.selected}
                onChange={setSessionFilter}
                onSessionsChange={handleFilterSessionsChange}
              />
              {/* 训练数据范围摘要：家族布局下「默认全部训练」实际覆盖整个
                  家族（后端展开），此处列出将参与训练的 Tub 段数/帧数，
                  避免只训根 tub 的静默漏训 */}
              {sessionFilterList &&
                sessionFilterList.path === sessionFilterFetchPath &&
                sessionFilterList.sessions.length > 0 &&
                (() => {
                  const filterActive =
                    sessionFilter.enabled && !sessionFilter.isFullSelection;
                  const scoped = filterActive
                    ? sessionFilterList.sessions.filter((s) =>
                        sessionFilter.selected.includes(
                          `${s.tub_path}::${s.session_id}`
                        )
                      )
                    : sessionFilterList.sessions;
                  const scopedTubs = new Set(scoped.map((s) => s.tub_path)).size;
                  const scopedFrames = scoped.reduce(
                    (sum, s) => sum + s.record_count,
                    0
                  );
                  return (
                    <div
                      className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-2"
                      data-testid="training-scope-summary"
                    >
                      <div className="text-sm text-zinc-300">
                        {t('trainer.trainingScopeTitle')}
                      </div>
                      <div className="text-xs text-zinc-400">
                        {filterActive
                          ? t('trainer.trainingScopeFiltered', {
                              segments: scoped.length,
                              tubs: scopedTubs,
                              frames: scopedFrames,
                            })
                          : t('trainer.trainingScopeAll', {
                              tubs: scopedTubs,
                              frames: scopedFrames,
                            })}
                      </div>
                      {filterActive && scoped.length > 0 && (
                        <ul className="max-h-24 overflow-y-auto space-y-1 border-t border-zinc-800 pt-2">
                          {scoped.map((s) => (
                            <li
                              key={`${s.tub_path}::${s.session_id}`}
                              className="text-xs text-zinc-500 font-mono"
                            >
                              {s.tub_name}/{s.session_id}
                              <span className="text-zinc-600">
                                {' '}
                                · {t('trainer.sessionFilterFrames', { count: s.record_count })}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  );
                })()}
            </>
          ) : mode === 'mypc' ? (
            <>
              <RemoteConfigForm
                titleKey="trainer.myPcTraining"
                icon={<Cpu className="w-5 h-5" />}
                compact
                host={myPcForm.host}
                onHostChange={(v) => {
                  myPcEditedRef.current = true;
                  setMyPcForm((f) => ({ ...f, host: v }));
                }}
                user={myPcForm.user}
                onUserChange={(v) => {
                  myPcEditedRef.current = true;
                  setMyPcForm((f) => ({ ...f, user: v }));
                }}
                password={myPcForm.password}
                onPasswordChange={(v) => {
                  myPcEditedRef.current = true;
                  setMyPcForm((f) => ({ ...f, password: v }));
                }}
                remoteDirBase={myPcForm.remoteDirBase}
                onRemoteDirBaseChange={(v) => setMyPcForm((f) => ({ ...f, remoteDirBase: v }))}
                modelName={myPcForm.modelName}
                onModelNameChange={(v) => setMyPcForm((f) => ({ ...f, modelName: v }))}
                modelType={myPcForm.modelType}
                onModelTypeChange={(v) => setMyPcForm((f) => ({ ...f, modelType: v }))}
                pythonPath={myPcForm.pythonPath}
                onPythonPathChange={(v) => setMyPcForm((f) => ({ ...f, pythonPath: v }))}
                keyPath={myPcForm.keyPath}
                onKeyPathChange={(v) => setMyPcForm((f) => ({ ...f, keyPath: v }))}
              />
              <AdvancedOptions
                icon={<SlidersHorizontal className="w-5 h-5" />}
                title={t('trainer.advancedOptions')}
                externalOpen={job?.status === 'running'}
              >
                <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-4">
                  <SectionCardTitle
                    icon={<Database className="w-5 h-5" />}
                    title={t('trainer.trainingData')}
                  />
                  <TubSelector
                    tub={myPcForm.tub}
                    onTubChange={(v) => {
                      myPcTubEditedRef.current = true;
                      setMyPcForm((f) => ({ ...f, tub: v }));
                    }}
                    tubCandidates={tubCandidates}
                    currentTubPath={currentTubPath}
                  />
                </div>
                <MyPcProbePanel
                  host={myPcForm.host}
                  user={myPcForm.user}
                  password={myPcForm.password}
                  pythonPath={myPcForm.pythonPath}
                  keyPath={myPcForm.keyPath}
                  onApplyPythonPath={(v) => setMyPcForm((f) => ({ ...f, pythonPath: v }))}
                  result={myPcProbe.result}
                  loading={myPcProbe.loading}
                  error={myPcProbe.error}
                  onRunProbe={runMyPcProbe}
                />
                <LogPanel job={job} />
              </AdvancedOptions>
            </>
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
              modelType={onlineForm.modelType}
              onModelTypeChange={(v) => setOnlineForm((f) => ({ ...f, modelType: v }))}
              pythonPath={onlineForm.pythonPath}
              onPythonPathChange={(v) => setOnlineForm((f) => ({ ...f, pythonPath: v }))}
              keyPath={onlineForm.keyPath}
              onKeyPathChange={(v) => setOnlineForm((f) => ({ ...f, keyPath: v }))}
            />
          )}

          {mode !== 'mypc' && <LogPanel job={job} />}
        </div>

        <div className="space-y-6">
          <ProgressPanel job={job} />

          <button
            onClick={handleAction}
            disabled={
              (mode === 'mypc' && !isRunning && myPcProbe.loading) ||
              // 已启用会话筛选但一段都没勾选：禁止开始，提示文案在筛选面板里
              (mode === 'local' &&
                !isRunning &&
                sessionFilter.enabled &&
                sessionFilter.selected.length === 0)
            }
            className={`w-full px-4 py-2 rounded-md font-medium transition-colors text-white disabled:opacity-60 disabled:cursor-not-allowed ${
              isRunning
                ? 'bg-red-600 hover:bg-red-700'
                : 'bg-cyan-600 hover:bg-cyan-700'
            }`}
          >
            {isRunning
              ? t('trainer.stopTraining')
              : mode === 'mypc' && myPcProbe.loading
              ? t('trainer.myPcProbeRunning')
              : mode === 'mypc' && job?.status === 'stopped'
              ? t('trainer.resumeTraining')
              : t('trainer.startTraining')}
          </button>

          <ModelsList />
        </div>
      </div>
    </div>
  );
});
