import { useEffect, useRef, useState } from 'react';

/**
 * 观测容器内容宽度（ResizeObserver），返回 [ref, width]。
 * observe() 挂载后立即回调一次拿到真实宽度；宽度取整、无变化不触发 re-render。
 * 用于摇杆抽屉的连续缩放布局（docs/issues/008）——缩放比依赖容器实际宽度而非
 * window.innerWidth，避免页面留白/滚动条等因素造成偏差。
 */
export function useElementWidth<T extends HTMLElement>(
  fallback = typeof window === 'undefined' ? 1280 : window.innerWidth,
) {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(fallback);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0].contentRect.width);
      setWidth((prev) => (prev === w ? prev : w));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return [ref, width] as const;
}

/** 同理观测元素高度（如视频行上方工具栏：悬浮模式下面板顶对齐视频顶需让过工具栏） */
export function useElementHeight<T extends HTMLElement>(fallback = 0) {
  const ref = useRef<T | null>(null);
  const [height, setHeight] = useState(fallback);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const h = Math.round(entries[0].contentRect.height);
      setHeight((prev) => (prev === h ? prev : h));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return [ref, height] as const;
}
