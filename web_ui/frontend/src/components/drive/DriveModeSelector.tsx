import React from 'react';
import { useTranslation } from '@/i18n';
import { useResolvedTheme } from '@/lib/theme';

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
// (mode0=手动 green #39d98a, mode1=半自动 amber #ffcc66, mode2=全自动 blue #5cc8ff).
// 任意值类皮肤 CSS 覆盖不到:浅色主题改用同色相饱和中间色文字 + 薄底
// (绿 #1fae6b / 琥珀 #b57d0e / 蓝 #0c9bd6)。
const MODE_OPTIONS: { value: DriveMode; labelKey: string; activeClass: string; activeClassLight: string }[] = [
  { value: 'user', labelKey: 'drive.modeUser', activeClass: 'bg-[#39d98a]/20 text-[#39d98a]', activeClassLight: 'bg-[#1fae6b]/15 text-[#1fae6b]' },
  { value: 'local_angle', labelKey: 'drive.modeSemiAuto', activeClass: 'bg-[#ffcc66]/20 text-[#ffcc66]', activeClassLight: 'bg-[#b57d0e]/15 text-[#b57d0e]' },
  { value: 'local', labelKey: 'drive.modeFullAuto', activeClass: 'bg-[#5cc8ff]/20 text-[#5cc8ff]', activeClassLight: 'bg-[#0c9bd6]/15 text-[#0c9bd6]' },
];

export const DriveModeSelector: React.FC<DriveModeSelectorProps> = ({
  value,
  onChange,
  disabled = false,
  className = '',
}) => {
  const { t } = useTranslation();
  const theme = useResolvedTheme();
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
                ? `mode-active ${theme === 'light' ? mode.activeClassLight : mode.activeClass}`
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
