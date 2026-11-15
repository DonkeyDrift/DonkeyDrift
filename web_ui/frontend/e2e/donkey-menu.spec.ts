import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// 本机未下载 playwright 自带 chromium，使用已安装的 Google Chrome
// （与 layout-shell.spec.ts 一致）
test.use({ channel: 'chrome' });

// /#/donkey 是全屏内嵌 launcher 的页面：容器高度必须精确等于
// 「视口 − 实际顶栏高度」。Layout 把真实顶栏高度发布为 --header-h
// （桌面单行 57px，移动端两行约 101px），页面若硬编码扣 3.5rem(56px)，
// iframe 底边会超出视口：外层文档出现滚动条（双滚动），launcher 自带的
// 右下角帮助 FAB 被顶出可视区（移动端约 45px）。

async function measure(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const header = document.querySelector('header')!;
    const iframe = document.querySelector('iframe')!;
    return {
      headerH: header.offsetHeight,
      iframeBottom: Math.round(iframe.getBoundingClientRect().bottom),
      viewportH: window.innerHeight,
      docScrolls: document.documentElement.scrollHeight > window.innerHeight,
    };
  });
}

test.describe('Donkey 菜单内嵌页全屏高度', () => {
  test('桌面端：iframe 底边不超出视口，外层文档不滚动', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/#/donkey', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1200);

    const m = await measure(page);
    expect(m.headerH).toBeGreaterThan(0);
    expect(m.iframeBottom).toBeLessThanOrEqual(m.viewportH);
    expect(m.docScrolls).toBe(false);
  });

  test('移动端：两行顶栏下 iframe 仍铺满可视区且不溢出，launcher 帮助 FAB 可见', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/#/donkey', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1200);

    const m = await measure(page);
    // 移动端顶栏为两行（标题行 + 控件行），高度远大于硬编码的 56px
    expect(m.headerH).toBeGreaterThan(56);
    expect(m.iframeBottom).toBeLessThanOrEqual(m.viewportH);
    expect(m.docScrolls).toBe(false);

    // launcher 页内自带的帮助小点必须完整落在 iframe 可视区内
    await expect
      .poll(
        async () => {
          const frame = page.frames().find((f) => f.url().includes(':8090'));
          if (!frame) return false;
          return frame.evaluate(() => !!document.getElementById('fabToggle'));
        },
        { timeout: 10_000 },
      )
      .toBe(true);
    const frame = page.frames().find((f) => f.url().includes(':8090'))!;
    const fabVisible = await frame.evaluate(() => {
      const fab = document.getElementById('fabToggle')!;
      const r = fab.getBoundingClientRect();
      return r.bottom <= window.innerHeight && r.top >= 0;
    });
    expect(fabVisible).toBe(true);
  });
});

// ── CWD 栏响应式（MENU_HTML 源直测）──────────────────────────────────────
// 运行中的 8090 服务不热载 Python，这里直接从 server.py 提取 MENU_HTML、
// 注入长路径占位（触发窄屏挤压场景），经 route fulfill 以受控 URL（含
// ?embedded=1）渲染真实布局：手机端标签单行、标签+版本号一行、长路径独占
// 一行且不横向溢出；桌面端保持单行不回归。
const LAUNCHER_SERVER_PY = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '../../../donkeycar/launcher/server.py',
);
const LONG_CWD = '/home/dkc/projects/DonkeyDrift_data_backup_20261106';

function buildMenuHtml(): string {
  const src = readFileSync(LAUNCHER_SERVER_PY, 'utf8');
  const m = src.match(/MENU_HTML = r"""([\s\S]*?)"""/);
  if (!m) throw new Error('MENU_HTML not found in server.py');
  return m[1]
    .replaceAll('{{CWD}}', LONG_CWD)
    .replaceAll('{{VERSION}}', 'v0.9.12-e2e');
}

test.describe('CWD 栏响应式（MENU_HTML 源直测）', () => {
  test.beforeEach(async ({ page }) => {
    const html = buildMenuHtml();
    await page.route('http://menu.test/**', (route) =>
      route.fulfill({ contentType: 'text/html; charset=utf-8', body: html }),
    );
  });

  async function cwdGeom(page: import('@playwright/test').Page) {
    return page.evaluate(() => {
      const bar = document.querySelector('.cwdBar') as HTMLElement;
      const label = bar.querySelector('.label') as HTMLElement;
      const p = bar.querySelector('.path') as HTMLElement;
      const badge = bar.querySelector('.versionBadge') as HTMLElement | null;
      const r = (el: Element) => el.getBoundingClientRect();
      return {
        labelH: Math.round(r(label).height),
        labelBottom: r(label).bottom,
        labelTop: r(label).top,
        badge: badge
          ? { top: r(badge).top, bottom: r(badge).bottom }
          : null,
        pathTop: r(p).top,
        pathWidth: r(p).width,
        barH: Math.round(r(bar).height),
        barOverflow: bar.scrollWidth > bar.clientWidth,
        docOverflow: document.documentElement.scrollWidth > window.innerWidth,
      };
    });
  }

  test('移动端内嵌：标签单行，标签+版本号在路径上方，路径独占行且不溢出', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('http://menu.test/menu?embedded=1&lang=zh', {
      waitUntil: 'load',
    });
    await page.waitForTimeout(400);

    const g = await cwdGeom(page);
    // 内嵌模式下版本号被移入 cwdBar
    expect(g.badge).not.toBeNull();
    // 标签单行（行高约 17px，两行会是 ~34px）
    expect(g.labelH).toBeLessThanOrEqual(20);
    // 标签与版本号同在路径上方的一行
    expect(g.labelBottom).toBeLessThanOrEqual(g.pathTop + 1);
    expect(g.badge!.bottom).toBeLessThanOrEqual(g.pathTop + 1);
    // 长路径独占行、在自身行内换行，不横向溢出
    expect(g.pathWidth).toBeGreaterThan(0);
    expect(g.barOverflow).toBe(false);
    expect(g.docOverflow).toBe(false);
  });

  test('移动端独立页：标签单行在上、路径独占一行（版本号仍在顶栏）', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('http://menu.test/menu?lang=zh', { waitUntil: 'load' });
    await page.waitForTimeout(400);

    const g = await cwdGeom(page);
    // 独立页版本号在顶栏，不在 cwdBar 里
    expect(g.badge).toBeNull();
    expect(g.labelH).toBeLessThanOrEqual(20);
    expect(g.labelBottom).toBeLessThanOrEqual(g.pathTop + 1);
    expect(g.pathWidth).toBeGreaterThan(0);
    expect(g.barOverflow).toBe(false);
    expect(g.docOverflow).toBe(false);
  });

  test('桌面内嵌不回归：标签/路径/版本号仍在同一行', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('http://menu.test/menu?embedded=1&lang=zh', {
      waitUntil: 'load',
    });
    await page.waitForTimeout(400);

    const g = await cwdGeom(page);
    expect(g.badge).not.toBeNull();
    // 单行：三者顶边几乎对齐，栏高不超过两行（~34px）
    expect(Math.abs(g.labelTop - g.pathTop)).toBeLessThanOrEqual(2);
    expect(Math.abs(g.badge!.top - g.labelTop)).toBeLessThanOrEqual(8);
    expect(g.barH).toBeLessThanOrEqual(24);
    expect(g.barOverflow).toBe(false);
  });
});
