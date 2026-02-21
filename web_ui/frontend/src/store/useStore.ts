import { create } from 'zustand';

interface TubRecord {
  _index: number;
  _timestamp_ms: number;
  [key: string]: any;
}

interface AppState {
  config: any | null;
  configPath: string;
  tubPath: string;
  records: TubRecord[];
  totalRecords: number;
  currentIndex: number;
  fields: string[];
  isLoading: boolean;
  error: string | null;

  setConfig: (config: any, path: string) => void;
  setTub: (path: string, records: TubRecord[], fields: string[]) => void;
  setRecords: (records: TubRecord[]) => void;
  setCurrentIndex: (index: number | ((prev: number) => number)) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

export const useStore = create<AppState>((set) => ({
  config: null,
  configPath: '/home/dkc/projects/mycar', // Default default
  tubPath: '/home/dkc/projects/mycar/data', // Default default
  records: [],
  totalRecords: 0,
  currentIndex: 0,
  fields: [],
  isLoading: false,
  error: null,

  setConfig: (config, path) => set({ config, configPath: path }),
  setTub: (path, records, fields) => set({ tubPath: path, records, totalRecords: records.length, fields, currentIndex: 0 }),
  setRecords: (records) => set({ records }),
  setCurrentIndex: (index) =>
    set((state) => ({
      currentIndex: typeof index === 'function' ? index(state.currentIndex) : index,
    })),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
}));
