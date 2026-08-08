import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { MESSAGES } from './messages';

// UI i18n: 'zh' is the default locale and mirrors the current (mixed zh/en)
// interface verbatim; 'en' is the full English translation. The selection is
// persisted in localStorage so it survives browser close and system reboot.
export type UiLanguage = 'zh' | 'en';

export const LANG_STORAGE_KEY = 'donkeydrifter.ui.lang';

type TranslateVars = Record<string, string | number>;

const normalizeLanguage = (lang: string | null): UiLanguage => (lang === 'en' ? 'en' : 'zh');

const readStoredLanguage = (): UiLanguage => {
  try {
    return normalizeLanguage(window.localStorage.getItem(LANG_STORAGE_KEY));
  } catch {
    return 'zh';
  }
};

const interpolate = (text: string, vars?: TranslateVars): string => {
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (match, name) =>
    vars[name] !== undefined ? String(vars[name]) : match,
  );
};

// Lookup order: current language -> zh fallback -> the key itself.
const translate = (lang: UiLanguage, key: string, vars?: TranslateVars): string => {
  const text = MESSAGES[lang][key] ?? MESSAGES.zh[key] ?? key;
  return interpolate(text, vars);
};

// Non-React access path (services, zustand stores): mirrors the provider state.
let currentLanguage: UiLanguage = readStoredLanguage();

export const getLanguage = (): UiLanguage => currentLanguage;

// One-shot translation for non-component modules; does not subscribe to changes.
export const t = (key: string, vars?: TranslateVars): string => translate(currentLanguage, key, vars);

interface I18nContextValue {
  lang: UiLanguage;
  setLanguage: (lang: UiLanguage) => void;
  t: (key: string, vars?: TranslateVars) => string;
}

const I18nContext = createContext<I18nContextValue>({
  lang: 'zh',
  setLanguage: () => undefined,
  t: (key, vars) => translate('zh', key, vars),
});

export const LanguageProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [lang, setLang] = useState<UiLanguage>(readStoredLanguage);

  const setLanguage = useCallback((next: UiLanguage) => {
    currentLanguage = next;
    setLang(next);
    try {
      window.localStorage.setItem(LANG_STORAGE_KEY, next);
    } catch {
      /* localStorage unavailable: keep in-memory selection */
    }
  }, []);

  const value = useMemo<I18nContextValue>(
    () => ({ lang, setLanguage, t: (key, vars) => translate(lang, key, vars) }),
    [lang, setLanguage],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
};

// Components/hooks use this; the default context value renders zh so existing
// tests that render without the provider keep working unchanged.
export const useTranslation = (): I18nContextValue => useContext(I18nContext);
