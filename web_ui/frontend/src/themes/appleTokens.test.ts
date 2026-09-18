import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Apple 深化规格 v1 的 token 守卫（纯 CSS 断言，不依赖渲染）：
 * ① apple 象限关键 token 与规格实算值一致；
 * ② 座舱象限（不带 ui-apple）的调色板/共享规则逐值不变（冻结守卫）；
 * ③ 语义色填充与文字是两套值，且文字规则只引用 *-text。
 *
 * 规格来源：APPLE-SPEC-V1.md §1（灰阶）/ §2（语义双轨）/ §5（材质）/
 * §6（发丝线）；实测对比度见审计报告 B 节。
 */
// 用项目根相对路径读源文件：jsdom 环境下 import.meta.url 不是 file: scheme
const read = (name: string): string => readFileSync(resolve(process.cwd(), 'src/themes', name), 'utf8');

/** 去掉注释后再解析：文件头注释里也写着 `html.theme-*.ui-apple { --* }`。 */
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

const darkApple = tokensOf(blockOf(mus4, 'html.theme-mus4.ui-apple {'));
const lightApple = tokensOf(blockOf(light, 'html.theme-light.ui-apple {'));
const darkCockpit = tokensOf(blockOf(mus4, 'html.theme-mus4 {'));
const lightCockpit = tokensOf(blockOf(light, 'html.theme-light {'));

describe('apple 象限 token（规格 §1/§2/§5/§6）', () => {
  it('深色灰阶层级 = 规格实算值（ink2 .85 / ink3 .62 / ink4 .52）', () => {
    expect(darkApple['--ink']).toBe('#f5f5f7');
    expect(darkApple['--ink2']).toBe('rgba(235, 235, 245, 0.85)');
    expect(darkApple['--ink3']).toBe('rgba(235, 235, 245, 0.62)');
    expect(darkApple['--ink4']).toBe('rgba(235, 235, 245, 0.52)');
  });

  it('浅色灰阶层级 = 规格实算值（ink2 .85 / ink3 .72 / ink4 .62）', () => {
    expect(lightApple['--ink']).toBe('#1d1d1f');
    expect(lightApple['--ink2']).toBe('rgba(60, 60, 67, 0.85)');
    expect(lightApple['--ink3']).toBe('rgba(60, 60, 67, 0.72)');
    expect(lightApple['--ink4']).toBe('rgba(60, 60, 67, 0.62)');
  });

  it('语义色文字变体与规格一致（浅 #1a7f37/#c93400/#d70015，深 #30d158/#ff9f0a/#ff453a）', () => {
    expect(lightApple['--ok-text']).toBe('#1a7f37');
    expect(lightApple['--warn-text']).toBe('#c93400');
    expect(lightApple['--bad-text']).toBe('#d70015');
    expect(darkApple['--ok-text']).toBe('#30d158');
    expect(darkApple['--warn-text']).toBe('#ff9f0a');
    expect(darkApple['--bad-text']).toBe('#ff453a');
  });

  it('发丝线收敛为 2 档：卡片弱档 + Apple separator 强档', () => {
    expect(darkApple['--hairline']).toBe(darkApple['--line-soft']);
    expect(darkApple['--separator']).toBe('rgba(255, 255, 255, 0.16)');
    expect(darkApple['--line-mid']).toBe(darkApple['--separator']);
    expect(lightApple['--hairline']).toBe(lightApple['--line-soft']);
    expect(lightApple['--separator']).toBe('rgba(60, 60, 67, 0.29)');
    expect(lightApple['--line-mid']).toBe(lightApple['--separator']);
  });

  it('浮层恢复 elevation，卡片仍是 hairline-only', () => {
    for (const tokens of [darkApple, lightApple]) {
      expect(tokens['--shadow-sm']).toBe('none');
      expect(tokens['--shadow-lg']).toMatch(/^0 8px 30px rgba\(0, 0, 0, /);
      expect(tokens['--shadow-xl']).toMatch(/^0 12px 40px rgba\(0, 0, 0, /);
    }
  });
});

describe('座舱象限冻结守卫（不带 ui-apple 的调色板与共享规则）', () => {
  it('座舱深色调色板逐值不变', () => {
    expect(darkCockpit['--canvas']).toBe('#101318');
    expect(darkCockpit['--surface']).toBe('#171c24');
    expect(darkCockpit['--ink']).toBe('#e8edf2');
    expect(darkCockpit['--ink2']).toBe('#b9c5d3');
    expect(darkCockpit['--ink3']).toBe('#8fa1b5');
    expect(darkCockpit['--ink4']).toBe('#6b7d90');
    expect(darkCockpit['--ink5']).toBe('#55677a');
    expect(darkCockpit['--hairline']).toBe('#344154');
    expect(darkCockpit['--accent']).toBe('#5cc8ff');
    expect(darkCockpit['--shadow-lg']).toMatch(/^0 10px 24px -3px/);
  });

  it('座舱浅色调色板逐值不变', () => {
    expect(lightCockpit['--canvas']).toBe('#eef1f5');
    expect(lightCockpit['--ink']).toBe('#1a2330');
    expect(lightCockpit['--hairline']).toBe('#ccd5df');
    expect(lightCockpit['--accent']).toBe('#0c9bd6');
  });

  it('灰阶重映射不写进共享规则体（否则座舱会被一起改）', () => {
    // theme-*.css 里两象限共用的 .text-zinc-500/.text-zinc-600 必须保持原样
    expect(mus4).toContain('html.theme-mus4 .text-zinc-500,\nhtml.theme-mus4 .placeholder\\:text-zinc-500::placeholder {\n  color: var(--ink4);');
    expect(mus4).toContain('html.theme-mus4 .text-zinc-600,\nhtml.theme-mus4 .disabled\\:text-zinc-600:disabled {\n  color: var(--ink5);');
    expect(light).toContain('html.theme-light .text-zinc-500,\nhtml.theme-light .placeholder\\:text-zinc-500::placeholder {\n  color: var(--ink4);');
    expect(light).toContain('html.theme-light .text-zinc-600,\nhtml.theme-light .disabled\\:text-zinc-600:disabled {\n  color: var(--ink5);');
  });

  it('apple-deep.css 里每次出现主题类都紧跟 ui-apple（不带就不生效）', () => {
    // 不解析选择器（文件里有 @keyframes/@media 嵌套），改为检查不变量：
    // 任何 html.theme-mus4 / html.theme-light 出现处后面必须紧跟 .ui-apple
    const mentions = appleDeep.match(/html\.theme-(mus4|light)/g) ?? [];
    const unguarded = appleDeep.match(/html\.theme-(mus4|light)(?!\.ui-apple)/g) ?? [];
    expect(mentions.length).toBeGreaterThan(40);
    expect(unguarded, `未限定 ui-apple 的选择器片段：${unguarded.join(', ')}`).toEqual([]);
  });
});

describe('语义色双轨（填充 / 文字是两套值）', () => {
  it('同一主题下填充与文字取值不同（浅色）/ 深色保持系统色不变', () => {
    expect(lightApple['--ok-fill']).toBe('#34c759');
    expect(lightApple['--ok-text']).not.toBe(lightApple['--ok-fill']);
    expect(lightApple['--warn']).toBe('#ff9500');
    expect(lightApple['--warn-text']).not.toBe(lightApple['--warn']);
    expect(lightApple['--bad-fill']).toBe('#ff3b30');
    expect(lightApple['--bad-text']).not.toBe(lightApple['--bad-fill']);
    // 深色：系统色本身已过 AA，文字变体等于填充色是有意的
    expect(darkApple['--ok-text']).toBe(darkApple['--ok-fill']);
    expect(darkApple['--bad-text']).toBe(darkApple['--bad-fill']);
  });

  it('文字规则引用 *-text，填充规则引用 *-fill（两者不串线）', () => {
    expect(appleDeep).toContain('html.theme-light.ui-apple .text-emerald-400,\nhtml.theme-light.ui-apple .text-green-400 {\n  color: var(--ok-text);');
    expect(appleDeep).toContain('html.theme-light.ui-apple .text-red-400,\nhtml.theme-light.ui-apple .text-red-500 {\n  color: var(--bad-text);');
    // 填充仍走原 token（主题里的 .bg-emerald-* / .bg-red-* 规则体未改动）
    expect(mus4).toContain('html.theme-mus4 .bg-emerald-600,\nhtml.theme-mus4 .bg-emerald-500,\nhtml.theme-mus4 .bg-emerald-400 {\n  background-color: var(--ok-fill);');
    expect(mus4).toContain('html.theme-mus4 .text-amber-400,\nhtml.theme-mus4 .text-yellow-400,\nhtml.theme-mus4 .text-yellow-500,\nhtml.theme-mus4 .text-orange-400 {\n  color: var(--warn-text);');
  });

  it('聚焦环、命中区、reduced-* 兜底都在 apple 作用域内存在', () => {
    expect(appleDeep).toMatch(/html\.theme-mus4\.ui-apple :focus-visible[\s\S]{0,200}outline: 3px solid var\(--accent\)/);
    expect(appleDeep).toMatch(/::after \{[\s\S]{0,200}width: max\(100%, 44px\)/);
    expect(appleDeep).toContain('@media (prefers-reduced-transparency: reduce)');
    expect(appleDeep).toContain('@media (prefers-contrast: more)');
    expect(appleDeep).toContain('@media (prefers-reduced-motion: reduce)');
    expect(appleDeep).toContain('@media (forced-colors: active)');
  });
});
