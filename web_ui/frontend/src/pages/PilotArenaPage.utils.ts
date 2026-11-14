/**
 * PilotArenaPage 常量与纯工具函数。
 *
 * 从 PilotArenaPage.tsx 抽取，便于独立测试与复用。
 */

import type { ResolvedTheme } from "@/lib/theme";
import type { ArenaPilot, ArenaModel } from "@/services/api";

export type ViewerState = {
  localId: string;
  modelType: string;
  modelPath: string;
  pilot?: ArenaPilot;
  models: ArenaModel[];
  prediction?: { angle: number; throttle: number };
  lastEvaluatedIndex?: number;
  playbackFps: number;
  inferenceFps: number;
  loading: boolean;
  error?: string;
};

export const defaultViewer = (): ViewerState => ({
  localId: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
  modelType: 'tflite_linear',
  modelPath: '',
  models: [],
  playbackFps: 0,
  inferenceFps: 0,
  loading: false,
});








export const TRANSFORMATION_OPTIONS = [
  'TRAPEZE',
  'CROP',
  'RGB2BGR',
  'BGR2RGB',
  'RGB2HSV',
  'HSV2RGB',
  'BGR2HSV',
  'HSV2BGR',
  'RGB2GRAY',
  'BGR2GRAY',
  'HSV2GRAY',
  'GRAY2RGB',
  'GRAY2BGR',
  'CANNY',
  'BLUR',
  'RESIZE',
  'SCALE',
];

export const ARENA_IMAGE_CACHE_LIMIT = 40;
export const ARENA_IMAGE_MAX_IN_FLIGHT = 1;
export const ARENA_IMAGE_MIN_INTERVAL_MS = 16;
// 播放前瞻预取帧数：当前帧显示的同时提前加载其后 N 帧（60Hz 下 N=12 ≈ 200ms），
// 把逐帧 HTTP 取图的 RTT 隐藏在读秒之前——不预取时当前帧到显示时刻才发起请求，
// 响应成批到达造成画面忽停忽跳（卡顿感的主因，与播放/推理 FPS 计数无关）。
export const ARENA_IMAGE_PREFETCH_FRAMES = 12;
// 播放中预测数值读数的节流间隔：canvas 上的控制线每 rAF 直读 ref 缓存（不走 React），
// React state 仅喂角/油门的数字读数，53 次/秒的响应若每次都 setState 会带崩整页
// 重渲染（含 Chart.js 全量重绘），10Hz 对人眼读数足够。
export const ARENA_PREDICTION_DISPLAY_INTERVAL_MS = 100;
// 推理评估节流下限。后端曾每帧重载 config(≈75ms)，故原用 250ms 防堆积；config 已缓存后
// 放宽到与逐帧播放一致(≤60Hz)，推理节奏改由实际能力决定。可用 ARENA_PREDICTION_INTERVAL_MS 调大。
export const ARENA_PREDICTION_MIN_INTERVAL_MS = 16;
export const ARENA_BATCH_PREFETCH_MIN_INTERVAL_MS = 1000;
// 每 viewer 推理并发默认 2：单请求 RTT 含浏览器/网络开销（真机实测本机回环 ~8ms、
// 经浏览器访问更高），并发 1 时推理帧率被 1/RTT 硬封顶（RTT 20ms → 上限 50FPS、
// 30ms → 33FPS），并发 2 让第 N+1 帧的请求在第 N 帧 invoke 期间发出，CPU 准备与
// NPU 执行流水线化（后端 predict 已在线程池执行，天然支持重叠）。瓶颈在 RTT 时才
// 继续调大（上限 4），纯本机超低延迟场景用 ARENA_INFERENCE_CONCURRENCY=1 还原。
export const ARENA_INFERENCE_CONCURRENCY_DEFAULT = 2;

/**
 * canvas 绘制线 / chart.js 数据系列的 JS 配色（回退值表，深色值即现状；
 * 浅色值对标 theme-light.css 色板:同色相、保饱和、适度降明度）。
 * 语义角色（user=--ok、pilot=--accent、legend=--ink2、ticks=--ink3）实际取色走
 * CSS 变量，随主题（深/浅）切换自动变化；userThrottle/pilotThrottle
 * 为数据可视化专用色相，保持固定。
 */
export const ARENA_SERIES_COLORS = {
  dark: {
    user: '#22c55e',
    pilot: '#3b82f6',
    userThrottle: '#a3e635',
    pilotThrottle: '#38bdf8',
    legend: '#d4d4d8',
    ticks: '#a1a1aa',
  },
  light: {
    user: '#1fae6b',
    pilot: '#0c9bd6',
    userThrottle: '#d99a17',
    pilotThrottle: '#0a6f9e',
    legend: '#42546a',
    ticks: '#5b6b7d',
  },
};

export type ArenaSeriesColors = (typeof ARENA_SERIES_COLORS)['dark'];

/** 语义角色 → CSS 变量名（取不到时回退 ARENA_SERIES_COLORS 对应值）。 */
export const ARENA_SERIES_CSS_VARS: Partial<Record<keyof ArenaSeriesColors, string>> = {
  user: '--ok',
  pilot: '--accent',
  legend: '--ink2',
  ticks: '--ink3',
};

/** 从根元素 computed style 解析 CSS 变量颜色；取不到（jsdom/变量缺失）回退 fallback。 */
export const cssVarColor = (name: string, fallback: string): string => {
  try {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  } catch {
    return fallback;
  }
};

/** 按当前主题解析系列配色：语义角色读 CSS 变量，其余用回退值表。 */
export const resolveArenaSeriesColors = (theme: ResolvedTheme): ArenaSeriesColors => {
  const fallback = ARENA_SERIES_COLORS[theme];
  const resolved = { ...fallback };
  for (const key of Object.keys(ARENA_SERIES_CSS_VARS) as (keyof ArenaSeriesColors)[]) {
    resolved[key] = cssVarColor(ARENA_SERIES_CSS_VARS[key] as string, fallback[key]);
  }
  return resolved;
};

export const formatValue = (value: number | undefined) =>
  value === undefined || Number.isNaN(value) ? '--' : value.toFixed(3);

export const getRecordImagePath = (record: Record<string, unknown> | undefined) => {
  if (!record) return null;
  const imageKey = Object.keys(record).find((key) => key.endsWith('image_array') || key === 'cam/image' || key === 'image');
  const imagePath = imageKey ? record[imageKey] : null;
  return typeof imagePath === 'string' ? imagePath : null;
};

export const drawControlLine = (ctx: CanvasRenderingContext2D, angle: number | undefined, throttle: number | undefined, color: string) => {
  if (angle === undefined || throttle === undefined || Number.isNaN(angle) || Number.isNaN(throttle)) return;
  const { width, height } = ctx.canvas;
  const startX = width / 2;
  const startY = height - 1;
  const endX = startX + Math.max(-1, Math.min(1, angle)) * width * 0.4;
  const endY = startY - Math.max(-1, Math.min(1, throttle)) * height * 0.6;
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(2, width / 160);
  ctx.beginPath();
  ctx.moveTo(startX, startY);
  ctx.lineTo(endX, endY);
  ctx.stroke();
};

export const getRecordUserControl = (record: Record<string, unknown> | undefined) => {
  if (!record) return undefined;
  return {
    angle: Number(record['user/angle']),
    throttle: Number(record['user/throttle']),
  };
};

