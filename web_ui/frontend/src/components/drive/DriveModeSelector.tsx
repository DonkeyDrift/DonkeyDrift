import React from 'react';
import { useTranslation } from '@/i18n';

export type DriveMode = 'user' | 'local_angle' | 'local';

/** DriveMode -> ESP32 车控模式 rc_mode（0=手动 / 1=半自动 / 2=全自动）。 */
export const driveModeToRcMode = (mode: DriveMode): number => {
  switch (mode) {
    case 'user':
      return 0;
    case 'local_angle':
      return 1;
    case 'local':
      return 2;
  }
};

/** ESP32 车控模式 rc_mode（0/1/2）-> DriveMode，非法值回退 'user'。 */
export const rcModeToDriveMode = (rcMode: number): DriveMode => {
  switch (rcMode) {
    case 0:
      return 'user';
    case 1:
      return 'local_angle';
    case 2:
      return 'local';
    default:
      return 'user';
  }
};

interface DriveModeSelectorProps {
  value: DriveMode;
  onChange: (mode: DriveMode) => void;
  disabled?: boolean;
  className?: string;
}

// Active-segment colors mirror the ESP32 Drifter Console mode cards
// (mode0=手动 green, mode1=半自动 amber, mode2=全自动 blue)。
// 语义类由 theme-*.css 映射到 --ok/--warn/--accent 变量，四象限（深/浅 × 座舱/Apple）自动取色。
const MODE_OPTIONS: { value: DriveMode; labelKey: string; activeClass: string }[] = [
  { value: 'user', labelKey: 'drive.modeUser', activeClass: 'bg-emerald-500/25 text-emerald-400' },
  { value: 'local_angle', labelKey: 'drive.modeSemiAuto', activeClass: 'bg-amber-400/10 text-amber-400' },
  { value: 'local', labelKey: 'drive.modeFullAuto', activeClass: 'bg-cyan-600/20 text-cyan-400' },
];

export const DriveModeSelector: React.FC<DriveModeSelectorProps> = ({
  value,
  onChange,
  disabled = false,
  className = '',
}) => {
  const { t } = useTranslation();
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
            {t(mode.labelKey)}
          </button>
        );
      })}
    </div>
  );
};
