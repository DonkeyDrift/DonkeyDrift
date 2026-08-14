import React, { useEffect, useRef, useState } from 'react';
import { Gamepad2, Smartphone, Joystick, Keyboard, ChevronDown, ChevronUp } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { useResolvedTheme } from '@/lib/theme';

export type InputSource = 'joystick' | 'keyboard' | 'gamepad' | 'gyro';

interface InputSourceSelectorProps {
  value: InputSource;
  onChange: (source: InputSource) => void;
  gamepadConnected?: boolean;
  gyroAvailable?: boolean;
  className?: string;
}

const SOURCES: { value: InputSource; labelKey: string; icon: React.ReactNode }[] = [
  { value: 'joystick', labelKey: 'drive.sourceJoystick', icon: <Joystick className="w-3.5 h-3.5" /> },
  { value: 'keyboard', labelKey: 'drive.sourceKeyboard', icon: <Keyboard className="w-3.5 h-3.5" /> },
  { value: 'gamepad', labelKey: 'drive.sourceGamepad', icon: <Gamepad2 className="w-3.5 h-3.5" /> },
  { value: 'gyro', labelKey: 'drive.sourceGyro', icon: <Smartphone className="w-3.5 h-3.5" /> },
];

export const InputSourceSelector: React.FC<InputSourceSelectorProps> = ({
  value,
  onChange,
  gamepadConnected = false,
  gyroAvailable = true,
  className = '',
}) => {
  const { t } = useTranslation();
  const theme = useResolvedTheme();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // 任意值阴影皮肤 CSS 覆盖不到:浅色改用皮肤同款软 slate 阴影
  const panelShadow = theme === 'light'
    ? 'shadow-[0_8px_24px_rgba(15,23,42,0.12)]'
    : 'shadow-[0_8px_24px_rgba(0,0,0,0.25)]';

  const selected = SOURCES.find((s) => s.value === value)!;
  const others = SOURCES.filter((s) => s.value !== value);

  const isDisabled = (source: InputSource) =>
    (source === 'gamepad' && !gamepadConnected) ||
    (source === 'gyro' && !gyroAvailable);

  const handleSelect = (source: InputSource) => {
    if (isDisabled(source)) return;
    onChange(source);
    setOpen(false);
  };

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  return (
    <div
      ref={containerRef}
      data-testid="input-source-selector"
      className={`relative inline-block ${className}`}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        onClick={() => setOpen(!open)}
        className="px-3 py-1.5 rounded-lg border border-zinc-800 bg-zinc-900 text-xs font-medium flex items-center justify-between gap-2 text-cyan-400 hover:bg-zinc-800 transition-colors whitespace-nowrap"
        title={t('drive.inputSource')}
      >
        <span className="flex items-center gap-1.5">
          {selected.icon}
          <span>{t(selected.labelKey)}</span>
          {selected.value === 'gamepad' && gamepadConnected && (
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          )}
        </span>
        {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
      </button>
      {open && (
        <div className="absolute top-full left-0 w-max min-w-full pt-1 z-50">
          <div className={`rounded-lg border border-zinc-800 bg-zinc-900 ${panelShadow} overflow-hidden`}>
            {others.map((src) => {
              const disabled = isDisabled(src.value);
              return (
                <button
                  key={src.value}
                  onClick={() => handleSelect(src.value)}
                  disabled={disabled}
                  className={`w-full px-3 py-1.5 text-xs font-medium flex items-center gap-1.5 transition-colors text-left whitespace-nowrap
                    ${disabled
                      ? 'text-zinc-600 cursor-not-allowed'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800'
                    }
                  `}
                  title={
                    src.value === 'gamepad'
                      ? gamepadConnected ? t('drive.gamepadConnected') : t('drive.gamepadNotDetected')
                      : src.value === 'gyro'
                        ? gyroAvailable ? t('drive.gyroSupported') : t('drive.gyroNotSupported')
                        : t(src.labelKey)
                  }
                >
                  {src.icon}
                  <span>{t(src.labelKey)}</span>
                  {src.value === 'gamepad' && gamepadConnected && (
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
