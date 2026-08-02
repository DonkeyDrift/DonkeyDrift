import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type UiSkin = 'donkey' | 'mus4';

interface UiPrefsState {
  skin: UiSkin;
  setSkin: (skin: UiSkin) => void;
}

export const useUiPrefsStore = create<UiPrefsState>()(
  persist(
    (set) => ({
      skin: 'donkey',
      setSkin: (skin) => set({ skin }),
    }),
    {
      name: 'donkey-ui-prefs',
      partialize: (state) => ({ skin: state.skin }),
    }
  )
);
