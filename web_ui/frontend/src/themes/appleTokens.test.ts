import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Apple 唯一风格的 token 守卫（纯 CSS 断言，不依赖渲染）。
 * 2026-09-20 座舱/Apple 双风格机制移除后：
 * ① 拍平后的调色板（`html.theme-* { --* }`）直接持有 Apple token 值；
 * ② 三份 CSS 不再出现 `ui-apple` 作用域与座舱取值（拍平回归守卫）；
 * ③ 语义色填充与文字是两套值，且文字规则只引用 *-text；
 * ④ SkinSwitcher 相关规则/变量已随组件一并删除。
 *
 * 规格来源：APPLE-SPEC-V1.md §1（灰阶）/ §2（语义双轨）/ §5（材质）/
 * §6（发丝线）；实测对比度见审计报告 B 节。
 */
// 用项目根相对路径读源文件：jsdom 环境下 import.meta.url 不是 file: scheme
const read = (name: string): string => readFileSync(resolve(process.cwd(), 'src/themes', name), 'utf8');

/** 去掉注释后再解析：文件头注释里也写着选择器样例。 */
const stripComments = (css: string): string => css.replace(/\/\*[\s\S]*?\*\//g, '');

/** 取出行首选择器块的声明体（`^selector { ... }`，声明体是扁平的）。 */
const blockOf = (rawCss: string, selector: string): string => {
  const css = stripComments(rawCss);
  const re = new RegExp(`^${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'm');
  const m = re.exec(css);
  expect(m, `选择器 ${selector} 必须存在`).not.toBeNull();
  const open = css.indexOf('{', m!.index);
  const close = css.indexOf('}', open);
  return css.slice(open + 1, close);
};

/** 解析声明体里的 `--name: value;`。 */
const tokensOf = (block: string): Record<string, string> => {
  const out: Record<string, string> = {};
  for (const line of block.split('\n')) {
    const m = line.match(/^\s*(--[\w-]+)\s*:\s*([^;]+);/);
    if (m) out[m[1]] = m[2].trim();
  }
  return out;
};

const mus4 = read('theme-mus4.css');
const light = read('theme-light.css');
const appleDeep = read('apple-deep.css');

// 拍平后唯一调色板：Apple 值已并入基值块，ui-apple 覆写块不复存在
const dark = tokensOf(blockOf(mus4, 'html.theme-mus4 {'));
const lightPal = tokensOf(blockOf(light, 'html.theme-light {'));

describe('拍平后的调色板 = Apple token（规格 §1/§2/§5/§6）', () => {
  it('深色灰阶层级 = 规格实算值（ink2 .85 / ink3 .62 / ink4 .52）', () => {
    expect(dark['--canvas']).toBe('#000000');
    expect(dark['--surface']).toBe('#1c1c1e');
    expect(dark['--ink']).toBe('#f5f5f7');
    expect(dark['--ink2']).toBe('rgba(235, 235, 245, 0.85)');
    expect(dark['--ink3']).toBe('rgba(235, 235, 245, 0.62)');
    expect(dark['--ink4']).toBe('rgba(235, 235, 245, 0.52)');
  });

  it('浅色灰阶层级 = 规格实算值（ink2 .85 / ink3 .72 / ink4 .62）', () => {
    expect(lightPal['--canvas']).toBe('#f5f5f7');
    expect(lightPal['--surface']).toBe('#ffffff');
    expect(lightPal['--ink']).toBe('#1d1d1f');
    expect(lightPal['--ink2']).toBe('rgba(60, 60, 67, 0.85)');
    expect(lightPal['--ink3']).toBe('rgba(60, 60, 67, 0.72)');
    expect(lightPal['--ink4']).toBe('rgba(60, 60, 67, 0.62)');
  });

  it('accent = Apple 蓝（深 #2997ff/#0a84ff，浅 #0066cc/#0071e3）', () => {
    expect(dark['--accent']).toBe('#2997ff');
    expect(dark['--accent-fill']).toBe('#0a84ff');
    expect(lightPal['--accent']).toBe('#0066cc');
    expect(lightPal['--accent-fill']).toBe('#0071e3');
  });

  it('语义色文字变体与规格一致（浅 #1a7f37/#c93400/#d70015，深 #30d158/#ff9f0a/#ff453a）', () => {
    expect(lightPal['--ok-text']).toBe('#1a7f37');
    expect(lightPal['--warn-text']).toBe('#c93400');
    expect(lightPal['--bad-text']).toBe('#d70015');
    expect(dark['--ok-text']).toBe('#30d158');
    expect(dark['--warn-text']).toBe('#ff9f0a');
    expect(dark['--bad-text']).toBe('#ff453a');
  });

  it('发丝线收敛为 2 档：卡片弱档 + Apple separator 强档', () => {
    expect(dark['--hairline']).toBe(dark['--line-soft']);
    expect(dark['--separator']).toBe('rgba(255, 255, 255, 0.16)');
    expect(dark['--line-mid']).toBe(dark['--separator']);
    expect(lightPal['--hairline']).toBe(lightPal['--line-soft']);
    expect(lightPal['--separator']).toBe('rgba(60, 60, 67, 0.29)');
    expect(lightPal['--line-mid']).toBe(lightPal['--separator']);
  });

  it('圆角/字重/标题字距 = Apple 刻度（18/10/9999、600、-0.02em）', () => {
    for (const tokens of [dark, lightPal]) {
      expect(tokens['--r-lg']).toBe('18px');
      expect(tokens['--r-md']).toBe('10px');
      expect(tokens['--r-pill']).toBe('9999px');
      expect(tokens['--w-bold']).toBe('600');
      expect(tokens['--w-extrabold']).toBe('600');
      expect(tokens['--tracking-title']).toBe('-0.02em');
    }
  });

  it('浮层恢复 elevation，卡片仍是 hairline-only', () => {
    for (const tokens of [dark, lightPal]) {
      expect(tokens['--shadow-sm']).toBe('none');
      expect(tokens['--shadow-lg']).toMatch(/^0 8px 30px rgba\(0, 0, 0, /);
      expect(tokens['--shadow-xl']).toMatch(/^0 12px 40px rgba\(0, 0, 0, /);
    }
  });
});

describe('拍平回归守卫（双风格机制已移除）', () => {
  it('三份 CSS 不再出现 ui-apple 作用域', () => {
    for (const [name, css] of [
      ['theme-mus4.css', mus4],
      ['theme-light.css', light],
      ['apple-deep.css', appleDeep],
    ] as const) {
      expect(stripComments(css), `${name} 不应再有 ui-apple 选择器`).not.toMatch(/ui-apple/);
    }
  });

  it('座舱调色板取值不复存在（抽样反断言）', () => {
    // 座舱深色：canvas #101318 / ink #e8edf2 / hairline #344154 / accent #5cc8ff
    expect(dark['--canvas']).not.toBe('#101318');
    expect(dark['--ink']).not.toBe('#e8edf2');
    expect(dark['--hairline']).not.toBe('#344154');
    // 座舱浅色：canvas #eef1f5 / ink #1a2330 / accent #0c9bd6
    expect(lightPal['--canvas']).not.toBe('#eef1f5');
    expect(lightPal['--ink']).not.toBe('#1a2330');
    expect(lightPal['--accent']).not.toBe('#0c9bd6');
  });

  it('SkinSwitcher 规则与分段控件变量已随组件删除', () => {
    for (const css of [mus4, light, appleDeep]) {
      expect(stripComments(css)).not.toMatch(/skin-switcher/);
      expect(stripComments(css)).not.toMatch(/--segment-(thumb|track)/);
    }
  });

  it('灰阶重映射在 apple-deep.css 后置生效（裸 html.theme-* 前缀，同特异度后加载胜出）', () => {
    // theme-*.css 的共享规则体保持 ink4/ink5 基值……
    expect(mus4).toContain('html.theme-mus4 .text-zinc-500,\nhtml.theme-mus4 .placeholder\\:text-zinc-500::placeholder {\n  color: var(--ink4);');
    expect(light).toContain('html.theme-light .text-zinc-600,\nhtml.theme-light .disabled\\:text-zinc-600:disabled {\n  color: var(--ink5);');
    // ……apple-deep.css 用拍平后的同特异度选择器覆盖到 ink3/ink4
    expect(appleDeep).toContain('html.theme-mus4 .text-zinc-500,\nhtml.theme-mus4 .placeholder\\:text-zinc-500::placeholder,\nhtml.theme-light .text-zinc-500,\nhtml.theme-light .placeholder\\:text-zinc-500::placeholder {\n  color: var(--ink3);');
  });
});

describe('语义色双轨（填充 / 文字是两套值）', () => {
  it('同一主题下填充与文字取值不同（浅色）/ 深色保持系统色不变', () => {
    expect(lightPal['--ok-fill']).toBe('#34c759');
    expect(lightPal['--ok-text']).not.toBe(lightPal['--ok-fill']);
    expect(lightPal['--warn']).toBe('#ff9500');
    expect(lightPal['--warn-text']).not.toBe(lightPal['--warn']);
    expect(lightPal['--bad-fill']).toBe('#ff3b30');
    expect(lightPal['--bad-text']).not.toBe(lightPal['--bad-fill']);
    // 深色：系统色本身已过 AA，文字变体等于填充色是有意的
    expect(dark['--ok-text']).toBe(dark['--ok-fill']);
    expect(dark['--bad-text']).toBe(dark['--bad-fill']);
  });

  it('文字规则引用 *-text，填充规则引用 *-fill（两者不串线）', () => {
    expect(appleDeep).toContain('html.theme-light .text-emerald-400,\nhtml.theme-light .text-green-400 {\n  color: var(--ok-text);');
    expect(appleDeep).toContain('html.theme-light .text-red-400,\nhtml.theme-light .text-red-500 {\n  color: var(--bad-text);');
    // 填充仍走原 token（主题里的 .bg-emerald-* / .bg-red-* 规则体未改动）
    expect(mus4).toContain('html.theme-mus4 .bg-emerald-600,\nhtml.theme-mus4 .bg-emerald-500,\nhtml.theme-mus4 .bg-emerald-400 {\n  background-color: var(--ok-fill);');
    expect(mus4).toContain('html.theme-mus4 .text-amber-400,\nhtml.theme-mus4 .text-yellow-400,\nhtml.theme-mus4 .text-yellow-500,\nhtml.theme-mus4 .text-orange-400 {\n  color: var(--warn-text);');
  });

  it('聚焦环、命中区、reduced-* 兜底都在（拍平后选择器为裸 html.theme-*）', () => {
    expect(appleDeep).toMatch(/html\.theme-mus4 :focus-visible[\s\S]{0,200}outline: 3px solid var\(--accent\)/);
    expect(appleDeep).toMatch(/::after \{[\s\S]{0,200}width: max\(100%, 44px\)/);
    expect(appleDeep).toContain('@media (prefers-reduced-transparency: reduce)');
    expect(appleDeep).toContain('@media (prefers-contrast: more)');
    expect(appleDeep).toContain('@media (prefers-reduced-motion: reduce)');
    expect(appleDeep).toContain('@media (forced-colors: active)');
  });
});
