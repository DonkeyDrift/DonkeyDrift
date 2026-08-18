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

  // issue #139：语言入口统一为顶栏静音式单按钮，FAB 群不再包含语言按钮/菜单
  it('does not render any language button or menu in the FAB cluster', () => {
    renderFab();
    expect(screen.queryByRole('button', { name: /语言|Language/ })).not.toBeInTheDocument();
    expect(screen.queryByText('🌐')).not.toBeInTheDocument();
    expect(screen.queryByText('中文')).not.toBeInTheDocument();
    expect(screen.queryByText('English')).not.toBeInTheDocument();
  });
});
