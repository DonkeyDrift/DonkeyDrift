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
import { Line } from 'react-chartjs-2';
import { Pause, Play, Trash2, Maximize2, Minimize2 } from 'lucide-react';
import { cn } from '../../lib/utils';
import type { Telemetry } from '../../hooks/useDriveWebsocket';
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

/** 环形缓冲长度，与固件 WebConsole 对齐（约 2.6 秒 @100Hz）。 */
const BUFFER_SIZE = 256;

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

/** 默认显示 5 条曲线（油门/转向/陀螺仪Z + RC 手柄输入），对齐固件 MUS4_FW Drifter Console。 */
const CURVES: CurveConfig[] = [
  { labelKey: 'driveViz.curveThrottle', color: '#39d98a', lightColor: '#0ea35e', key: 'throttle', defaultOn: true },
  { labelKey: 'driveViz.curveSteering', color: '#5cc8ff', lightColor: '#0f96d6', key: 'steering', defaultOn: true },
  { labelKey: 'driveViz.curveGyroZ', color: '#ff6b6b', lightColor: '#e03131', key: 'gz', defaultOn: true, scale: 0.2 },
  { labelKey: 'driveViz.curveRcSteering', color: '#2563eb', key: 'rc_steering', defaultOn: true },
  { labelKey: 'driveViz.curveRcThrottle', color: '#15803d', lightColor: '#14532d', key: 'rc_throttle', defaultOn: true },
  { labelKey: 'driveViz.curveGyroX', color: '#ffcc66', lightColor: '#a87900', key: 'gx', defaultOn: false, scale: 0.2 },
  { labelKey: 'driveViz.curveGyroY', color: '#d96bff', lightColor: '#c026d3', key: 'gy', defaultOn: false, scale: 0.2 },
  { labelKey: 'driveViz.curveAccX', color: '#a3e635', lightColor: '#65a30d', key: 'ax', defaultOn: false, scale: 1 / 9.8 },
  { labelKey: 'driveViz.curveAccY', color: '#fb923c', lightColor: '#ea580c', key: 'ay', defaultOn: false, scale: 1 / 9.8 },
  { labelKey: 'driveViz.curveAccZ', color: '#f472b6', lightColor: '#db2777', key: 'az', defaultOn: false, scale: 1 / 9.8 },
  { labelKey: 'driveViz.curvePilotAngle', color: '#22d3ee', lightColor: '#0891b2', key: 'pilot_angle', defaultOn: false },
  { labelKey: 'driveViz.curvePilotThrottle', color: '#c084fc', lightColor: '#9333ea', key: 'pilot_throttle', defaultOn: false },
];

interface TelemetryChartProps {
  /** 最新一帧遥测（由父组件通过 ref 持有，避免高频 setState）。 */
  telemetry: Telemetry | null;
  className?: string;
}

/**
 * 实时遥测曲线图，移植自固件 Drifter Console。
 * - 256 点环形缓冲，requestAnimationFrame 节流重绘（上限 60fps），避免 100Hz 全量 setState
 * - 默认 5 条曲线（Throttle/Steering/GyroZ/RC Steering/RC Throttle），其余通过工具栏开关
 * - gyro(rad/s) 与 accel(m/s²) 按 CurveConfig.scale 缩放到 y 轴 [-1, 1] 量程
 * - 缺失字段（undefined）不写入缓冲，对应曲线自动隐藏
 */
export const TelemetryChart: React.FC<TelemetryChartProps> = ({ telemetry, className = '' }) => {
  const { t } = useTranslation();
  // canvas/图表配色不受皮肤 CSS 控制，订阅主题以重建 chart 配置
  const theme = useResolvedTheme();
  // 各曲线的环形缓冲：number[] 长度恒为 BUFFER_SIZE，未填满处为 NaN
  const buffersRef = useRef<Record<string, number[]>>({});
  const writeIndexRef = useRef(0);
  const filledRef = useRef(0);
  const pausedRef = useRef(false);
  const rafRef = useRef<number | null>(null);
  const latestTelemetryRef = useRef<Telemetry | null>(null);

  const [paused, setPaused] = useState(false);
  const [visibleKeys, setVisibleKeys] = useState<Set<string>>(
    () => new Set(CURVES.filter((c) => c.defaultOn).map((c) => c.key as string)),
  );
  const [fullscreen, setFullscreen] = useState(false);
  // 用于触发 Line 重绘的版本号
  const [renderTick, setRenderTick] = useState(0);
  const [hasData, setHasData] = useState(false);

  // 初始化缓冲
  if (Object.keys(buffersRef.current).length === 0) {
    for (const c of CURVES) {
      buffersRef.current[c.key as string] = new Array(BUFFER_SIZE).fill(NaN);
    }
  }

  // 收到新遥测帧：写入环形缓冲（暂停时丢弃）
  useEffect(() => {
    if (!telemetry) return;
    latestTelemetryRef.current = telemetry;
    if (pausedRef.current) return;

    const buffers = buffersRef.current;
    const idx = writeIndexRef.current;
    let wroteAny = false;
    for (const c of CURVES) {
      const val = telemetry[c.key];
      const buf = buffers[c.key as string];
      if (typeof val === 'number' && Number.isFinite(val)) {
        buf[idx] = val * (c.scale ?? 1);
        wroteAny = true;
      } else {
        // 缺失字段不写入，该位置保持 NaN（曲线在此处断开）
        buf[idx] = NaN;
      }
    }
    if (wroteAny) {
      writeIndexRef.current = (idx + 1) % BUFFER_SIZE;
      filledRef.current = Math.min(filledRef.current + 1, BUFFER_SIZE);
      setHasData(true);
    }
  }, [telemetry]);

  // requestAnimationFrame 节流重绘：合并 100Hz 写入到 60fps 重绘
  useEffect(() => {
    const tick = () => {
      setRenderTick((t) => (t + 1) % 1_000_000);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }
    };
  }, []);

  const handlePauseToggle = useCallback(() => {
    pausedRef.current = !pausedRef.current;
    setPaused(pausedRef.current);
  }, []);

  const handleClear = useCallback(() => {
    const buffers = buffersRef.current;
    for (const c of CURVES) {
      const buf = buffers[c.key as string];
      buf.fill(NaN);
    }
    writeIndexRef.current = 0;
    filledRef.current = 0;
    setHasData(false);
    setRenderTick((t) => (t + 1) % 1_000_000);
  }, []);

  const toggleCurve = useCallback((key: string) => {
    setVisibleKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const toggleFullscreen = useCallback(() => {
    setFullscreen((f) => !f);
  }, []);

  // 构造 chart.js 数据：按写入顺序展开环形缓冲（最旧 -> 最新）
  const chartData = useMemo(() => {
    const buffers = buffersRef.current;
    const writeIdx = writeIndexRef.current;
    const filled = filledRef.current;
    const activeCurves = CURVES.filter((c) => visibleKeys.has(c.key as string));

    const datasets = activeCurves.map((c) => {
      const buf = buffers[c.key as string];
      let ordered: number[];
      if (filled < BUFFER_SIZE) {
        // 未填满：取 [0, filled)
        ordered = buf.slice(0, filled);
      } else {
        // 已填满：从 writeIdx 开始环绕
        ordered = buf.slice(writeIdx).concat(buf.slice(0, writeIdx));
      }
      const color = curveColor(c, theme);
      return {
        label: t(c.labelKey),
        data: ordered,
        borderColor: color,
        backgroundColor: color,
        pointRadius: 0,
        borderWidth: 1.5,
        spanGaps: false, // NaN 处断开曲线
        tension: 0,
      };
    });

    const labels = datasets[0]?.data.map((_, i) => i) ?? [];
    return { labels, datasets };
    // renderTick 驱动重绘；theme 变化时按新主题重建配色
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleKeys, renderTick, theme]);

  const chartOptions = useMemo(
    () => ({
      animation: { duration: 0 } as const,
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { enabled: false },
      },
      scales: {
        x: { display: false },
        y: {
          min: -1,
          max: 1,
          grid: { color: theme === 'light' ? 'rgba(100,116,136,0.25)' : 'rgba(255,255,255,0.06)' },
          ticks: { color: theme === 'light' ? '#5f7185' : '#8fa1b5', font: { size: 10 } },
        },
      },
    }),
    [theme],
  );

  return (
    <div
      className={cn(
        'panel rounded-lg border border-slate-700 p-3 bg-slate-900/60',
        fullscreen && 'fixed inset-0 z-50 rounded-none p-4 bg-slate-950',
        className,
      )}
    >
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wider text-slate-400">{t('driveViz.chartTitle')}</span>
          {!hasData && <span className="text-xs text-slate-500">{t('driveViz.waitingData')}</span>}
          {paused && <span className="text-xs text-amber-400">{t('driveViz.paused')}</span>}
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={handlePauseToggle}
            className="p-1.5 rounded hover:bg-slate-700 text-slate-300"
            title={paused ? t('driveViz.resume') : t('driveViz.pause')}
            aria-label={paused ? t('driveViz.resume') : t('driveViz.pause')}
          >
            {paused ? <Play size={14} /> : <Pause size={14} />}
          </button>
          <button
            type="button"
            onClick={handleClear}
            className="p-1.5 rounded hover:bg-slate-700 text-slate-300"
            title={t('driveViz.clear')}
            aria-label={t('driveViz.clear')}
          >
            <Trash2 size={14} />
          </button>
          <button
            type="button"
            onClick={toggleFullscreen}
            className="p-1.5 rounded hover:bg-slate-700 text-slate-300"
            title={fullscreen ? t('driveViz.exitFullscreen') : t('driveViz.fullscreen')}
            aria-label={fullscreen ? t('driveViz.exitFullscreen') : t('driveViz.fullscreen')}
          >
            {fullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        </div>
      </div>
      <div className={cn('relative', fullscreen ? 'h-[calc(100vh-100px)]' : 'h-48')}>
        <Line data={chartData} options={chartOptions} />
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2">
        {CURVES.map((c) => {
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
                onChange={() => toggleCurve(c.key as string)}
                className="accent-[var(--curve-color)]"
                style={{ ['--curve-color' as string]: color }}
              />
              <span style={{ color: on ? color : undefined }}>{t(c.labelKey)}</span>
            </label>
          );
        })}
      </div>
    </div>
  );
};
