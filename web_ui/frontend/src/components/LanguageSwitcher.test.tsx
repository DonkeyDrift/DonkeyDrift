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

  it('renders 中文 active by default when the browser language is Chinese', () => {
    renderSwitcher();
    expect(screen.getByRole('button', { name: '中文' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('follows the browser language and renders English active on first visit', () => {
    setBrowserLanguage('en-US');
    renderSwitcher();
    expect(screen.getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: '中文' })).toHaveAttribute('aria-pressed', 'false');
    // Auto-detection must not persist: only an explicit user switch is stored.
    expect(window.localStorage.getItem(LANG_STORAGE_KEY)).toBeNull();
  });

  it('switches to English on click and persists the selection', () => {
    renderSwitcher();
    fireEvent.click(screen.getByRole('button', { name: 'English' }));
    expect(screen.getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: '中文' })).toHaveAttribute('aria-pressed', 'false');
    expect(window.localStorage.getItem(LANG_STORAGE_KEY)).toBe('en');
  });

  it('restores the persisted selection on first render', () => {
    window.localStorage.setItem(LANG_STORAGE_KEY, 'en');
    renderSwitcher();
    expect(screen.getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('lets the persisted selection win over the browser language', () => {
    setBrowserLanguage('en-US');
    window.localStorage.setItem(LANG_STORAGE_KEY, 'zh');
    renderSwitcher();
    expect(screen.getByRole('button', { name: '中文' })).toHaveAttribute('aria-pressed', 'true');
  });
});
