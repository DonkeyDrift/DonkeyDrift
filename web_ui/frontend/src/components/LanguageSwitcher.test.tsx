import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { LANG_STORAGE_KEY, LanguageProvider } from '@/i18n';
import { LanguageSwitcher } from './LanguageSwitcher';

const setBrowserLanguage = (lang: string) => {
  Object.defineProperty(window.navigator, 'language', { value: lang, configurable: true });
};

const renderSwitcher = () =>
  render(
    <LanguageProvider>
      <LanguageSwitcher />
    </LanguageProvider>,
  );

describe('LanguageSwitcher', () => {
  beforeEach(() => {
    window.localStorage.clear();
    setBrowserLanguage('zh-CN');
  });

  it('shows 中 and is pressed when the browser language is Chinese', () => {
    renderSwitcher();
    const btn = screen.getByRole('button');
    expect(btn).toHaveTextContent('中');
    expect(btn).toHaveAttribute('aria-pressed', 'true');
  });

  it('follows the browser language and shows EN on first visit', () => {
    setBrowserLanguage('en-US');
    renderSwitcher();
    const btn = screen.getByRole('button');
    expect(btn).toHaveTextContent('EN');
    expect(btn).toHaveAttribute('aria-pressed', 'false');
    // Auto-detection must not persist: only an explicit user switch is stored.
    expect(window.localStorage.getItem(LANG_STORAGE_KEY)).toBeNull();
  });

  it('toggles to English on click and persists the selection', () => {
    renderSwitcher();
    const btn = screen.getByRole('button');
    fireEvent.click(btn);
    expect(btn).toHaveTextContent('EN');
    expect(btn).toHaveAttribute('aria-pressed', 'false');
    expect(window.localStorage.getItem(LANG_STORAGE_KEY)).toBe('en');
  });

  it('toggles back to Chinese on second click', () => {
    renderSwitcher();
    const btn = screen.getByRole('button');
    fireEvent.click(btn); // → en
    fireEvent.click(btn); // → zh
    expect(btn).toHaveTextContent('中');
    expect(btn).toHaveAttribute('aria-pressed', 'true');
    expect(window.localStorage.getItem(LANG_STORAGE_KEY)).toBe('zh');
  });

  it('restores the persisted selection on first render', () => {
    window.localStorage.setItem(LANG_STORAGE_KEY, 'en');
    renderSwitcher();
    expect(screen.getByRole('button')).toHaveTextContent('EN');
  });

  it('lets the persisted selection win over the browser language', () => {
    setBrowserLanguage('en-US');
    window.localStorage.setItem(LANG_STORAGE_KEY, 'zh');
    renderSwitcher();
    expect(screen.getByRole('button')).toHaveTextContent('中');
  });
});
