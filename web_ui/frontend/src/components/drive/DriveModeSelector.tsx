import React from 'react';

export type DriveMode = 'user' | 'local_angle' | 'local';

interface DriveModeSelectorProps {
  value: DriveMode;
  onChange: (mode: DriveMode) => void;
  disabled?: boolean;
  className?: string;
}

// Active-segment colors mirror the ESP32 Drifter Console mode cards
// (mode0=手动 green #39d98a, mode1=半自动 amber #ffcc66, mode2=全自动 blue #5cc8ff).
const MODE_OPTIONS: { value: DriveMode; label: string; activeClass: string }[] = [
  { value: 'user', label: '手动', activeClass: 'bg-[#39d98a]/20 text-[#39d98a]' },
  { value: 'local_angle', label: '半自动', activeClass: 'bg-[#ffcc66]/20 text-[#ffcc66]' },
  { value: 'local', label: '全自动', activeClass: 'bg-[#5cc8ff]/20 text-[#5cc8ff]' },
];

export const DriveModeSelector: React.FC<DriveModeSelectorProps> = ({
  value,
  onChange,
  disabled = false,
  className = '',
}) => {
  return (
    <div className={`inline-flex rounded-lg border border-zinc-800 overflow-hidden ${className}`}>
      {MODE_OPTIONS.map((mode) => {
        const active = value === mode.value;
        return (
          <button
            key={mode.value}
            data-mode={mode.value}
            onClick={() => onChange(mode.value)}
            disabled={disabled}
            className={`px-3 py-1.5 text-xs font-medium transition-colors
              ${active
                ? `mode-active ${mode.activeClass}`
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800'
              }
              ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
            `}
          >
            {mode.label}
          </button>
        );
      })}
    </div>
  );
};
