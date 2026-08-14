import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { LANG_STORAGE_KEY, LanguageProvider } from '@/i18n';
import { FabActions } from './FabActions';

const renderFab = () =>
  render(
    <LanguageProvider>
      <FabActions />
    </LanguageProvider>,
  );

const openHelp = () => {
  fireEvent.click(screen.getByRole('button', { name: /快捷入口|Quick actions/ }));
  fireEvent.click(screen.getByRole('button', { name: /功能说明|Feature guide/ }));
};

describe('FabActions i18n', () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.defineProperty(window.navigator, 'language', { value: 'zh-CN', configurable: true });
  });

  it('renders the help modal in Chinese by default', () => {
    renderFab();
    openHelp();
    expect(screen.getByText('快捷键说明')).toBeInTheDocument();
    expect(screen.getByText('播放 / 暂停')).toBeInTheDocument();
  });

  it('renders the help modal in English when en is persisted', () => {
    window.localStorage.setItem(LANG_STORAGE_KEY, 'en');
    renderFab();
    openHelp();
    expect(screen.getByText('Keyboard Shortcuts')).toBeInTheDocument();
    expect(screen.getByText('Play / Pause')).toBeInTheDocument();
  });
});
