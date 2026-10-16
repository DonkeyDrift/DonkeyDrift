import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Telemetry } from '../../hooks/useDriveWebsocket';
import { useTelemetryStore } from '../../store/useTelemetryStore';
import { useTranslation } from '@/i18n';
import { useResolvedTheme, type ResolvedTheme } from '@/lib/theme';
import { cn } from '../../lib/utils';
import { subscribeRafLoop } from '../../lib/rafLoop';
import { RingSeries, drawRingCurves, type RingCurve } from './telemetryCurveRenderer';

/** 环形缓冲长度（约 1.3 秒 @100Hz）。 */
export const BUFFER_SIZE = 128;

/** 曲线重绘节流（30fps）。自绘 canvas 单次重绘 ~0.1ms 量级，30fps 对趋势曲线已视觉平滑，
 *  同时给 60fps 视频呈现留出帧预算；100Hz 遥测写入只置脏标记，由共享 rAF 循环消费。
 *  （历史：chart.js 时代单次重绘毫秒级，只能 200ms 节流 → 曲线实际 5fps、跳变明显。） */
export const CURVE_REDRAW_MIN_INTERVAL_MS = 33;

/** 曲线绘制性能打点汇总间隔（仅 VITE_CHART_PERF=1 时输出 console.debug）。 */
const PERF_LOG_INTERVAL_MS = 5000;
const PERF_ENABLED = import.meta.env.VITE_CHART_PERF === '1';
const CURVE_LINE_WIDTH = 1.5;

/** 曲线分组：左右分栏各管一组——转向/姿态 vs 油门/加速度。 */
export type CurveGroup = 'steering' | 'throttle';

/** 单条曲线的显示配置。 */
interface CurveConfig {
  /** 显示名的 i18n key（driveViz 命名空间）。 */
  labelKey: string;
  /** CSS 颜色（深色主题 theme-mus4）。 */
  color: string;
  /** 浅色主题（theme-light）下的墨色版本；缺省表示该颜色两主题通用。 */
  lightColor?: string;
  /**
   * 语义 CSS 变量名（如 '--ok'）：设置后优先从根元素 computed style 取色，
   * 随主题（深/浅）切换自动变化；取不到（jsdom 等）回退 color/lightColor。
   * 仅语义角色曲线使用（油门=ok、转向=accent、陀螺仪 Z=bad、陀螺仪 X=warn），
   * 其余数据可视化专用色相保持固定。
   */
  cssVar?: string;
  /** 从 Telemetry 取值的键。 */
  key: keyof Pick<Telemetry, 'gz' | 'steering' | 'throttle' | 'gx' | 'gy' | 'ax' | 'ay' | 'az' | 'pilot_angle' | 'pilot_throttle' | 'rc_steering' | 'rc_throttle'>;
  /** 所属分组。 */
  group: CurveGroup;
  /** 是否默认显示。 */
  defaultOn: boolean;
  /**
   * 显示缩放系数（写入缓冲前乘上）。y 轴固定 [-1, 1]，
   * gyro(rad/s) 与 accel(m/s²) 需要缩放到该量程内才可见。
   */
  scale?: number;
}

/** 从根元素 computed style 解析 CSS 变量颜色；取不到（jsdom/变量缺失）回退 fallback。 */
const cssVarColor = (name: string, fallback: string): string => {
  try {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  } catch {
    return fallback;
  }
};

/** 按当前生效主题取曲线颜色：语义曲线读 CSS 变量，其余浅色用墨色版、缺省回退深色值。 */
const curveColor = (c: CurveConfig, theme: ResolvedTheme): string => {
  const fallback = theme === 'light' ? c.lightColor ?? c.color : c.color;
  return c.cssVar ? cssVarColor(c.cssVar, fallback) : fallback;
};

/** 全部遥测曲线。分组：steering=转向/姿态（RC 转向、Pilot 角度、转向、陀螺仪三轴），
 *  throttle=油门/加速度（RC 油门、Pilot 油门、油门、加速度三轴）。 */
export const CURVES: CurveConfig[] = [
  { labelKey: 'driveViz.curveThrottle', color: '#39d98a', lightColor: '#1fae6b', cssVar: '--ok', key: 'throttle', group: 'throttle', defaultOn: true },
  { labelKey: 'driveViz.curveSteering', color: '#5cc8ff', lightColor: '#0c9bd6', cssVar: '--accent', key: 'steering', group: 'steering', defaultOn: true },
  { labelKey: 'driveViz.curveGyroZ', color: '#ff6b6b', lightColor: '#e5484d', cssVar: '--bad', key: 'gz', group: 'steering', defaultOn: true, scale: 0.2 },
  { labelKey: 'driveViz.curveRcSteering', color: '#2563eb', key: 'rc_steering', group: 'steering', defaultOn: true },
  { labelKey: 'driveViz.curveRcThrottle', color: '#15803d', lightColor: '#14532d', key: 'rc_throttle', group: 'throttle', defaultOn: true },
  { labelKey: 'driveViz.curveGyroX', color: '#ffcc66', lightColor: '#d99a17', cssVar: '--warn', key: 'gx', group: 'steering', defaultOn: true, scale: 0.2 },
  { labelKey: 'driveViz.curveGyroY', color: '#d96bff', lightColor: '#c026d3', key: 'gy', group: 'steering', defaultOn: true, scale: 0.2 },
  { labelKey: 'driveViz.curveAccX', color: '#a3e635', lightColor: '#65a30d', key: 'ax', group: 'throttle', defaultOn: true, scale: 1 / 9.8 },
  { labelKey: 'driveViz.curveAccY', color: '#fb923c', lightColor: '#ea580c', key: 'ay', group: 'throttle', defaultOn: true, scale: 1 / 9.8 },
  { labelKey: 'driveViz.curveAccZ', color: '#f472b6', lightColor: '#db2777', key: 'az', group: 'throttle', defaultOn: true, scale: 1 / 9.8 },
  { labelKey: 'driveViz.curvePilotAngle', color: '#22d3ee', lightColor: '#0891b2', key: 'pilot_angle', group: 'steering', defaultOn: true },
  { labelKey: 'driveViz.curvePilotThrottle', color: '#c084fc', lightColor: '#9333ea', key: 'pilot_throttle', group: 'throttle', defaultOn: true },
];

/** 按分组取曲线子集（保持 CURVES 顺序）。 */
export const curvesByGroup = (group: CurveGroup): CurveConfig[] =>
  CURVES.filter((c) => c.group === group);

interface TelemetryLegendProps {
  /** 当前显示的曲线 key 集合。 */
  visibleKeys: Set<string>;
  /** 切换某条曲线显隐。 */
  onToggle: (key: string) => void;
  /** 全选/全不选本组曲线（select=true 全选、false 全不选）；不传则不渲染「全选」项。 */
  onToggleAll?: (select: boolean) => void;
  /** 只渲染指定分组的曲线；不传则渲染全部曲线。 */
  group?: CurveGroup;
  className?: string;
}

/** 曲线显隐图例（复选框）。覆盖模式下由父组件放在视频画面外部渲染。 */
export const TelemetryLegend: React.FC<TelemetryLegendProps> = ({
  visibleKeys,
  onToggle,
  onToggleAll,
  group,
  className = '',
}) => {
  const { t } = useTranslation();
  const theme = useResolvedTheme();
  const curves = group ? curvesByGroup(group) : CURVES;
  const selectedCount = curves.reduce((n, c) => (visibleKeys.has(c.key as string) ? n + 1 : n), 0);
  const allSelected = curves.length > 0 && selectedCount === curves.length;
  // 半选（部分勾选）时全选框显示 indeterminate 横杠
  const someSelected = selectedCount > 0 && !allSelected;
  const selectAllRef = useRef<HTMLInputElement | null>(null);
  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = someSelected;
  }, [someSelected]);
  return (
    <div className={cn('flex flex-wrap gap-x-3 gap-y-1', className)}>
      {onToggleAll && (
        <label className="flex items-center gap-1 cursor-pointer text-xs font-medium text-slate-300 hover:text-slate-100">
          <input
            ref={selectAllRef}
            type="checkbox"
            checked={allSelected}
            onChange={() => onToggleAll(!allSelected)}
            className={allSelected ? 'accent-blue-500' : 'accent-slate-400'}
          />
          <span>{t('driveViz.selectAll')}</span>
        </label>
      )}
      {curves.map((c) => {
        const on = visibleKeys.has(c.key as string);
        const color = curveColor(c, theme);
        return (
          <label
            key={c.key as string}
            className="flex items-center gap-1 cursor-pointer text-xs text-slate-400 hover:text-slate-200"
          >
            <input
              type="checkbox"
              checked={on}
              onChange={() => onToggle(c.key as string)}
              className="accent-[var(--curve-color)]"
              style={{ ['--curve-color' as string]: color }}
            />
            <span style={{ color: on ? color : undefined }}>{t(c.labelKey)}</span>
          </label>
        );
      })}
    </div>
  );
};

interface TelemetryChartProps {
  className?: string;
  /** 所在 section 是否可见：不可见时停掉订阅与绘制，避免滚走后空转（#178） */
  active?: boolean;
  /** 覆盖模式：贴在视频画面下方的半透明浮层（曲线开关由父组件在画面外部渲染） */
  overlay?: boolean;
  /** 受控：当前显示的曲线 key 集合；不传则组件内部自管 */
  visibleKeys?: Set<string>;
  /** 受控：切换曲线显隐；不传则组件内部自管 */
  onToggleCurve?: (key: string) => void;
  /** 面板标题 i18n key；缺省用 driveViz.chartTitle。 */
  title?: string;
  /** 本实例管理的曲线分组；不传则管理全部曲线。 */
  group?: CurveGroup;
  /** 内部曲线容器高度类，覆盖默认（overlay 下 h-28，否则 h-40）。 */
  chartHeightClassName?: string;
}

/**
 * 实时遥测曲线图，移植自固件 Drifter Console。
 *
 * 性能关键（曲线浮层卡顿优化）：不再用 chart.js——其通用管线单次重绘毫秒级，
 * 只能 200ms 节流（实际 5fps，叠加在 60fps 视频上跳变感明显）。现改为自绘 2D canvas：
 *
 * - 128 点环形缓冲；遥测写入（100Hz，旁路 store 订阅）只推进缓冲 + 置脏标记，
 *   不做绘制、不触发 React 渲染
 * - 绘制由共享 rAF 循环（lib/rafLoop）驱动：脏了才画、按 30fps 节流、与显示刷新对齐，
 *   单次重绘 ~0.1ms 量级
 * - gyro(rad/s) 与 accel(m/s²) 按 CurveConfig.scale 缩放到 y 轴 [-1, 1] 量程
 * - 缺失字段写 NaN，曲线在该点断开
 * - 显隐/主题变化立即重绘一次（用户操作，低频）
 * - 全屏由父组件统一管理整块画面（视频 + 曲线）
 */
export const TelemetryChart = React.memo(function TelemetryChart({
  className = '',
  active = true,
  overlay = false,
  visibleKeys: controlledVisibleKeys,
  onToggleCurve,
  title,
  group,
  chartHeightClassName,
}: TelemetryChartProps) {
  const { t } = useTranslation();
  const theme = useResolvedTheme();
  // 本实例管理的曲线子集
  const curves = useMemo(() => (group ? curvesByGroup(group) : CURVES), [group]);
  // 每条曲线一个环形缓冲；写入走旁路订阅，绘制走共享 rAF（见下方 effect）
  const seriesRef = useRef<Record<string, RingSeries>>({});
  if (Object.keys(seriesRef.current).length === 0) {
    for (const c of curves) {
      seriesRef.current[c.key as string] = new RingSeries(BUFFER_SIZE);
    }
  }
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const ctxRef = useRef<CanvasRenderingContext2D | null>(null);
  // 画布 CSS 像素尺寸（绘制坐标系经 dpr 变换）；0 表示尚未量到尺寸，跳过绘制
  const canvasSizeRef = useRef({ width: 0, height: 0 });
  /** 脏标记：有新数据待画，由 rAF 循环消费。 */
  const dirtyRef = useRef(false);
  const [hasData, setHasData] = useState(false);
  const hasDataRef = useRef(false);
  // 绘制性能打点（仅 PERF_ENABLED 时累计/输出）
  const perfRef = useRef({ count: 0, totalMs: 0, maxMs: 0, windowStart: 0 });

  const [internalVisibleKeys, setInternalVisibleKeys] = useState<Set<string>>(
    () => new Set(curves.filter((c) => c.defaultOn).map((c) => c.key as string)),
  );
  const visibleKeys = controlledVisibleKeys ?? internalVisibleKeys;

  // 当前激活曲线与颜色缓存：显隐/主题/分组变化时重建（rAF 回调经 ref 读最新值，
  // 不随显隐重建订阅）。jsdom 取不到 CSS 变量，curveColor 已内置回退。
  const activeCurves = useMemo(
    () => curves.filter((c) => visibleKeys.has(c.key as string)),
    [curves, visibleKeys],
  );
  const activeCurvesRef = useRef(activeCurves);
  const colorsRef = useRef<Map<string, string>>(new Map());

  const drawNow = useCallback(() => {
    const ctx = ctxRef.current;
    const { width, height } = canvasSizeRef.current;
    if (!ctx || width <= 0 || height <= 0) return;
    const ringCurves: RingCurve[] = [];
    for (const c of activeCurvesRef.current) {
      ringCurves.push({
        color: colorsRef.current.get(c.key as string) ?? c.color,
        series: seriesRef.current[c.key as string],
        lineWidth: CURVE_LINE_WIDTH,
      });
    }
    const start = PERF_ENABLED ? performance.now() : 0;
    drawRingCurves(ctx, width, height, ringCurves);
    if (PERF_ENABLED) {
      const elapsed = performance.now() - start;
      const perf = perfRef.current;
      perf.count += 1;
      perf.totalMs += elapsed;
      perf.maxMs = Math.max(perf.maxMs, elapsed);
    }
  }, []);

  // 激活曲线/颜色缓存更新后立即重绘（用户勾选、主题切换等低频操作的即时反馈）
  useEffect(() => {
    activeCurvesRef.current = activeCurves;
    colorsRef.current = new Map(activeCurves.map((c) => [c.key as string, curveColor(c, theme)]));
    drawNow();
  }, [activeCurves, theme, drawNow]);

  // 画布尺寸：跟随容器（绘制坐标系为 CSS 像素，物理分辨率乘 dpr）。
  // jsdom 无 ResizeObserver，跳过观测（apply 一次即可满足测试）。
  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;
    const apply = () => {
      const rect = wrap.getBoundingClientRect();
      const width = Math.max(0, Math.round(rect.width));
      const height = Math.max(0, Math.round(rect.height));
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        ctxRef.current = null;
        return;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctxRef.current = ctx;
      canvasSizeRef.current = { width, height };
      drawNow();
    };
    apply();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => apply());
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [drawNow]);

  // 遥测写入（100Hz，旁路 store）：只推进环形缓冲 + 置脏，不做绘制/React 更新。
  const writeFrame = useCallback((frame: Telemetry) => {
    let wroteAny = false;
    for (const c of curves) {
      const val = frame[c.key];
      if (typeof val === 'number' && Number.isFinite(val)) wroteAny = true;
    }
    // 全字段缺失不推进缓冲（保留旧数据），与旧 chart.js 方案行为一致
    if (!wroteAny) return;
    for (const c of curves) {
      const val = frame[c.key];
      seriesRef.current[c.key as string].push(
        typeof val === 'number' && Number.isFinite(val) ? val * (c.scale ?? 1) : NaN,
      );
    }
    if (!hasDataRef.current) {
      hasDataRef.current = true;
      setHasData(true);
    }
    dirtyRef.current = true;
  }, [curves]);

  // 数据订阅 + 共享 rAF 绘制循环：脏了才画，按 30fps 节流
  useEffect(() => {
    if (!active) {
      dirtyRef.current = false;
      return;
    }
    const unsubscribe = useTelemetryStore.subscribe((state) => {
      if (state.latest) writeFrame(state.latest);
    });
    // 订阅时若已有最新帧，立即写入一次（便于测试/深链恢复后直接有数据）
    const latest = useTelemetryStore.getState().latest;
    if (latest) writeFrame(latest);

    let lastDrawAt = 0;
    const offRaf = subscribeRafLoop((now) => {
      if (PERF_ENABLED) {
        const perf = perfRef.current;
        if (perf.windowStart === 0) {
          perf.windowStart = now;
        } else if (perf.count > 0 && now - perf.windowStart >= PERF_LOG_INTERVAL_MS) {
          console.debug(
            `[telemetry-chart${group ? `:${group}` : ''}] 绘制 ${perf.count} 次, ` +
            `平均 ${(perf.totalMs / perf.count).toFixed(2)}ms, 峰值 ${perf.maxMs.toFixed(2)}ms, ` +
            `绘制帧率 ${((perf.count * 1000) / (now - perf.windowStart)).toFixed(1)}fps`,
          );
          perf.count = 0;
          perf.totalMs = 0;
          perf.maxMs = 0;
          perf.windowStart = now;
        }
      }
      if (!dirtyRef.current) return;
      if (now - lastDrawAt < CURVE_REDRAW_MIN_INTERVAL_MS) return;
      lastDrawAt = now;
      dirtyRef.current = false;
      drawNow();
    });
    return () => {
      unsubscribe();
      offRaf();
    };
  }, [active, curves, drawNow, group, writeFrame]);

  const toggleCurve = useCallback((key: string) => {
    if (onToggleCurve) {
      onToggleCurve(key);
      return;
    }
    setInternalVisibleKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, [onToggleCurve]);

  // 全选/全不选本组曲线（仅非受控时内部自管；受控时父组件自行渲染全选，这里不重复提供）
  const toggleAll = useCallback((select: boolean) => {
    setInternalVisibleKeys(select ? new Set(curves.map((c) => c.key as string)) : new Set());
  }, [curves]);

  return (
    <div
      className={cn(
        overlay
          ? 'p-2'
          : 'panel rounded-lg border border-slate-700 p-3 bg-slate-900/60',
        className,
      )}
    >
      <div ref={wrapRef} className={cn('relative', chartHeightClassName ?? (overlay ? 'h-28' : 'h-40'))}>
        {/* 自绘曲线画布：透明底叠在视频上，尺寸跟随容器（ResizeObserver） */}
        <canvas ref={canvasRef} className="block h-full w-full" />
      </div>
      {/* 面板标题移到曲线画布下方（贴近画面下沿），左右位置不变 */}
      <div className="flex items-center justify-between mt-2 gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wider text-slate-400">{t(title ?? 'driveViz.chartTitle')}</span>
          {!hasData && <span className="text-xs text-slate-500">{t('driveViz.waitingData')}</span>}
        </div>
      </div>
      {!overlay && (
        <TelemetryLegend
          group={group}
          visibleKeys={visibleKeys}
          onToggle={toggleCurve}
          onToggleAll={controlledVisibleKeys ? undefined : toggleAll}
          className="mt-2"
        />
      )}
    </div>
  );
});
