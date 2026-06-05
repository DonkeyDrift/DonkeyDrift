import React, { useEffect, useRef, useState, useCallback } from 'react';

interface VirtualJoystickProps {
  onChange?: (angle: number, throttle: number) => void;
  size?: number;
  className?: string;
}

/**
 * 虚拟摇杆组件 - 不依赖第三方库
 * 横向输出 angle [-1, 1]：左负右正
 * 纵向输出 throttle [-1, 1]：上正下负（向前推油门为正）
 */
export const VirtualJoystick: React.FC<VirtualJoystickProps> = ({
  onChange,
  size = 220,
  className = '',
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const activePointerId = useRef<number | null>(null);
  const centerRef = useRef({ x: 0, y: 0 });

  const maxRadius = size / 2 - 28;

  const updateCenter = useCallback(() => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    centerRef.current = {
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
    };
  }, []);

  const clampToRadius = (x: number, y: number) => {
    const dist = Math.sqrt(x * x + y * y);
    if (dist > maxRadius) {
      const ratio = maxRadius / dist;
      return { x: x * ratio, y: y * ratio };
    }
    return { x, y };
  };

  const emitChange = useCallback((x: number, y: number) => {
    if (!onChange) return;
    const angle = Math.max(-1, Math.min(1, x / maxRadius));
    const throttle = Math.max(-1, Math.min(1, -y / maxRadius));
    onChange(angle, throttle);
  }, [onChange, maxRadius]);

  const handlePointerDown = (e: React.PointerEvent) => {
    if (activePointerId.current !== null) return;
    activePointerId.current = e.pointerId;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    updateCenter();
    setDragging(true);

    const dx = e.clientX - centerRef.current.x;
    const dy = e.clientY - centerRef.current.y;
    const clamped = clampToRadius(dx, dy);
    setOffset(clamped);
    emitChange(clamped.x, clamped.y);
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (activePointerId.current !== e.pointerId) return;
    const dx = e.clientX - centerRef.current.x;
    const dy = e.clientY - centerRef.current.y;
    const clamped = clampToRadius(dx, dy);
    setOffset(clamped);
    emitChange(clamped.x, clamped.y);
  };

  const handlePointerUp = (e: React.PointerEvent) => {
    if (activePointerId.current !== e.pointerId) return;
    activePointerId.current = null;
    (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    setDragging(false);
    setOffset({ x: 0, y: 0 });
    emitChange(0, 0);
  };

  useEffect(() => {
    updateCenter();
    window.addEventListener('resize', updateCenter);
    return () => window.removeEventListener('resize', updateCenter);
  }, [updateCenter]);

  const knobSize = 56;

  return (
    <div
      ref={containerRef}
      className={`relative rounded-full bg-zinc-950 border-2 border-zinc-700 touch-none select-none ${dragging ? 'border-cyan-500/60 shadow-lg shadow-cyan-500/10' : ''} ${className}`}
      style={{ width: size, height: size }}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
    >
      {/* 参考圆环 */}
      <div
        className="absolute rounded-full border border-zinc-800"
        style={{
          width: maxRadius * 2,
          height: maxRadius * 2,
          left: size / 2 - maxRadius,
          top: size / 2 - maxRadius,
        }}
      />
      <div
        className="absolute rounded-full border border-dashed border-zinc-800/60"
        style={{
          width: maxRadius,
          height: maxRadius,
          left: size / 2 - maxRadius / 2,
          top: size / 2 - maxRadius / 2,
        }}
      />
      {/* 十字线 */}
      <div className="absolute w-px h-1/2 bg-zinc-800 left-1/2 top-0" />
      <div className="absolute w-1/2 h-px bg-zinc-800 top-1/2 left-0" />

      {/* 摇杆头 */}
      <div
        className={`absolute rounded-full transition-colors ${dragging ? 'bg-cyan-500/80' : 'bg-zinc-600'} shadow-lg`}
        style={{
          width: knobSize,
          height: knobSize,
          left: size / 2 - knobSize / 2 + offset.x,
          top: size / 2 - knobSize / 2 + offset.y,
        }}
      />
    </div>
  );
};
