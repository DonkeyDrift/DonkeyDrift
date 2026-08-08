import React from 'react';
import { useTranslation, type UiLanguage } from '@/i18n';

const SEGMENTS: ReadonlyArray<{ value: UiLanguage; label: string }> = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
];

export const LanguageSwitcher: React.FC = () => {
  const { lang, setLanguage } = useTranslation();
  return (
    <div className="flex items-center gap-1 rounded-full bg-zinc-800 border border-zinc-700 p-1">
      {SEGMENTS.map(({ value, label }) => {
        const active = value === lang;
        return (
          <button
            key={value}
            type="button"
            aria-pressed={active}
            onClick={() => setLanguage(value)}
            className={`px-3 py-1 rounded-full text-xs transition-colors ${
              active
                ? 'bg-cyan-600 text-white'
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
