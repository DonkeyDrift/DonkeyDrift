import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { TrainerMode } from '../components/trainer/ModeTabs';

const MAX_SELECTION_HISTORY = 120;

export interface TubRecord {
  _index: number;
  _timestamp_ms: number;
  [key: string]: unknown;
}

export interface TrainingJob {
  id: string;
  mode: 'local' | 'mypc' | 'online';
  status: 'pending' | 'running' | 'completed' | 'failed' | 'stopped';
  progress: {
    currentEpoch: number;
    totalEpochs: number;
    currentStep: number;
    totalSteps: number;
    loss: number | null;
    globalPercent: number;
  };
  logs: string[];
  startedAt: string;
  finishedAt?: string;
  // 失败时的真实原因（SSE status 消息的 error 字段），completed/stopped 为 null
  errorMessage?: string | null;
}

export interface TrainerOnlineConfig {
  host: string;
  user: string;
  password: string;
  remoteDirBase: string;
  modelName: string;
  /** 模型类型（linear/categorical/...），写入 conf 的 model_type */
  modelType: string;
  pythonPath: string;
  /** SSH 私钥路径（可选，与 Car Connector 的 key_path 对齐；留空时用密码认证） */
  keyPath: string;
}

// Connection settings for training on the user's own computer (SSH callback
// from the backend to the machine running the browser, config train_my_pc.conf).
// 比 online 多一个 tub 字段：训练打包哪个 tub（相对 working_dir 的路径）。
export interface TrainerMyPcConfig extends TrainerOnlineConfig {
  tub: string;
}

export interface TrainerLocalConfig {
  tub: string;
  model: string;
  modelType: string;
  transfer: string;
  advancedEnabled: boolean;
  batchSize: number;
  trainTestSplit: number;
  maxEpochs: number;
  showPlot: boolean;
  useEarlyStop: boolean;
  earlyStopPatience: number;
  learningRate: number;
  createTfLite: boolean;
  pruneValLossDegradationLimit: number;
}

interface AppState {
  config: Record<string, unknown> | null;
  configPath: string;
  tubPath: string;
  originalRecords: TubRecord[];
  records: TubRecord[];
  totalRecords: number;
  tubTotalRecords: number;
  totalPhysicalRecords: number;
  deletedIndexes: number[];
  currentIndex: number;
  activeSessionId: string | null;
  activeSessionRecords: TubRecord[];
  fields: string[];
  isLoading: boolean;
  loadedTubPath: string | null;
  tubRefreshToken: number;
  isDragging: boolean;
  isPlaying: boolean;
  isLooping: boolean;
  error: string | null;
  activeDrawer: 'loaders' | 'connectors' | null;
  // 配置自动加载每页面生命周期只尝试一次（ConfigLoader 随抽屉开关反复挂载，
  // 不能用组件内 ref 记忆）；不持久化，刷新页面后重新尝试
  configAutoLoadTried: boolean;
  selectionStartIndex: number | null;
  selectionEndIndex: number | null;
  selectionHistory: { startIndex: number; endIndex: number }[];
  selectionHistoryIndex: number;

  // Trainer state
  trainingJob: TrainingJob | null;
  // 当前正在训练的任务（id + 模式），持久化以支持刷新后恢复进度
  activeTraining: { id: string; mode: TrainingJob['mode'] } | null;
  trainerMode: TrainerMode;
  trainerOnlineConfig: TrainerOnlineConfig;
  trainerMyPcConfig: TrainerMyPcConfig;
  trainerLocalConfig: TrainerLocalConfig;

  setConfig: (config: Record<string, unknown>, path: string) => void;
  setTub: (path: string, records: TubRecord[], fields: string[], totalPhysicalRecords?: number, deletedIndexes?: number[]) => void;
  requestTubRefresh: () => void;
  setRecords: (records: TubRecord[]) => void;
  setAllRecords: (records: TubRecord[], totalPhysicalRecords?: number, deletedIndexes?: number[]) => void;
  setActiveSession: (sessionId: string | null, records: TubRecord[]) => void;
  setDeletedIndexes: (deletedIndexes: number[], totalPhysicalRecords?: number) => void;
  setCurrentIndex: (index: number | ((prev: number) => number)) => void;
  setIsDragging: (isDragging: boolean) => void;
  setIsPlaying: (isPlaying: boolean) => void;
  setIsLooping: (isLooping: boolean) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setActiveDrawer: (drawer: 'loaders' | 'connectors' | null) => void;
  setSelectionRange: (startIndex: number, endIndex: number) => void;
  clearSelectionRange: () => void;
  undoSelectionRange: () => void;
  redoSelectionRange: () => void;
  onSelectionChange?: (startIndex: number | null, endIndex: number | null) => void;
  setSelectionChangeHandler: (
    handler: ((startIndex: number | null, endIndex: number | null) => void) | undefined
  ) => void;

  // Trainer actions
  setTrainingJob: (job: TrainingJob | null) => void;
  setActiveTraining: (id: string, mode: TrainingJob['mode']) => void;
  clearActiveTraining: () => void;
  setTrainerMode: (mode: TrainerMode) => void;
  appendTrainingLog: (lines: string[]) => void;
  updateTrainingProgress: (progress: TrainingJob['progress']) => void;
  finishTrainingJob: (status: 'completed' | 'failed' | 'stopped', errorMessage?: string | null) => void;
  setTrainerOnlineConfig: (cfg: Partial<TrainerOnlineConfig>) => void;
  setTrainerMyPcConfig: (cfg: Partial<TrainerMyPcConfig>) => void;
  setTrainerLocalConfig: (cfg: Partial<TrainerLocalConfig>) => void;
}

export const useStore = create<AppState>()(
  persist(
    (set) => ({
      config: null,
      configPath: '',
      tubPath: '',
      originalRecords: [],
      records: [],
      totalRecords: 0,
      tubTotalRecords: 0,
      totalPhysicalRecords: 0,
      deletedIndexes: [],
      currentIndex: 0,
      activeSessionId: null,
      activeSessionRecords: [],
      fields: [],
      isLoading: false,
      loadedTubPath: null,
      tubRefreshToken: 0,
      isDragging: false,
      isPlaying: false,
      isLooping: false,
      error: null,
      activeDrawer: 'loaders' as 'loaders' | 'connectors' | null,
      configAutoLoadTried: false,
      selectionStartIndex: null,
      selectionEndIndex: null,
      selectionHistory: [],
      selectionHistoryIndex: -1,
      onSelectionChange: undefined,

      // Trainer defaults
      trainingJob: null,
      activeTraining: null,
      trainerMode: 'local',
      trainerOnlineConfig: {
        host: '',
        user: '',
        password: '',
        remoteDirBase: '~/projects',
        modelName: 'model',
        modelType: 'linear',
        pythonPath: '~/miniconda3/envs/donkey/bin/python',
        keyPath: '',
      },
      trainerMyPcConfig: {
        host: '',
        user: '',
        password: '',
        remoteDirBase: '~/projects',
        modelName: 'model',
        modelType: 'linear',
        pythonPath: '',
        keyPath: '',
        tub: './data',
      },
      trainerLocalConfig: {
        tub: './data',
        model: '',
        modelType: 'linear',
        transfer: '',
        advancedEnabled: false,
        batchSize: 128,
        trainTestSplit: 0.8,
        maxEpochs: 100,
        showPlot: true,
        useEarlyStop: true,
        earlyStopPatience: 5,
        learningRate: 0.001,
        createTfLite: true,
        pruneValLossDegradationLimit: 0.2,
      },

      setConfig: (config, path) => set({ config, configPath: path, error: null, activeDrawer: null }),
      setTub: (path, records, fields, totalPhysicalRecords, deletedIndexes) =>
        set({
          tubPath: path,
          loadedTubPath: path,
          records,
          originalRecords: records,
          totalRecords: records.length,
          tubTotalRecords: records.length,
          totalPhysicalRecords: totalPhysicalRecords ?? records.length,
          deletedIndexes: deletedIndexes ?? [],
          fields,
          currentIndex: records.length > 0 ? 0 : 0,
          activeSessionId: null,
          activeSessionRecords: [],
          error: null,
          activeDrawer: null,
          isPlaying: false,
        }),
      // 手动刷新 Tub：清空已加载标记并递增令牌，让 TubManagerPage 重新全量拉取
      requestTubRefresh: () =>
        set((state) => ({ tubRefreshToken: state.tubRefreshToken + 1, loadedTubPath: null })),
      setRecords: (records) => set({ records, totalRecords: records.length }),
      setAllRecords: (records, totalPhysicalRecords, deletedIndexes) =>
        set((state) => ({
          records,
          originalRecords: records,
          totalRecords: records.length,
          totalPhysicalRecords: totalPhysicalRecords ?? state.totalPhysicalRecords,
          deletedIndexes: deletedIndexes ?? state.deletedIndexes,
          currentIndex:
            records.length > 0
              ? Math.max(0, Math.min(state.currentIndex, records.length - 1))
              : 0,
          isPlaying: false,
        })),
      setActiveSession: (sessionId, records) =>
        set({ activeSessionId: sessionId, activeSessionRecords: records }),
      setCurrentIndex: (index) =>
        set((state) => ({
          currentIndex: typeof index === 'function' ? index(state.currentIndex) : index,
        })),
      setIsDragging: (isDragging) => set({ isDragging }),
      setIsPlaying: (isPlaying) => set({ isPlaying }),
      setIsLooping: (isLooping) => set({ isLooping }),
      setLoading: (loading) => set({ isLoading: loading }),
      setError: (error) => {
        if (!error) {
          // 仅清除错误，不联动抽屉：ConfigLoader 挂载时会 setError(null)，
          // 若把 activeDrawer 置空，抽屉会被瞬间关上（老用户点击「加载器」无反应的根因）
          set({ error: null });
          return;
        }
        const shouldOpenPanel = error.includes('not found') || error.includes('Failed');
        set({ error, activeDrawer: shouldOpenPanel ? 'loaders' : null });
      },
      setActiveDrawer: (drawer) => set({ activeDrawer: drawer }),
      setSelectionRange: (startIndex, endIndex) =>
        set((state) => {
          const clampedStart = Math.max(0, Math.min(startIndex, state.totalRecords));
          const clampedEnd = Math.max(clampedStart + 1, Math.min(endIndex, state.totalRecords));
          if (
            state.selectionStartIndex === clampedStart &&
            state.selectionEndIndex === clampedEnd
          ) {
            return state;
          }
          const entry = { startIndex: clampedStart, endIndex: clampedEnd };
          const baseHistory =
            state.selectionHistoryIndex >= 0
              ? state.selectionHistory.slice(0, state.selectionHistoryIndex + 1)
              : [];
          const nextHistory = [...baseHistory, entry].slice(-MAX_SELECTION_HISTORY);
          if (state.onSelectionChange) {
            state.onSelectionChange(clampedStart, clampedEnd);
          }
          return {
            selectionStartIndex: clampedStart,
            selectionEndIndex: clampedEnd,
            selectionHistory: nextHistory,
            selectionHistoryIndex: nextHistory.length - 1,
          };
        }),
      clearSelectionRange: () =>
        set((state) => {
          if (state.onSelectionChange) {
            state.onSelectionChange(null, null);
          }
          return {
            selectionStartIndex: null,
            selectionEndIndex: null,
          };
        }),
      undoSelectionRange: () =>
        set((state) => {
          if (state.selectionHistoryIndex <= 0) {
            return state;
          }
          const nextIndex = state.selectionHistoryIndex - 1;
          const entry = state.selectionHistory[nextIndex];
          if (state.onSelectionChange) {
            state.onSelectionChange(entry.startIndex, entry.endIndex);
          }
          return {
            selectionStartIndex: entry.startIndex,
            selectionEndIndex: entry.endIndex,
            selectionHistoryIndex: nextIndex,
          };
        }),
      redoSelectionRange: () =>
        set((state) => {
          if (
            state.selectionHistoryIndex < 0 ||
            state.selectionHistoryIndex >= state.selectionHistory.length - 1
          ) {
            return state;
          }
          const nextIndex = state.selectionHistoryIndex + 1;
          const entry = state.selectionHistory[nextIndex];
          if (state.onSelectionChange) {
            state.onSelectionChange(entry.startIndex, entry.endIndex);
          }
          return {
            selectionStartIndex: entry.startIndex,
            selectionEndIndex: entry.endIndex,
            selectionHistoryIndex: nextIndex,
          };
        }),
      setDeletedIndexes: (deletedIndexes, totalPhysicalRecords) =>
        set((state) => ({
          deletedIndexes,
          totalPhysicalRecords: totalPhysicalRecords ?? state.totalPhysicalRecords,
        })),
      setSelectionChangeHandler: (handler) => set({ onSelectionChange: handler }),

      // Trainer actions
      setTrainingJob: (job) => set({ trainingJob: job }),
      setActiveTraining: (id, mode) => set({ activeTraining: { id, mode } }),
      clearActiveTraining: () => set({ activeTraining: null }),
      setTrainerMode: (mode) => set({ trainerMode: mode }),
      appendTrainingLog: (lines) =>
        set((state) => {
          if (!state.trainingJob) return state;
          return {
            trainingJob: {
              ...state.trainingJob,
              logs: [...state.trainingJob.logs, ...lines],
            },
          };
        }),
      updateTrainingProgress: (progress) =>
        set((state) => {
          if (!state.trainingJob) return state;
          return {
            trainingJob: {
              ...state.trainingJob,
              progress,
            },
          };
        }),
      finishTrainingJob: (status, errorMessage) =>
        set((state) => {
          if (!state.trainingJob) return state;
          return {
            trainingJob: {
              ...state.trainingJob,
              status,
              finishedAt: new Date().toISOString(),
              errorMessage: errorMessage ?? null,
            },
            activeTraining: null,
          };
        }),
      setTrainerOnlineConfig: (cfg) =>
        set((state) => ({
          trainerOnlineConfig: { ...state.trainerOnlineConfig, ...cfg },
        })),
      setTrainerMyPcConfig: (cfg) =>
        set((state) => ({
          trainerMyPcConfig: { ...state.trainerMyPcConfig, ...cfg },
        })),
      setTrainerLocalConfig: (cfg) =>
        set((state) => ({
          trainerLocalConfig: { ...state.trainerLocalConfig, ...cfg },
        })),
    }),
    {
      name: 'donkeycar-storage',
      partialize: (state) => ({
        configPath: state.configPath,
        tubPath: state.tubPath,
        isLooping: state.isLooping,
        trainerOnlineConfig: state.trainerOnlineConfig,
        trainerMyPcConfig: state.trainerMyPcConfig,
        trainerLocalConfig: state.trainerLocalConfig,
        trainerMode: state.trainerMode,
        activeTraining: state.activeTraining,
      }),
    }
  )
);
