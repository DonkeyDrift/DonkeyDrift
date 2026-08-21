import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Legend,
  Tooltip,
} from 'chart.js';
import type { Chart, ChartDataset, ChartOptions } from 'chart.js';
import { cn } from '../../lib/utils';
import type { Telemetry } from '../../hooks/useDriveWebsocket';
import { useTelemetryStore } from '../../store/useTelemetryStore';
import { useTranslation } from '@/i18n';
import { useResolvedTheme, type ResolvedTheme } from '@/lib/theme';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Legend,
  Tooltip,
);

/** 环形缓冲长度（约 1.3 秒 @100Hz）。100Hz 遥测下曲线点数越少，重绘越便宜，
 *  while 仍足以呈现转向/油门的实时趋势；#135 第八轮实测 chart.js 重绘是卡顿主因，
 *  更小的缓冲配合 update('none') 可把每次重绘压到亚毫秒级。 */
const BUFFER_SIZE = 128;

/** chart.js 重绘节流间隔（~5fps）。遥测 100Hz，两张图若每帧全量 update 会占满主线程
 *  （#135：点 Donkey/Drift Console 无响应）。5fps 足够看趋势，同时给路由切换留空闲。 */
const CHART_REDRAW_INTERVAL_MS = 200;

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

/** 按当前生效主题取曲线颜色：浅色用墨色版，缺省回退深色值。 */
const curveColor = (c: CurveConfig, theme: ResolvedTheme): string =>
  theme === 'light' ? c.lightColor ?? c.color : c.color;

/** 全部遥测曲线。分组：steering=转向/姿态（RC 转向、Pilot 角度、转向、陀螺仪三轴），
 *  throttle=油门/加速度（RC 油门、Pilot 油门、油门、加速度三轴）。 */
export const CURVES: CurveConfig[] = [
  { labelKey: 'driveViz.curveThrottle', color: '#39d98a', lightColor: '#1fae6b', key: 'throttle', group: 'throttle', defaultOn: true },
  { labelKey: 'driveViz.curveSteering', color: '#5cc8ff', lightColor: '#0c9bd6', key: 'steering', group: 'steering', defaultOn: true },
  { labelKey: 'driveViz.curveGyroZ', color: '#ff6b6b', lightColor: '#e5484d', key: 'gz', group: 'steering', defaultOn: true, scale: 0.2 },
  { labelKey: 'driveViz.curveRcSteering', color: '#2563eb', key: 'rc_steering', group: 'steering', defaultOn: true },
  { labelKey: 'driveViz.curveRcThrottle', color: '#15803d', lightColor: '#14532d', key: 'rc_throttle', group: 'throttle', defaultOn: true },
  { labelKey: 'driveViz.curveGyroX', color: '#ffcc66', lightColor: '#d99a17', key: 'gx', group: 'steering', defaultOn: true, scale: 0.2 },
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
  /** 只渲染指定分组的曲线；不传则渲染全部曲线。 */
  group?: CurveGroup;
  className?: string;
}

/** 曲线显隐图例（复选框）。覆盖模式下由父组件放在视频画面外部渲染。 */
export const TelemetryLegend: React.FC<TelemetryLegendProps> = ({
  visibleKeys,
  onToggle,
  group,
  className = '',
}) => {
  const { t } = useTranslation();
  const theme = useResolvedTheme();
  const curves = group ? curvesByGroup(group) : CURVES;
  return (
    <div className={cn('flex flex-wrap gap-x-3 gap-y-1', className)}>
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
  /** 所在 section 是否可见：不可见时停掉重绘与写入，避免滚走后空转（#178） */
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
 * 性能关键（#135 第八轮）：不再用 react-chartjs-2 的 <Line>，因为后者每次 data 变化都会
 * 重设 chart.options，触发 chart.js 的 _configure + Proxy 全量解析，100Hz 遥测下持续占满
 * 主线程。这里改用原生 Chart.js 持有实例，重绘时直接改写 dataset 数据数组并调用
 * chart.update('none')（跳过动画/布局/配置解析），使每次重绘降至亚毫秒级。
 *
 * - 128 点环形缓冲；有新遥测帧才写入，并按 ~5fps 节流触发重绘
 * - gyro(rad/s) 与 accel(m/s²) 按 CurveConfig.scale 缩放到 y 轴 [-1, 1] 量程
 * - 缺失字段（undefined）不写入缓冲，对应曲线自动隐藏
 * - 暂停/清空/全屏等操作已移除：全屏由父组件统一管理整块画面（视频 + 曲线）
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
  // 各曲线的环形缓冲与显示缓冲：恒为 BUFFER_SIZE 的 number[]，未填满处为 NaN
  const buffersRef = useRef<Record<string, number[]>>({});
  const displayRef = useRef<Record<string, number[]>>({});
  const writeIndexRef = useRef(0);
  const filledRef = useRef(0);
  const lastRenderAtRef = useRef(0);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const chartRef = useRef<Chart<'line'> | null>(null);
  // 当前 chart 内 dataset 对应的曲线（按 dataset 顺序），供 redraw 按索引定位缓冲。
  const activeCurvesRef = useRef<CurveConfig[]>([]);

  const [internalVisibleKeys, setInternalVisibleKeys] = useState<Set<string>>(
    () => new Set(curves.filter((c) => c.defaultOn).map((c) => c.key as string)),
  );
  const visibleKeys = controlledVisibleKeys ?? internalVisibleKeys;
  const [hasData, setHasData] = useState(false);

  // 初始化环形/显示缓冲（仅一次）
  if (Object.keys(buffersRef.current).length === 0) {
    for (const c of curves) {
      buffersRef.current[c.key as string] = new Array(BUFFER_SIZE).fill(NaN);
      displayRef.current[c.key as string] = new Array(BUFFER_SIZE).fill(NaN);
    }
  }

  const chartOptions = useMemo<ChartOptions<'line'>>(
    () => ({
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      normalized: true,
      plugins: {
        legend: { display: false },
        tooltip: { enabled: false },
        title: { display: false },
      },
      scales: {
        x: { display: false },
        y: {
          min: -1,
          max: 1,
          grid: { color: theme === 'light' ? '#dbe2ea' : 'rgba(255,255,255,0.06)' },
          ticks: { color: theme === 'light' ? '#5b6b7d' : '#8fa1b5', font: { size: 10 } },
        },
      },
    }),
    [theme],
  );

  // 把环形缓冲按“最旧→最新”顺序展开到显示缓冲（当前 active 曲线）。数据集持有同一数组引用，
  // 重绘与“勾选新曲线”时都调用它，保证新开启的曲线立刻带上已有历史。
  const syncDisplay = useCallback(() => {
    const buffers = buffersRef.current;
    const display = displayRef.current;
    const writeIdx = writeIndexRef.current;
    const filled = filledRef.current;
    const activeCurves = activeCurvesRef.current;
    for (const c of activeCurves) {
      const buf = buffers[c.key as string];
      const out = display[c.key as string];
      if (filled < BUFFER_SIZE) {
        for (let i = 0; i < BUFFER_SIZE; i++) out[i] = i < filled ? buf[i] : NaN;
      } else {
        for (let i = 0; i < BUFFER_SIZE; i++) out[i] = buf[(writeIdx + i) % BUFFER_SIZE];
      }
    }
  }, []);

  // 创建/重建 chart 实例：仅当曲线集合、显隐、主题变化时重建（用户操作，低频）。
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const activeCurves = curves.filter((c) => visibleKeys.has(c.key as string));
    activeCurvesRef.current = activeCurves;
    const labels = Array.from({ length: BUFFER_SIZE }, (_, i) => i);
    const datasets: ChartDataset<'line', number[]>[] = activeCurves.map((c) => {
      const color = curveColor(c, theme);
      return {
        label: t(c.labelKey),
        data: displayRef.current[c.key as string],
        borderColor: color,
        backgroundColor: color,
        pointRadius: 0,
        borderWidth: 1.5,
        spanGaps: false, // NaN 处断开曲线
        tension: 0,
      };
    });

    chartRef.current?.destroy();
    chartRef.current = new ChartJS(ctx, {
      type: 'line',
      data: { labels, datasets },
      options: chartOptions,
    });
    // 新开启的曲线立刻填充已有历史（例如测试里勾选隐藏曲线后无需等下一帧）。
    syncDisplay();

    return () => {
      chartRef.current?.destroy();
      chartRef.current = null;
    };
  }, [curves, visibleKeys, theme, chartOptions, t, syncDisplay]);

  // 从旁路遥测 feed 订阅新帧并写入环形缓冲；重绘直接改写 chart dataset，不再触发 React 渲染。
  useEffect(() => {
    if (!active) return;

    const redraw = () => {
      const chart = chartRef.current;
      if (!chart) return;
      syncDisplay();
      chart.update('none');
    };

    const writeFrame = (frame: Telemetry) => {
      const buffers = buffersRef.current;
      const idx = writeIndexRef.current;
      let wroteAny = false;
      for (const c of curves) {
        const val = frame[c.key];
        const buf = buffers[c.key as string];
        if (typeof val === 'number' && Number.isFinite(val)) {
          buf[idx] = val * (c.scale ?? 1);
          wroteAny = true;
        } else {
          // 缺失字段不写入，该位置保持 NaN（曲线在此处断开）
          buf[idx] = NaN;
        }
      }
      if (!wroteAny) return;
      writeIndexRef.current = (idx + 1) % BUFFER_SIZE;
      filledRef.current = Math.min(filledRef.current + 1, BUFFER_SIZE);
      setHasData(true);
      // 有新数据才重绘，并按 CHART_REDRAW_INTERVAL_MS 节流（~5fps）。
      const now = performance.now();
      if (now - lastRenderAtRef.current >= CHART_REDRAW_INTERVAL_MS) {
        lastRenderAtRef.current = now;
        redraw();
      }
    };

    const unsubscribe = useTelemetryStore.subscribe((state) => {
      if (state.latest) writeFrame(state.latest);
    });
    // 订阅时若已有最新帧，立即写入一次（便于测试/深链恢复后直接有数据）
    const latest = useTelemetryStore.getState().latest;
    if (latest) writeFrame(latest);

    return unsubscribe;
  }, [active, curves, syncDisplay]);

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

  return (
    <div
      className={cn(
        overlay
          ? 'p-2'
          : 'panel rounded-lg border border-slate-700 p-3 bg-slate-900/60',
        className,
      )}
    >
      <div className="flex items-center justify-between mb-2 gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wider text-slate-400">{t(title ?? 'driveViz.chartTitle')}</span>
          {!hasData && <span className="text-xs text-slate-500">{t('driveViz.waitingData')}</span>}
        </div>
      </div>
      <div className={cn('relative', chartHeightClassName ?? (overlay ? 'h-28' : 'h-40'))}>
        <canvas ref={canvasRef} />
      </div>
      {!overlay && (
        <TelemetryLegend group={group} visibleKeys={visibleKeys} onToggle={toggleCurve} className="mt-2" />
      )}
    </div>
  );
});
