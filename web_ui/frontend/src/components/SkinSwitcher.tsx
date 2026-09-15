import React, { useEffect } from 'react';
import { applyUiStyle, readStoredUiStyle, setUiStyle, useUiStyle, type UiStyle } from '@/lib/uistyle';
import { useTranslation } from '@/i18n';

const SEGMENTS: Array<{ style: UiStyle; labelKey: string }> = [
  { style: 'cockpit', labelKey: 'common.uiStyle.cockpit' },
  { style: 'apple', labelKey: 'common.uiStyle.apple' },
];

/**
 * 座舱 / Apple 双风格分段切换器（复活自历史 SkinSwitcher aa48b7ae，皮肤维度
 * 由 useUiPrefsStore 改为 src/lib/uistyle.ts 的 <html> ui-apple class 维度）。
 * 几何两象限统一（统一切换器规格 v1）：28px 轨道 / 2px 内边距 / 24px 滑块 /
 * 12px 字号 600 字重；配色按象限分化——座舱象限靠 Tailwind 类吃 themes/*.css
 * 通用 remap（轨道 --surface2/--hairline、激活段 accent 填充 + on-accent 字），
 * Apple 象限由 theme-*.css 的 `.ui-apple .skin-switcher*` 规则呈 iOS 分段控件
 * 语义（填充灰轨道、透明边、浮起滑块带阴影、hover 只变字色）。
 */
export const SkinSwitcher: React.FC = () => {
  const { t } = useTranslation();
  const uiStyle = useUiStyle();

  // 与 index.html 的首屏内联脚本保持一致:挂载时按 localStorage 再应用一次,
  // 保证 <html> 的 ui-apple class 与持久化选择始终同步。
  useEffect(() => {
    applyUiStyle(readStoredUiStyle());
  }, []);

  return (
    <div
      role="group"
      aria-label={t('common.uiStyle.switchLabel')}
      className="skin-switcher box-border inline-flex h-[28px] items-center gap-[2px] rounded-full border border-zinc-700 bg-zinc-800 p-[2px]"
    >
      {SEGMENTS.map(({ style, labelKey }) => {
        const active = uiStyle === style;
        return (
          <button
            key={style}
            type="button"
            aria-pressed={active}
            onClick={() => setUiStyle(style)}
            className={`skin-switcher-segment h-[24px] cursor-pointer whitespace-nowrap rounded-full border-none bg-transparent px-[12px] text-[12px] font-semibold leading-none transition-colors ${
              active
                ? 'bg-cyan-500 text-white hover:bg-cyan-700'
                : 'text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200'
            }`}
          >
            {t(labelKey)}
          </button>
        );
      })}
    </div>
  );
};
