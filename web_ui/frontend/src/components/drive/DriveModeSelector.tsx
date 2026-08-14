import React from 'react';
import { useTranslation } from '@/i18n';
import { useResolvedTheme } from '@/lib/theme';

export type DriveMode = 'user' | 'local_angle' | 'local';

interface DriveModeSelectorProps {
  value: DriveMode;
  onChange: (mode: DriveMode) => void;
  disabled?: boolean;
  className?: string;
}

// Active-segment colors mirror the ESP32 Drifter Console mode cards
// (mode0=手动 green #39d98a, mode1=半自动 amber #ffcc66, mode2=全自动 blue #5cc8ff).
// 任意值类皮肤 CSS 覆盖不到:浅色主题改用同色相墨色文字 + 薄底
// (绿 #1a8952 / 琥珀 #a87900 / 蓝 #0280bd)。
const MODE_OPTIONS: { value: DriveMode; labelKey: string; activeClass: string; activeClassLight: string }[] = [
  { value: 'user', labelKey: 'drive.modeUser', activeClass: 'bg-[#39d98a]/20 text-[#39d98a]', activeClassLight: 'bg-[#1a8952]/15 text-[#1a8952]' },
  { value: 'local_angle', labelKey: 'drive.modeSemiAuto', activeClass: 'bg-[#ffcc66]/20 text-[#ffcc66]', activeClassLight: 'bg-[#a87900]/15 text-[#a87900]' },
  { value: 'local', labelKey: 'drive.modeFullAuto', activeClass: 'bg-[#5cc8ff]/20 text-[#5cc8ff]', activeClassLight: 'bg-[#0280bd]/15 text-[#0280bd]' },
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
