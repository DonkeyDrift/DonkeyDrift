import React from 'react';

interface ControlBarsProps {
  angle: number;
  throttle: number;
  className?: string;
}

/**
 * 转向/油门指示条
 * angle: -1 ~ 1
 * throttle: -1 ~ 1
 */
export const ControlBars: React.FC<ControlBarsProps> = ({ angle, throttle, className = '' }) => {
  const anglePercent = Math.abs(angle) * 50;
  const throttlePercent = Math.abs(throttle) * 50;

  return (
    <div className={`space-y-3 ${className}`}>
      {/* 转向 */}
      <div>
        <div className="flex items-center justify-between text-[10px] text-zinc-500 mb-1">
        <span>左转</span>
        <span className="text-zinc-400 font-medium">转向</span>
        <span>右转</span>
      </div>
      <div className="h-2 bg-zinc-800 rounded-full overflow-hidden relative">
        <div className="absolute left-1/2 top-0 bottom-0 w-0.5 bg-zinc-600" />
        {angle >= 0 ? (
          <div
            className="absolute left-1/2 top-0 bottom-0 bg-cyan-500 rounded-full"
            style={{ width: `${anglePercent}%` }}
          />
        ) : (
          <div
            className="absolute right-1/2 top-0 bottom-0 bg-cyan-500 rounded-full"
            style={{ width: `${anglePercent}%` }}
          />
        )}
      </div>
      <div className="text-[10px] text-zinc-500 text-center mt-1">
        {angle.toFixed(2)}
      </div>
    </div>

    {/* 油门 */}
    <div>
      <div className="flex items-center justify-between text-[10px] text-zinc-500 mb-1">
        <span>倒车</span>
        <span className="text-zinc-400 font-medium">油门</span>
        <span>前进</span>
      </div>
      <div className="h-2 bg-zinc-800 rounded-full overflow-hidden relative">
        <div className="absolute left-1/2 top-0 bottom-0 w-0.5 bg-zinc-600" />
        {throttle >= 0 ? (
          <div
            className="absolute left-1/2 top-0 bottom-0 bg-emerald-500 rounded-full"
            style={{ width: `${throttlePercent}%` }}
          />
        ) : (
          <div
            className="absolute right-1/2 top-0 bottom-0 bg-red-500 rounded-full"
            style={{ width: `${throttlePercent}%` }}
          />
        )}
      </div>
      <div className="text-[10px] text-zinc-500 text-center mt-1">
        {throttle.toFixed(2)}
      </div>
    </div>
    </div>
  );
};
