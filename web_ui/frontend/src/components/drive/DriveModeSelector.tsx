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

// 选中段统一 accent 浅底 + accent 文字（2026-09-25 视觉评审：Drive 页选中态只保留
// Apple 蓝（主）+ 语义红（停止/危险）+ 中性灰三种语言，不再沿用 ESP32 模式三色）。
// 语义类由 theme-*.css 映射到 --accent 变量体系，深/浅主题自动取色：
// bg-cyan-600/20 → --accent-wash-20、text-cyan-400 → --accent，
// 描边由 theme-*.css 的 button.mode-active 规则统一给 --accent-a55。
const MODE_OPTIONS: { value: DriveMode; labelKey: string }[] = [
  { value: 'user', labelKey: 'drive.modeUser' },
  { value: 'local_angle', labelKey: 'drive.modeSemiAuto' },
  { value: 'local', labelKey: 'drive.modeFullAuto' },
];

/** 分段选中态：accent 浅底 + accent 文字（与全站分段控件同一语言）。 */
const ACTIVE_CLASS = 'bg-cyan-600/20 text-cyan-400';

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
                ? `mode-active ${ACTIVE_CLASS}`
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
