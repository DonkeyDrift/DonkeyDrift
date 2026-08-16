import React from 'react';
import { useTranslation, type UiLanguage } from '@/i18n';

/**
 * 静音式单按钮语言切换：单击在中/英之间来回切，
 * 按钮文字显示当前语言，首次访问跟随浏览器语言（由 i18n Provider 负责）。
 */
export const LanguageSwitcher: React.FC = () => {
  const { lang, setLanguage } = useTranslation();
  const next: UiLanguage = lang === 'zh' ? 'en' : 'zh';
  return (
    <button
      type="button"
      aria-pressed={lang === 'zh'}
      aria-label={lang === 'zh' ? 'Switch to English' : '切换到中文'}
      onClick={() => setLanguage(next)}
      className="flex items-center justify-center w-8 h-8 rounded-full bg-zinc-800 border border-zinc-700 text-xs font-semibold text-zinc-300 hover:text-zinc-100 transition-colors"
    >
      {lang === 'zh' ? '中' : 'EN'}
    </button>
  );
};
