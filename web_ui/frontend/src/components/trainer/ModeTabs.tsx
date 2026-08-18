import React from 'react';
import { useTranslation } from '@/i18n';

export type TrainerMode = 'mypc' | 'local' | 'online';

interface ModeTabsProps {
  mode: TrainerMode;
  onChange: (mode: TrainerMode) => void;
}

const MODES: { value: TrainerMode; labelKey: string }[] = [
  { value: 'mypc', labelKey: 'trainer.tabMyPc' },
  { value: 'local', labelKey: 'trainer.tabLocal' },
  { value: 'online', labelKey: 'trainer.tabCloud' },
];

export const ModeTabs: React.FC<ModeTabsProps> = ({ mode, onChange }) => {
  const { t } = useTranslation();

  return (
    <div className="flex bg-zinc-900 rounded-full p-1 border border-zinc-800">
      {MODES.map(({ value, labelKey }) => (
        <button
          key={value}
          onClick={() => onChange(value)}
          className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
            mode === value
              ? 'bg-cyan-600 text-white'
              : 'text-zinc-400 hover:text-zinc-200'
          }`}
        >
          {t(labelKey)}
        </button>
      ))}
    </div>
  );
};
