import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import { DonkeyMenuPage } from './DonkeyMenuPage';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    lang: 'zh',
  }),
}));
vi.mock('@/services/api', () => ({
  getDonkeyUrl: () => 'http://127.0.0.1:8090/',
}));

describe('DonkeyMenuPage 内嵌契约', () => {
  it('iframe src 带 ?embedded=1 与当前语言参数，title 使用 donkeyTitle 文案', () => {
    render(<DonkeyMenuPage />);
    const iframe = document.querySelector('iframe');
    expect(iframe).not.toBeNull();
    expect(iframe?.getAttribute('src')).toBe(
      'http://127.0.0.1:8090/?embedded=1&lang=zh',
    );
    expect(iframe?.getAttribute('title')).toBe(
      'common.enterButtons.donkeyTitle',
    );
  });

  it('iframe 以 no-referrer 加载，避免被 launcher 回环鉴权当跨站请求 401', () => {
    // launcher auth（2026-10-12 P0）对回环客户端要求「干净 Origin」：
    // 无 Origin/Referer 即视为本机直连放行。浏览器 iframe 跨端口导航默认
    // 会发 Referer（DD :5188 → launcher :8090），Origin 永远对不上，菜单
    // 整页被 401 令牌页顶替。referrerpolicy="no-referrer" 把内嵌导航对齐
    // 到「本机直连」信任级（攻击者本可在自己的 iframe 上设同款属性，
    // 不削弱 launcher 的 CSRF/DNS-rebinding 防线）。
    render(<DonkeyMenuPage />);
    const iframe = document.querySelector('iframe');
    expect(iframe).toHaveAttribute('referrerpolicy', 'no-referrer');
  });
});

describe('DonkeyMenuPage 全屏高度（顶栏高度动态化）', () => {
  it('容器高度跟随 Layout 发布的动态 --header-h，而不是硬编码 3.5rem', () => {
    // Layout 用 ResizeObserver 把真实顶栏高度写入 --header-h（桌面单行
    // h-14+边框=57px，移动端两行约 101px）；硬编码 3.5rem(56px) 会让
    // iframe 底边超出视口，外层出现滚动条、launcher 右下角 FAB 被顶出。
    const { container } = render(<DonkeyMenuPage />);
    const wrap = container.firstElementChild as HTMLElement;
    expect(wrap.className).toContain('h-[calc(100vh-var(--header-h))]');
    expect(wrap.className).not.toContain('3.5rem');
  });

  it('支持 dvh 的浏览器改用动态视口高度，避免移动端 100vh 被工具栏裁切', () => {
    const { container } = render(<DonkeyMenuPage />);
    const wrap = container.firstElementChild as HTMLElement;
    expect(wrap.className).toContain(
      'supports-[height:100dvh]:h-[calc(100dvh-var(--header-h))]',
    );
  });
});
