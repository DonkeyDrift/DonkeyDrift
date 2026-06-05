import React from 'react';

export type DriveMode = 'user' | 'local_angle' | 'local';

interface DriveModeSelectorProps {
  value: DriveMode;
  onChange: (mode: DriveMode) => void;
  disabled?: boolean;
  className?: string;
}

const MODE_OPTIONS: { value: DriveMode; label: string; shortcut?: string }[] = [
  { value: 'user', label: '人工' },
  { value: 'local_angle', label: 'AI 转向', shortcut: 'S' },
  { value: 'local', label: '全自动', shortcut: 'A' },
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
            onClick={() => onChange(mode.value)}
            disabled={disabled}
            className={`px-3 py-1.5 text-xs font-medium transition-colors
              ${active
                ? 'bg-cyan-500/20 text-cyan-400'
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800'
              }
              ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
            `}
          >
            {mode.label}
            {mode.shortcut && (
              <span className="ml-1 text-[10px] opacity-60">({mode.shortcut})</span>
            )}
          </button>
        );
      })}
    </div>
  );
};
