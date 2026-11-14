/**
 * 遥测曲线自绘渲染器（替代 chart.js，性能关键路径）。
 *
 * 曲线形态完全固定：y 轴钉死 [-1,1]、无坐标轴/网格/tooltip/动画/布局计算。
 * chart.js 的通用管线（dataset 解析 → scale → 布局 → 逐点路径）单次重绘在毫秒级，
 * 迫使调用方只能 200ms 节流（5fps，曲线跳变感明显）；本模块直接在 2D canvas 上
 * 画折线，单次重绘 ~0.1ms 量级，允许 30fps 稳定重绘且几乎不占主线程。
 */

/** 单条曲线的定长环形缓冲：未填满处为 NaN（曲线在此断开）。 */
export class RingSeries {
  readonly buf: number[];
  /** 下一个写入位置。 */
  writeIndex = 0;
  /** 已填充的点数（≤ size）。 */
  filled = 0;

  constructor(readonly size: number) {
    this.buf = new Array<number>(size).fill(NaN);
  }

  /** 追加一个采样点（缩放与 NaN/缺失判断由调用方完成）。 */
  push(value: number): void {
    this.buf[this.writeIndex] = value;
    this.writeIndex = (this.writeIndex + 1) % this.size;
    this.filled = Math.min(this.filled + 1, this.size);
  }

  /** 取「最旧→最新」第 i 个点；未填满时 i ≥ filled 为 NaN。 */
  at(i: number): number {
    return this.filled < this.size
      ? (i < this.filled ? this.buf[i] : NaN)
      : this.buf[(this.writeIndex + i) % this.size];
  }
}

/** 绘制参数：一条曲线 = 颜色 + 环形缓冲。 */
export interface RingCurve {
  color: string;
  series: RingSeries;
  lineWidth?: number;
}

/**
 * 把一组环形缓冲画成折线：x 均分整个宽度（最旧在左、最新在右），
 * y 线性映射 [-1,1]→[height,0]（上下各留 1px 防线宽被裁切），NaN 断开曲线。
 * 零临时数组分配，可被 rAF 高频调用。
 */
export const drawRingCurves = (
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  curves: RingCurve[],
): void => {
  ctx.clearRect(0, 0, width, height);
  const size = curves[0]?.series.size ?? 0;
  if (size < 2 || width <= 0 || height <= 0) return;
  const yMid = height / 2;
  const half = Math.max(0, yMid - 1);
  const step = width / (size - 1);
  for (const curve of curves) {
    const series = curve.series;
    // 样式先于 beginPath：路径属性在 stroke() 时生效，但先设样式可让「起路径」即携带最终样式
    ctx.strokeStyle = curve.color;
    ctx.lineWidth = curve.lineWidth ?? 1.5;
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < size; i++) {
      const v = series.at(i);
      // NaN（缓冲未填满处或缺失字段）→ 当前段结束，下一个有效点重新起笔
      if (v !== v) {
        started = false;
        continue;
      }
      const x = i * step;
      const y = yMid - v * half;
      if (started) {
        ctx.lineTo(x, y);
      } else {
        ctx.moveTo(x, y);
        started = true;
      }
    }
    ctx.stroke();
  }
};
