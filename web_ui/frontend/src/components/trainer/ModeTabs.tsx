import React from 'react';
import { useTranslation } from '@/i18n';

interface ModeTabsProps {
  mode: 'local' | 'online';
  onChange: (mode: 'local' | 'online') => void;
}

export const ModeTabs: React.FC<ModeTabsProps> = ({ mode, onChange }) => {
  const { t } = useTranslation();

  return (
    <div className="flex bg-zinc-900 rounded-full p-1 border border-zinc-800">
      <button
        onClick={() => onChange('local')}
        className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
          mode === 'local'
            ? 'bg-cyan-600 text-white'
            : 'text-zinc-400 hover:text-zinc-200'
        }`}
      >
        {t('trainer.tabLocal')}
      </button>
      <button
        onClick={() => onChange('online')}
        className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
          mode === 'online'
            ? 'bg-cyan-600 text-white'
            : 'text-zinc-400 hover:text-zinc-200'
        }`}
      >
        {t('trainer.tabCloud')}
      </button>
    </div>
  );
};
