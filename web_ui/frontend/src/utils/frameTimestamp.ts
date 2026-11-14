/**
 * 帧内时间戳印章解码器（与 donkeycar/parts/video_timestamp.py 逐字节对齐）。
 *
 * 车端把每帧时间戳烧进画面左上角的二进制单元条（cell bar）；浏览器在
 * rVFC 回调里 canvas 采样呈现帧的印章区域并解码，得到「该帧何时出车端」，
 * 与当前时刻相减即屏幕上的真实端到端时延（captureTime 缺失的浏览器的
 * 唯一可靠口径）。格式与容差由 Python 参考实现锁定，
 * __fixtures__/frameStamp.json 由 draw_timestamp 生成，防两端同错。
 *
 * 格式（v1，见 video_timestamp.py）：
 * - 2 行 × 28 数据 cell，行首 1 个同步 cell（行0 白、行1 黑）；
 * - cell 6px + 2px 间距（pitch 8px），起点 (4,4)，衬底外扩 2px 黑色；
 * - payload = 微秒时间戳 >> 4（48bit，MSB 先行、行优先）+ 8bit 校验和。
 */

/** canvas 采样区域：覆盖印章衬底 (2..238, 2..22) 的左上角矩形 */
export const FRAME_STAMP_SAMPLE_WIDTH = 240;
export const FRAME_STAMP_SAMPLE_HEIGHT = 24;

const CELL = 6;
const GAP = 2;
const PITCH = CELL + GAP; // 8
const COLS = 28;
const ROWS = 2;
const X0 = 4;
const Y0 = 4;
const CELL_INNER = CELL - 4; // 2：取 cell 中心 2×2 抗压缩

const WHITE_MIN = 160; // 同步 cell 判白下限（均值）
const BLACK_MAX = 96; // 同步 cell 判黑上限
const CELL_THRESHOLD = 128;

const PAYLOAD_BITS = 48;

/**
 * 从印章区域像素解码时间戳（秒，Unix epoch）。
 *
 * @param data   ImageData.data（RGBA），区域原点 = 视频像素 (0,0)
 * @param width  该区域宽度（像素步长）
 * @returns 时间戳；无印章/校验失败 → null（不猜值）
 */
export function readFrameTimestamp(data: Uint8ClampedArray, width: number): number | null {
  // cell 中心 CELL_INNER×CELL_INNER 的 RGB 均值（对应 Python 端 gray 切片）
  const meanAt = (x: number, y: number): number => {
    let sum = 0;
    for (let dy = 0; dy < CELL_INNER; dy += 1) {
      for (let dx = 0; dx < CELL_INNER; dx += 1) {
        const i = ((y + dy) * width + (x + dx)) * 4;
        sum += (data[i] + data[i + 1] + data[i + 2]) / 3;
      }
    }
    return sum / (CELL_INNER * CELL_INNER);
  };

  let payload = 0; // 48bit 时间位（Number 安全：2^48 < 2^53）
  let checksum = 0; // 8bit 校验位
  let bitIndex = 0;
  for (let row = 0; row < ROWS; row += 1) {
    const rowY = Y0 + row * PITCH;
    const sync = meanAt(X0 + CELL_INNER, rowY + CELL_INNER);
    if (row === 0 && sync < WHITE_MIN) return null;
    if (row === 1 && sync > BLACK_MAX) return null;
    for (let col = 0; col < COLS; col += 1) {
      const x = X0 + (col + 1) * PITCH + CELL_INNER;
      const bit = meanAt(x, rowY + CELL_INNER) >= CELL_THRESHOLD ? 1 : 0;
      if (bitIndex < PAYLOAD_BITS) {
        payload = payload * 2 + bit;
      } else {
        checksum = checksum * 2 + bit;
      }
      bitIndex += 1;
    }
  }

  let sum = 0;
  for (let i = 5; i >= 0; i -= 1) {
    sum += Math.floor(payload / 256 ** i) & 0xff;
  }
  if ((sum & 0xff) !== checksum) return null;
  return (payload * 16) / 1_000_000;
}
