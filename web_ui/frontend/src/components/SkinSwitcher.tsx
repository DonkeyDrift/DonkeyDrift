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
 * 样式跟随风格：座舱象限由 theme-*.css 通用规则自然成形（DC 粗框胶囊容器 +
 * 激活段 canvas 凹陷）；Apple 象限由 theme-*.css 的 `.ui-apple .skin-switcher*`
 * 规则呈 iOS 分段控件观感（直角容器 + 凸起滑块）。
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
      className="skin-switcher flex items-center gap-0.5 rounded-full bg-zinc-800 border border-zinc-700 p-0.5"
    >
      {SEGMENTS.map(({ style, labelKey }) => {
        const active = uiStyle === style;
        return (
          <button
            key={style}
            type="button"
            aria-pressed={active}
            onClick={() => setUiStyle(style)}
            className={`skin-switcher-segment px-2.5 py-1 rounded-full text-xs whitespace-nowrap transition-colors ${
              active
                ? 'bg-zinc-950 text-zinc-100'
                : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            {t(labelKey)}
          </button>
        );
      })}
    </div>
  );
};
