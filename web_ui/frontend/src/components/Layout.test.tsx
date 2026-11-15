import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Layout } from './Layout';

// 顶栏间距回归测试：桌面导航的条目间距必须由 flex gap 单一来源提供，
// 不允许 space-x 子 margin 参与——高级入口包装层是 display:contents，
// space-x 只能给非首个子元素加 margin，首个入口的间距会退化成依赖
// nav 自身 ml-4 的巧合值，重排/换行即碎（见 EnterButtons / Layout 注释）。

vi.mock('@/services/api', () => ({
  launchKimiCodeWeb: vi.fn(),
  launchDsh: vi.fn(),
  launchZcodeRemote: vi.fn(() => Promise.resolve({ status: 'ok' })),
  fetchZcodeRemoteLink: vi.fn(() => Promise.resolve({ status: 'error', error: 'down' })),
  getDonkeyUrl: vi.fn(() => 'http://localhost:8090/'),
}));

// 头部控件有轮询/请求逻辑，与本测试无关，全部换成占位
vi.mock('./FabActions', () => ({ FabActions: () => <div data-testid="fab-actions" /> }));
vi.mock('./ConsoleControls', () => ({
  ConsoleDevToggle: () => <button type="button">dev</button>,
  ConsoleMuteButton: () => <button type="button">mute</button>,
  ConsoleOtaButton: () => <button type="button">ota</button>,
}));
vi.mock('./CarConnectorButton', () => ({ CarConnectorButton: () => <button type="button">cc</button> }));
vi.mock('./VersionBadge', () => ({ VersionBadge: () => <div data-testid="version-badge" /> }));
vi.mock('./ThemeSwitcher', () => ({ ThemeSwitcher: () => <div /> }));
vi.mock('./LanguageSwitcher', () => ({ LanguageSwitcher: () => <div /> }));
vi.mock('./GitHubLink', () => ({ GitHubLink: () => <div /> }));

const renderLayout = () =>
  render(
    <MemoryRouter>
      <Layout>
        <div>page</div>
      </Layout>
    </MemoryRouter>,
  );

describe('Layout 桌面导航间距（flex gap 单一来源）', () => {
  it('nav 条目间距来自 gap-6，不再使用 space-x 子 margin', () => {
    renderLayout();
    const nav = screen.getByRole('navigation');
    expect(nav.className).toContain('gap-6');
    expect(nav.className).not.toContain('space-x-6');
  });

  it('高级入口包装层保留 xl:contents 但不再自带 space-x 间距', () => {
    renderLayout();
    const donkey = screen.getByText('Donkey').closest('a');
    expect(donkey).toBeInTheDocument();
    // 包装层：Donkey / Drifter Console 在 ≥xl 提升为 nav 的 flex item
    const wrapper = donkey?.parentElement;
    expect(wrapper?.className).toContain('xl:contents');
    // 间距只允许来自 nav 的 gap：包装层自带 space-x 会让 DC 吃到
    // margin+gap 双重间距（48px）或依赖 margin 拼间距（脆弱结构）
    expect(wrapper?.className).not.toMatch(/\bspace-x-/);
  });
});
