import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { LanguageProvider } from '@/i18n';
import { ModeTabs, type TrainerMode } from './ModeTabs';

const setBrowserLanguage = (lang: string) => {
  Object.defineProperty(window.navigator, 'language', { value: lang, configurable: true });
};

const renderTabs = (mode: TrainerMode, onChange: (m: TrainerMode) => void) =>
  render(
    <LanguageProvider>
      <ModeTabs mode={mode} onChange={onChange} />
    </LanguageProvider>,
  );

describe('ModeTabs', () => {
  beforeEach(() => {
    window.localStorage.clear();
    setBrowserLanguage('zh-CN');
  });

  it('renders all three tabs in order (mypc / local / online)', () => {
    renderTabs('local', vi.fn());
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(3);
    expect(buttons[0]).toHaveTextContent('客户端');
    expect(buttons[1]).toHaveTextContent('本机');
    expect(buttons[2]).toHaveTextContent('云端');
  });

  it('highlights the selected mode', () => {
    renderTabs('mypc', vi.fn());
    const buttons = screen.getAllByRole('button');
    expect(buttons[0].className).toContain('bg-cyan-600');
    expect(buttons[1].className).not.toContain('bg-cyan-600');
    expect(buttons[2].className).not.toContain('bg-cyan-600');
  });

  it('calls onChange with the clicked mode', () => {
    const onChange = vi.fn();
    renderTabs('local', onChange);
    fireEvent.click(screen.getByText('云端'));
    expect(onChange).toHaveBeenCalledWith('online');
    fireEvent.click(screen.getByText('客户端'));
    expect(onChange).toHaveBeenCalledWith('mypc');
  });
});
