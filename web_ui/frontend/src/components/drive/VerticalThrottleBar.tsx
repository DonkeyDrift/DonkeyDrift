import React from 'react';

interface VerticalThrottleBarProps {
  throttle: number;
  className?: string;
}

/**
 * 竖向油门指示条
 * throttle: -1 ~ 1，向上为正（前进），向下为负（倒车）
 * 条形区域高度与容器一致，中心严格对齐虚拟摇杆水平直径
 */
export const VerticalThrottleBar: React.FC<VerticalThrottleBarProps> = ({ throttle, className = '' }) => {
  const throttlePercent = Math.abs(throttle) * 50;

  return (
    <div className={`relative flex items-center justify-center ${className}`}>
      {/* 左侧数值 */}
      <span className="absolute right-full mr-2 top-1/2 -translate-y-1/2 text-[10px] text-zinc-500 text-right">
        {throttle.toFixed(2)}
      </span>

      <div className="w-2 h-full bg-zinc-800 rounded-full overflow-hidden relative">
        <div className="absolute left-0 right-0 top-1/2 h-0.5 bg-zinc-600" />
        {throttle >= 0 ? (
          <div
            className="absolute left-0 right-0 bottom-1/2 bg-emerald-500 rounded-full"
            style={{ height: `${throttlePercent}%` }}
          />
        ) : (
          <div
            className="absolute left-0 right-0 top-1/2 bg-red-500 rounded-full"
            style={{ height: `${throttlePercent}%` }}
          />
        )}
      </div>

      {/* 右侧标签：前进 / 油门 / 倒车 */}
      <div className="absolute left-full ml-2 flex flex-col justify-between h-full py-1 text-[10px] text-zinc-500 items-start">
        <span>前进</span>
        <span className="[writing-mode:vertical-rl] -translate-x-1">油 门</span>
        <span>倒车</span>
      </div>
    </div>
  );
};
