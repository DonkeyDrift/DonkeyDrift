import React from 'react';
import { useUiPrefsStore, type UiSkin } from '../store/useUiPrefsStore';

const SEGMENTS: Array<{ skin: UiSkin; label: string }> = [
  { skin: 'mus4', label: 'ESP32 UI' },
  { skin: 'donkey', label: 'Donkey UI' },
];

export const SkinSwitcher: React.FC = () => {
  const { skin, setSkin } = useUiPrefsStore();

  return (
    <div className="flex items-center gap-1 rounded-full bg-zinc-800 border border-zinc-700 p-1">
      {SEGMENTS.map(({ skin: value, label }) => {
        const active = skin === value;
        return (
          <button
            key={value}
            type="button"
            aria-pressed={active}
            onClick={() => setSkin(value)}
            className={`px-3 py-1 rounded-full text-xs transition-colors ${
              active
                ? 'bg-zinc-950 text-zinc-100'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
};
