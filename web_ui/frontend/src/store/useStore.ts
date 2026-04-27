import { create } from 'zustand';
import { persist } from 'zustand/middleware';

const MAX_SELECTION_HISTORY = 120;

interface TubRecord {
  _index: number;
  _timestamp_ms: number;
  [key: string]: unknown;
}

interface AppState {
  config: Record<string, unknown> | null;
  configPath: string;
  tubPath: string;
  originalRecords: TubRecord[];
  records: TubRecord[];
  totalRecords: number;
  tubTotalRecords: number;
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

  setConfig: (config: Record<string, unknown>, path: string) => void;
  setTub: (path: string, records: TubRecord[], fields: string[]) => void;
  setRecords: (records: TubRecord[]) => void;
  setAllRecords: (records: TubRecord[]) => void;
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
}

export const useStore = create<AppState>()(
  persist(
    (set) => ({
      config: null,
      configPath: '/home/dkc/projects/mycar', // Default default
      tubPath: '/home/dkc/projects/mycar/data', // Default default
      originalRecords: [],
      records: [],
      totalRecords: 0,
      tubTotalRecords: 0,
      currentIndex: 0,
      fields: [],
      isLoading: false,
      isDragging: false,
      isPlaying: false,
      isLooping: false,
      error: null,
      isSidePanelOpen: true, // Default open for first time use
      selectionStartIndex: null,
      selectionEndIndex: null,
      selectionHistory: [],
      selectionHistoryIndex: -1,
      onSelectionChange: undefined,

      setConfig: (config, path) => set({ config, configPath: path, error: null, isSidePanelOpen: false }),
      setTub: (path, records, fields) =>
        set({
          tubPath: path,
          records,
          originalRecords: records,
          totalRecords: records.length,
          tubTotalRecords: records.length,
          fields,
          currentIndex: records.length > 0 ? 0 : 0, // Keep at 0 but ensure UI update
          error: null,
          isSidePanelOpen: false,
          isPlaying: false,
        }),
      setRecords: (records) => set({ records, totalRecords: records.length }),
      setAllRecords: (records) =>
        set((state) => ({
          records,
          originalRecords: records,
          totalRecords: records.length,
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
      setSelectionChangeHandler: (handler) => set({ onSelectionChange: handler }),
    }),
    {
      name: 'donkeycar-storage',
      partialize: (state) => ({
        configPath: state.configPath,
        tubPath: state.tubPath,
        isLooping: state.isLooping,
      }),
    }
  )
);
