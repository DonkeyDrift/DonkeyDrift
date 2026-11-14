/**
 * TubEditor 常量与纯工具函数。
 *
 * 从 TubEditor.tsx 抽取，便于独立测试与复用。
 */

export const MIN_ZOOM_PERCENT = 100;
export const MAX_ZOOM_PERCENT = 1000;
export const ZOOM_STEP_PERCENT = 100;
export const MAX_UNDO_HISTORY = 10;
export const PLAYHEAD_SCROLL_PADDING_RATIO = 0.15;
export const DRAG_SELECTION_THRESHOLD_PX = 5;
export const MIN_SELECTION_DRAFT_WIDTH_PX = 2;

/** 把全局播放位置写进下方的不受控进度条（value 直写 DOM，播放期零 re-render）。
 *  值一律夹到当前量程（records.length - 1）：越界时浏览器会静默截断显示值，量程变化后
 *  不重写 value 更会让下方进度条停在上一次的位置、与上方录制视频库的播放进度条脱节。 */
export const writeSliderValue = (slider: HTMLInputElement, index: number) => {
  const max = Number(slider.max);
  const upper = Number.isFinite(max) ? max : index;
  const next = String(Math.max(0, Math.min(index, upper)));
  if (slider.value !== next) {
    slider.value = next;
  }
};

/** 从根元素 computed style 解析 CSS 变量颜色；取不到（jsdom/变量缺失）回退 fallback。
 *  canvas 配色按语义角色（转向=--accent、油门=--warn、选区=--ok、删除标记=--bad）
 *  随主题（深/浅）切换自动重取色；fallback 为原深/浅硬编码值。 */
export const cssVarColor = (name: string, fallback: string): string => {
  try {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  } catch {
    return fallback;
  }
};

export type RecordAction = {
  mode: 'delete' | 'restore';
  indexes: number[];
};
