import React from 'react';
import { fireEvent, render, waitFor } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { VirtualJoystick } from './VirtualJoystick';

// jsdom 未实现指针捕获 API，摇杆 handler 里会调用，补成 no-op
beforeAll(() => {
  HTMLElement.prototype.setPointerCapture = vi.fn();
  HTMLElement.prototype.releasePointerCapture = vi.fn();
});

describe('VirtualJoystick', () => {
  it('按下/拖动上报对应值，松开回中', () => {
    const onChange = vi.fn();
    const { container } = render(<VirtualJoystick onChange={onChange} size={220} />);
    const pad = container.firstElementChild as HTMLElement;

    fireEvent.pointerDown(pad, { pointerId: 1, clientX: 41, clientY: -41 });
    // jsdom 布局全 0 → 中心 (0,0)，maxRadius=82：x=41 ≈ 0.5 右打、y=-41 ≈ 0.5 前进
    const [, downThrottle] = onChange.mock.calls.at(-1) as [number, number];
    expect(downThrottle).toBeGreaterThan(0.4);

    fireEvent.pointerUp(pad, { pointerId: 1, clientX: 41, clientY: -41 });
    const [upAngle, upThrottle] = onChange.mock.calls.at(-1) as [number, number];
    expect(upAngle).toBe(0);
    // 回中值经 -y/maxRadius 计算可能是 -0，按数值比较
    expect(Math.abs(upThrottle)).toBe(0);
  });

  it('拖拽期间指针静止也按帧持续重发当前值（稳持心跳 #508）', async () => {
    const onChange = vi.fn();
    const { container } = render(<VirtualJoystick onChange={onChange} size={220} />);
    const pad = container.firstElementChild as HTMLElement;

    fireEvent.pointerDown(pad, { pointerId: 1, clientX: 0, clientY: -60 });
    await waitFor(() => expect(onChange.mock.calls.length).toBeGreaterThan(2));

    // 之后不再有任何 pointermove：心跳 rAF 仍持续重发同值
    const count = onChange.mock.calls.length;
    await new Promise((r) => setTimeout(r, 200));
    expect(onChange.mock.calls.length).toBeGreaterThan(count);
    const [angle, throttle] = onChange.mock.calls.at(-1) as [number, number];
    expect(angle).toBe(0);
    expect(throttle).toBeCloseTo(60 / 82, 1);
  });
});
