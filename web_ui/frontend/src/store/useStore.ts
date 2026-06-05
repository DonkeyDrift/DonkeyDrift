import { create } from 'zustand';
import { persist } from 'zustand/middleware';

const MAX_SELECTION_HISTORY = 120;

interface TubRecord {
  _index: number;
  _timestamp_ms: number;
  [key: string]: unknown;
}

export interface TrainingJob {
  id: string;
  mode: 'local' | 'online';
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
}

export interface TrainerOnlineConfig {
  host: string;
  user: string;
  password: string;
  remoteDirBase: string;
  modelName: string;
  pythonPath: string;
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
  fields: string[];
  isLoading: boolean;
  isDragging: boolean;
  isPlaying: boolean;
  isLooping: boolean;
  error: string | null;
  isSidePanelOpen: boolean;
  selectionStartIndex: number | null;
  selectionEndIndex: number | null;
  selectionHistory: { startIndex: number; endIndex: number }[];
  selectionHistoryIndex: number;

  // Trainer state
  trainingJob: TrainingJob | null;
  trainerOnlineConfig: TrainerOnlineConfig;
  trainerLocalConfig: TrainerLocalConfig;

  setConfig: (config: Record<string, unknown>, path: string) => void;
  setTub: (path: string, records: TubRecord[], fields: string[], totalPhysicalRecords?: number, deletedIndexes?: number[]) => void;
  setRecords: (records: TubRecord[]) => void;
  setAllRecords: (records: TubRecord[], totalPhysicalRecords?: number, deletedIndexes?: number[]) => void;
  setDeletedIndexes: (deletedIndexes: number[], totalPhysicalRecords?: number) => void;
  setCurrentIndex: (index: number | ((prev: number) => number)) => void;
  setIsDragging: (isDragging: boolean) => void;
  setIsPlaying: (isPlaying: boolean) => void;
  setIsLooping: (isLooping: boolean) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setSidePanelOpen: (isOpen: boolean) => void;
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
  appendTrainingLog: (lines: string[]) => void;
  updateTrainingProgress: (progress: TrainingJob['progress']) => void;
  finishTrainingJob: (status: 'completed' | 'failed' | 'stopped') => void;
  setTrainerOnlineConfig: (cfg: Partial<TrainerOnlineConfig>) => void;
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
      fields: [],
      isLoading: false,
      isDragging: false,
      isPlaying: false,
      isLooping: false,
      error: null,
      isSidePanelOpen: true,
      selectionStartIndex: null,
      selectionEndIndex: null,
      selectionHistory: [],
      selectionHistoryIndex: -1,
      onSelectionChange: undefined,

      // Trainer defaults
      trainingJob: null,
      trainerOnlineConfig: {
        host: 'haowenpi.com',
        user: 'ubuntu',
        password: 'dkc@2026',
        remoteDirBase: '~/projects',
        modelName: 'model',
        pythonPath: '~/miniconda3/envs/donkey/bin/python',
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

      setConfig: (config, path) => set({ config, configPath: path, error: null, isSidePanelOpen: false }),
      setTub: (path, records, fields, totalPhysicalRecords, deletedIndexes) =>
        set({
          tubPath: path,
          records,
          originalRecords: records,
          totalRecords: records.length,
          tubTotalRecords: records.length,
          totalPhysicalRecords: totalPhysicalRecords ?? records.length,
          deletedIndexes: deletedIndexes ?? [],
          fields,
          currentIndex: records.length > 0 ? 0 : 0,
          error: null,
          isSidePanelOpen: false,
          isPlaying: false,
        }),
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
      setCurrentIndex: (index) =>
        set((state) => ({
          currentIndex: typeof index === 'function' ? index(state.currentIndex) : index,
        })),
      setIsDragging: (isDragging) => set({ isDragging }),
      setIsPlaying: (isPlaying) => set({ isPlaying }),
      setIsLooping: (isLooping) => set({ isLooping }),
      setLoading: (loading) => set({ isLoading: loading }),
      setError: (error) => {
        const shouldOpenPanel = error && (error.includes('not found') || error.includes('Failed'));
        set({ error, isSidePanelOpen: !!shouldOpenPanel });
      },
      setSidePanelOpen: (isOpen) => set({ isSidePanelOpen: isOpen }),
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
      finishTrainingJob: (status) =>
        set((state) => {
          if (!state.trainingJob) return state;
          return {
            trainingJob: {
              ...state.trainingJob,
              status,
              finishedAt: new Date().toISOString(),
            },
          };
        }),
      setTrainerOnlineConfig: (cfg) =>
        set((state) => ({
          trainerOnlineConfig: { ...state.trainerOnlineConfig, ...cfg },
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
        trainerLocalConfig: state.trainerLocalConfig,
      }),
    }
  )
);
