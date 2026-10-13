import '@testing-library/jest-dom/vitest';
import React from 'react';
import { fireEvent, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { VirtualJoystick } from './VirtualJoystick';

// jsdom 无 PointerEvent 构造器与 pointer capture，手动补齐
let rafCallbacks: Map<number, FrameRequestCallback>;
let rafSeq = 0;

const stepRaf = (now: number) => {
  const cbs = [...rafCallbacks.entries()];
  rafCallbacks.clear();
  cbs.forEach(([, cb]) => cb(now));
};

const lastCall = (mock: ReturnType<typeof vi.fn>) => mock.mock.calls.at(-1) as [number, number] | undefined;

const zeroCalls = (mock: ReturnType<typeof vi.fn>) =>
  mock.mock.calls.filter(([a, t]) => Math.abs(a) < 1e-9 && Math.abs(t) < 1e-9);

/** -0 与 0 在 toEqual 下不相等，终点断言统一用 closeTo */
const expectLastCallNear = (mock: ReturnType<typeof vi.fn>, a: number, t: number) => {
  const [angle, throttle] = lastCall(mock)!;
  expect(angle).toBeCloseTo(a, 6);
  expect(throttle).toBeCloseTo(t, 6);
};

beforeEach(() => {
  vi.useFakeTimers();
  rafCallbacks = new Map();
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
    const id = ++rafSeq;
    rafCallbacks.set(id, cb);
    return id;
  });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => {
    rafCallbacks.delete(id);
  });
  HTMLElement.prototype.setPointerCapture = vi.fn();
  HTMLElement.prototype.releasePointerCapture = vi.fn();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** size=220 → maxRadius=82；jsdom 下容器中心为 (0,0)，client 坐标即偏移 */
const pressAt = (el: HTMLElement, x: number, y: number, pointerId = 1) =>
  fireEvent.pointerDown(el, { pointerId, clientX: x, clientY: y });
const moveTo = (el: HTMLElement, x: number, y: number, pointerId = 1) =>
  fireEvent.pointerMove(el, { pointerId, clientX: x, clientY: y });
const release = (el: HTMLElement, pointerId = 1) =>
  fireEvent.pointerUp(el, { pointerId, clientX: 0, clientY: 0 });

describe('VirtualJoystick 回中行为', () => {
  it('拖拽时输出映射正确', () => {
    const onChange = vi.fn();
    const { container } = render(<VirtualJoystick onChange={onChange} />);
    const el = container.firstChild as HTMLElement;
    pressAt(el, 41, -41);
    expect(lastCall(onChange)).toBeDefined();
    const [angle, throttle] = lastCall(onChange)!;
    expect(angle).toBeCloseTo(0.5, 1);   // 41/82
    expect(throttle).toBeCloseTo(0.5, 1); // 上推为正
  });

  it('松开不立即拍零，宽限期后斜坡回中', () => {
    const onChange = vi.fn();
    const { container } = render(<VirtualJoystick onChange={onChange} />);
    const el = container.firstChild as HTMLElement;
    pressAt(el, 41, -41);
    moveTo(el, 41, -41);
    const callsBeforeRelease = onChange.mock.calls.length;
    release(el);

    // 松开后、宽限期内：不得新增任何 (0,0) 输出
    expect(onChange.mock.calls.length).toBe(callsBeforeRelease);
    vi.advanceTimersByTime(100);
    expect(zeroCalls(onChange)).toHaveLength(0);

    // 宽限期(200ms)结束 → 斜坡开始，逐帧衰减
    vi.advanceTimersByTime(120);
    const t0 = performance.now();
    stepRaf(t0 + 16);
    const mid = lastCall(onChange)!;
    expect(Math.abs(mid[0])).toBeLessThan(0.5);
    expect(Math.abs(mid[0])).toBeGreaterThan(0.01);

    // 斜坡(180ms)走完 → 终点精确回中
    stepRaf(t0 + 500);
    expectLastCallNear(onChange, 0, 0);
  });

  it('宽限期内重新按下视为继续拖拽，全程无拍零', () => {
    const onChange = vi.fn();
    const { container } = render(<VirtualJoystick onChange={onChange} />);
    const el = container.firstChild as HTMLElement;
    pressAt(el, 41, -41);
    release(el);
    // 100ms 后（宽限期内）重新按下
    vi.advanceTimersByTime(100);
    pressAt(el, 50, -50);
    moveTo(el, 50, -50);

    // 越过宽限期 + 斜坡时长，确认回中从未发生
    vi.advanceTimersByTime(500);
    stepRaf(performance.now() + 600);
    expect(zeroCalls(onChange)).toHaveLength(0);
    expectLastCallNear(onChange, 50 / 82, 50 / 82);
  });

  it('pointercancel 与 pointerup 同样走宽限期回中', () => {
    const onChange = vi.fn();
    const { container } = render(<VirtualJoystick onChange={onChange} />);
    const el = container.firstChild as HTMLElement;
    pressAt(el, 41, -41);
    fireEvent.pointerCancel(el, { pointerId: 1, clientX: 0, clientY: 0 });
    vi.advanceTimersByTime(100);
    expect(zeroCalls(onChange)).toHaveLength(0);
    vi.advanceTimersByTime(120);
    stepRaf(performance.now() + 16);
    stepRaf(performance.now() + 500);
    expectLastCallNear(onChange, 0, 0);
  });
});
