import { test, expect } from '@playwright/test';

// 共享外壳（Layout）顶栏间距回归：Donkey / Drifter Console 高级入口与主导航
// 的间距必须由 nav 的 flex gap 单一来源提供（24px），不随断点/顺序漂移。
// 三个路由共用同一外壳，任取一个即可；这里用 /#/drive（FlowPage）实测。

// 本机未下载 playwright 自带 chromium，使用已安装的 Google Chrome（与手动探针一致）
test.use({ channel: 'chrome' });

test.beforeEach(async ({ page }) => {
  // 与 pilot-arena.spec.ts 同款 API stub：保证 FlowPage 挂载不崩即可
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    let body: unknown = {};
    if (pathname.endsWith('/drift/state')) {
      body = {
        state: 'idle',
        calibration_ready: false,
        camera_running: false,
        beta_deg: null,
        pose: null,
        telemetry_count: 0,
        camera_fps: 0,
        frames_written: 0,
        events: [],
        config: {},
      };
    } else if (pathname.endsWith('/config/load')) {
      body = { config: { DRIVE_LOOP_HZ: 60 } };
    }
    await route.fulfill({ json: body as Record<string, unknown> });
  });
});

test.describe('顶栏高级入口间距（xl：Donkey / Drifter Console 进主导航）', () => {
  test('nav 间距来自 flex gap 且 Donkey→DC 与 DC→Drive 均为 24px', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/drive', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1200);

    const nav = page.locator('header nav').first();
    await expect(nav).toBeVisible();

    // 间距单一来源：nav 上是 gap（columnGap=24px），而非子元素 margin（space-x 时为 normal）
    const columnGap = await nav.evaluate((el) => getComputedStyle(el).columnGap);
    expect(columnGap).toBe('24px');

    const gaps = await page.evaluate(() => {
      const links = [...document.querySelectorAll<HTMLAnchorElement>('header nav a')];
      const find = (txt: string) => links.find((a) => a.textContent?.trim() === txt);
      const donkey = find('Donkey');
      const dc = find('Drifter Console');
      const drive = find('Drive');
      if (!donkey || !dc || !drive) return null;
      const rect = (el: HTMLElement) => el.getBoundingClientRect();
      return {
        donkeyToDc: rect(dc).left - rect(donkey).right,
        dcToDrive: rect(drive).left - rect(dc).right,
      };
    });
    expect(gaps).not.toBeNull();
    expect(gaps!.donkeyToDc).toBe(24);
    expect(gaps!.dcToDrive).toBe(24);
  });

  test('lg 档高级入口收进「⋯」溢出菜单，主导航自身间距仍为 gap 24px', async ({ page }) => {
    await page.setViewportSize({ width: 1100, height: 900 });
    await page.goto('/#/drive', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1200);

    // Donkey / DC 不在导航行
    await expect(page.locator('header nav a', { hasText: 'Donkey' })).toBeHidden();

    const nav = page.locator('header nav').first();
    const columnGap = await nav.evaluate((el) => getComputedStyle(el).columnGap);
    expect(columnGap).toBe('24px');

    // 打开「⋯」菜单，高级入口在面板内（竖排 gap-1）
    await page.locator('header nav button[aria-haspopup="menu"]').click();
    const menuPanel = page.locator('header nav div.absolute');
    await expect(menuPanel.locator('a', { hasText: 'Donkey' })).toBeVisible();
    await expect(menuPanel.locator('a', { hasText: 'Drifter Console' })).toBeVisible();
  });
});

test.describe('移动端汉堡菜单', () => {
  test('菜单项垂直节奏一致：导航项与高级入口同为 py-2.5（10px）', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/#/drive', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1200);

    await page.locator('header button[aria-label="菜单"]').click();
    await page.waitForTimeout(300);

    const paddings = await page.evaluate(() => {
      const menuNav = [...document.querySelectorAll('header nav')].find((n) => n.closest('.lg\\:hidden'))!;
      return [...menuNav.querySelectorAll('a')].map((a) => getComputedStyle(a).paddingTop);
    });
    expect(paddings.length).toBeGreaterThanOrEqual(6);
    for (const p of paddings) expect(p).toBe('10px');
  });
});
