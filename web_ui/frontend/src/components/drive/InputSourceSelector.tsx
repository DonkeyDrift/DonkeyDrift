import React from 'react';
import { Gamepad2, Smartphone, Joystick, Keyboard } from 'lucide-react';

export type InputSource = 'joystick' | 'keyboard' | 'gamepad' | 'gyro';

interface InputSourceSelectorProps {
  value: InputSource;
  onChange: (source: InputSource) => void;
  gamepadConnected?: boolean;
  gyroAvailable?: boolean;
  className?: string;
}

const SOURCES: { value: InputSource; label: string; icon: React.ReactNode }[] = [
  { value: 'joystick', label: '摇杆', icon: <Joystick className="w-3.5 h-3.5" /> },
  { value: 'keyboard', label: '键盘', icon: <Keyboard className="w-3.5 h-3.5" /> },
  { value: 'gamepad', label: '手柄', icon: <Gamepad2 className="w-3.5 h-3.5" /> },
  { value: 'gyro', label: '陀螺仪', icon: <Smartphone className="w-3.5 h-3.5" /> },
];

export const InputSourceSelector: React.FC<InputSourceSelectorProps> = ({
  value,
  onChange,
  gamepadConnected = false,
  gyroAvailable = true,
  className = '',
}) => {
  return (
    <div className={`inline-flex rounded-lg border border-zinc-800 overflow-hidden ${className}`}>
      {SOURCES.map((src) => {
        const active = value === src.value;
        const disabled =
          (src.value === 'gamepad' && !gamepadConnected) ||
          (src.value === 'gyro' && !gyroAvailable);

        return (
          <button
            key={src.value}
            onClick={() => !disabled && onChange(src.value)}
            disabled={disabled}
            className={`px-3 py-1.5 text-xs font-medium transition-colors flex items-center gap-1.5
              ${active
                ? 'bg-cyan-500/20 text-cyan-400'
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800'
              }
              ${disabled ? 'opacity-40 cursor-not-allowed' : ''}
            `}
            title={
              src.value === 'gamepad'
                ? gamepadConnected ? '已连接手柄' : '未检测到手柄'
                : src.value === 'gyro'
                  ? gyroAvailable ? '设备支持陀螺仪' : '设备不支持陀螺仪'
                  : src.label
            }
          >
            {src.icon}
            <span>{src.label}</span>
            {src.value === 'gamepad' && gamepadConnected && (
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            )}
          </button>
        );
      })}
    </div>
  );
};
