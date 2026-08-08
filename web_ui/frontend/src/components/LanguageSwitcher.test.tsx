import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { LANG_STORAGE_KEY, LanguageProvider } from '@/i18n';
import { LanguageSwitcher } from './LanguageSwitcher';

const renderSwitcher = () =>
  render(
    <LanguageProvider>
      <LanguageSwitcher />
    </LanguageProvider>,
  );

describe('LanguageSwitcher', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('renders 中文 and English segments with 中文 active by default', () => {
    renderSwitcher();
    expect(screen.getByRole('button', { name: '中文' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'English' })).toHaveAttribute('aria-pressed', 'false');
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
});
