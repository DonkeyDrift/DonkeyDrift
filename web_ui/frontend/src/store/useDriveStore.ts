import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { api } from '../services/api';

export interface DriveParams {
  pid: {
    kp: number;
    ki: number;
    kd: number;
  };
  recenterRate: number;
  steerRate: number;
  accelRate: number;
  brakeRate: number;
}

export const DEFAULT_PARAMS: DriveParams = {
  pid: { kp: 0.8, ki: 0.0, kd: 0.05 },
  recenterRate: 0.35,
  steerRate: 1.2,
  accelRate: 1.0,
  brakeRate: 1.2,
};

declare global {
  interface Window {
    __driveSaveTimer?: number;
  }
}

interface DriveStore {
  params: DriveParams;
  isLoading: boolean;
  lastSavedAt: string | null;

  // 操作
  setParam: <K extends keyof DriveParams>(key: K, value: DriveParams[K]) => void;
  setPidParam: <K extends keyof DriveParams['pid']>(key: K, value: number) => void;
  resetToDefault: () => void;
  loadFromServer: () => Promise<void>;
  saveToServer: () => Promise<void>;
  importParams: (params: DriveParams) => void;
}

export const useDriveStore = create<DriveStore>()(
  persist(
    (set, get) => ({
      params: DEFAULT_PARAMS,
      isLoading: false,
      lastSavedAt: null,

      setParam: (key, value) => {
        set((state) => ({
          params: { ...state.params, [key]: value },
        }));
        // 防抖保存
        window.clearTimeout(window.__driveSaveTimer);
        window.__driveSaveTimer = window.setTimeout(() => {
          get().saveToServer();
        }, 500);
      },

      setPidParam: (key, value) => {
        set((state) => ({
          params: {
            ...state.params,
            pid: { ...state.params.pid, [key]: value },
          },
        }));
        window.clearTimeout(window.__driveSaveTimer);
        window.__driveSaveTimer = window.setTimeout(() => {
          get().saveToServer();
        }, 500);
      },

      resetToDefault: () => {
        set({ params: DEFAULT_PARAMS });
        setTimeout(() => get().saveToServer(), 100);
      },

      loadFromServer: async () => {
        set({ isLoading: true });
        try {
          const res = await api.get('/drive/params');
          if (res.data?.success && res.data?.params) {
            set({ params: res.data.params, lastSavedAt: res.data.timestamp || null });
          }
        } catch {
          console.warn('加载服务端参数失败，使用本地默认值');
        } finally {
          set({ isLoading: false });
        }
      },

      saveToServer: async () => {
        try {
          const res = await api.post('/drive/params', { params: get().params });
          set({ lastSavedAt: res.data.timestamp || null });
        } catch {
          console.warn('保存服务端参数失败');
        }
      },

      importParams: (params) => {
        set({ params });
        setTimeout(() => get().saveToServer(), 100);
      },
    }),
    {
      name: 'donkey-drive-params',
      partialize: (state) => ({ params: state.params }),
    }
  )
);
