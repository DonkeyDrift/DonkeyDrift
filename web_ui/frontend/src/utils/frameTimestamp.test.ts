import { describe, expect, it } from 'vitest';
import { readFrameTimestamp, FRAME_STAMP_SAMPLE_WIDTH, FRAME_STAMP_SAMPLE_HEIGHT } from './frameTimestamp';
// 夹具由 Python 参考实现 draw_timestamp 生成（含随机噪声背景 + 一枚损坏帧）
import fixture from './__fixtures__/frameStamp.json';

describe('readFrameTimestamp', () => {
  it('解码 Python draw_timestamp 生成的印章（跨语言对齐）', () => {
    const data = new Uint8ClampedArray(fixture.rgba);
    const stamp = readFrameTimestamp(data, fixture.width);
    expect(stamp).not.toBeNull();
    // Python 端 64µs 分辨率：容差取 1 个分辨率单位
    expect(Math.abs((stamp as number) - fixture.ts)).toBeLessThan(0.0001);
  });

  it('校验和失败返回 null（损坏帧不猜值）', () => {
    const data = new Uint8ClampedArray(fixture.badRgba);
    expect(readFrameTimestamp(data, fixture.width)).toBeNull();
  });

  it('全黑背景（无印章）返回 null', () => {
    const data = new Uint8ClampedArray(
      FRAME_STAMP_SAMPLE_WIDTH * FRAME_STAMP_SAMPLE_HEIGHT * 4,
    );
    expect(readFrameTimestamp(data, FRAME_STAMP_SAMPLE_WIDTH)).toBeNull();
  });

  it('采样区域常量覆盖印章衬底范围', () => {
    // 衬底 x∈[2, 238)、y∈[2, 22)：采样区必须完整包含
    expect(FRAME_STAMP_SAMPLE_WIDTH).toBeGreaterThanOrEqual(238);
    expect(FRAME_STAMP_SAMPLE_HEIGHT).toBeGreaterThanOrEqual(22);
  });
});
