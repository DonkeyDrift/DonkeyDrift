import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { MESSAGES } from './messages';

// UI i18n: 'zh' mirrors the original (mixed zh/en) interface verbatim; 'en' is
// the full English translation. On first visit the locale follows the browser
// language (zh* -> zh, everything else -> en). Once the user switches manually
// the choice is persisted in localStorage and takes precedence from then on,
// so it survives browser close and system reboot.
export type UiLanguage = 'zh' | 'en';

export const LANG_STORAGE_KEY = 'donkeydrifter.ui.lang';

type TranslateVars = Record<string, string | number>;

const normalizeLanguage = (lang: string | null): UiLanguage | null =>
  lang === 'zh' || lang === 'en' ? lang : null;

const detectBrowserLanguage = (): UiLanguage => {
  try {
    return (navigator.language || '').toLowerCase().startsWith('zh') ? 'zh' : 'en';
  } catch {
    return 'zh';
  }
};

const readInitialLanguage = (): UiLanguage => {
  try {
    const stored = normalizeLanguage(window.localStorage.getItem(LANG_STORAGE_KEY));
    if (stored) return stored;
  } catch {
    /* localStorage unavailable: fall through to browser detection */
  }
  return detectBrowserLanguage();
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

// <html lang> 必须跟 UI 语言走：写死 en 会让读屏用英文音库念中文，也让 CJK
// 字体回退挑错字面（审计 #24）。模块加载与每次切换都同步一次。
const applyDocumentLang = (lang: UiLanguage): void => {
  try {
    if (typeof document !== 'undefined') document.documentElement.lang = lang;
  } catch {
    /* SSR/测试环境无 document：忽略 */
  }
};

// Non-React access path (services, zustand stores): mirrors the provider state.
let currentLanguage: UiLanguage = readInitialLanguage();
applyDocumentLang(currentLanguage);

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
  const [lang, setLang] = useState<UiLanguage>(readInitialLanguage);

  const setLanguage = useCallback((next: UiLanguage) => {
    currentLanguage = next;
    applyDocumentLang(next);
    setLang(next);
    try {
      window.localStorage.setItem(LANG_STORAGE_KEY, next);
    } catch {
      /* localStorage unavailable: keep in-memory selection */
    }
  }, []);

  // 首屏（含 index.html 内联脚本未覆盖的场景）与语言变化时同步 <html lang>
  useEffect(() => {
    applyDocumentLang(lang);
  }, [lang]);

  const value = useMemo<I18nContextValue>(
    () => ({ lang, setLanguage, t: (key, vars) => translate(lang, key, vars) }),
    [lang, setLanguage],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
};

// Components/hooks use this; the default context value renders zh so existing
// tests that render without the provider keep working unchanged.
export const useTranslation = (): I18nContextValue => useContext(I18nContext);
