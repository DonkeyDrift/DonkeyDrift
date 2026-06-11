import React from 'react';

interface ControlBarsProps {
  angle: number;
  className?: string;
}

/**
 * 转向指示条
 * angle: -1 ~ 1
 */
export const ControlBars: React.FC<ControlBarsProps> = ({ angle, className = '' }) => {
  const anglePercent = Math.abs(angle) * 50;

  return (
    <div className={`space-y-3 ${className}`}>
      <div>
        <div className="flex items-center justify-between text-[10px] text-zinc-500 mb-1">
          <span>左 转</span>
          <span className="text-zinc-400 font-medium">转 向</span>
          <span>右 转</span>
        </div>
        <div className="h-2 bg-zinc-800 rounded-full overflow-hidden relative w-full">
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
    </div>
  );
};
