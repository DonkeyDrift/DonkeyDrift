import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, Gamepad2, RotateCcw, Wand2 } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { useGamepadStore } from '../../store/useGamepadStore';
import { GAMEPAD_PRESET_ORDER, axisHint, mapAxis } from '../../lib/gamepadMapping';
import { GamepadCalibrationWizard } from './GamepadCalibrationWizard';

interface GamepadConfigPanelProps {
  axes: number[];
  padId?: string;
  mapping?: string;
  connected: boolean;
  /** 选中「手柄」输入源时自动展开 */
  defaultOpen?: boolean;
  className?: string;
}

const AxisBar: React.FC<{ value: number; color?: string }> = ({ value, color = '#52525b' }) => {
  const pct = Math.abs(value) * 50;
  const style: React.CSSProperties =
    value >= 0
      ? { left: '50%', width: pct + '%', background: color }
      : { right: '50%', width: pct + '%', background: color };
  return (
    <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-zinc-800">
      <div className="absolute top-0 bottom-0 left-1/2 w-px bg-zinc-600" />
      <div className="absolute top-0 bottom-0 rounded-full" style={style} />
    </div>
  );
};

const MiniSlider: React.FC<{
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}> = ({ label, value, min, max, step, onChange }) => (
  <div>
    <div className="mb-1 flex items-center justify-between text-[11px] text-zinc-500">
      <span>{label}</span>
      <span className="font-mono text-zinc-400">{value.toFixed(2)}</span>
    </div>
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="h-3 w-full cursor-pointer accent-cyan-400"
    />
  </div>
);

export const GamepadConfigPanel: React.FC<GamepadConfigPanelProps> = ({
  axes,
  padId,
  mapping,
  connected,
  defaultOpen = false,
  className = '',
}) => {
  const { t } = useTranslation();
  const { config, setPreset, patchAxis, setDeadzone, reset } = useGamepadStore();
  const [open, setOpen] = useState(defaultOpen);
  const [wizardOpen, setWizardOpen] = useState(false);
  const dismissedPadsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (defaultOpen) setOpen(true);
  }, [defaultOpen]);

  // 首次连接某只手柄（本地未校准过）时自动弹出向导；每只手柄每会话只弹一次
  useEffect(() => {
    if (!connected || !padId) return;
    if (config.padId === padId) return;
    if (dismissedPadsRef.current.has(padId)) return;
    dismissedPadsRef.current.add(padId);
    setOpen(true);
    setWizardOpen(true);
  }, [connected, padId, config.padId]);

  const axisCount = Math.max(axes.length, config.steering.axis + 1, config.throttle.axis + 1, 6);
  const axisOptions = Array.from({ length: axisCount }, (_, i) => i);
  const steerOut = mapAxis(axes[config.steering.axis], config.steering);
  const throttleOut = mapAxis(axes[config.throttle.axis], config.throttle);

  return (
    <div
      data-testid="gamepad-config-panel"
      className={'w-full overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 ' + className}
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        data-testid="gamepad-config-toggle"
        className="flex w-full items-center justify-between px-3 py-2 text-xs text-zinc-400 hover:text-zinc-200"
      >
        <span className="flex items-center gap-1.5 font-medium">
          <Gamepad2 className="h-4 w-4" />
          {t('drive.gamepadSettings')}
          {connected && <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />}
        </span>
        {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
      </button>

      {open && (
        <div className="space-y-3 border-t border-zinc-800 px-3 pb-3 pt-3">
          <div className="flex items-center justify-between text-[10px] text-zinc-500">
            <span className="uppercase tracking-wider">{t('drive.gamepadPadLabel')}</span>
            <span className="max-w-[190px] truncate">{connected ? padId || '-' : t('drive.gamepadNotDetected')}</span>
          </div>

          <div>
            <p className="mb-1.5 text-[10px] uppercase tracking-wider text-zinc-500">{t('drive.gamepadPreset')}</p>
            <div className="flex flex-wrap gap-1.5">
              {GAMEPAD_PRESET_ORDER.map((preset) => (
                <button
                  key={preset.id}
                  type="button"
                  data-preset={preset.id}
                  onClick={() => setPreset(preset.id)}
                  className={
                    'rounded-lg border px-2 py-1 text-[11px] transition-colors ' +
                    (config.preset === preset.id
                      ? 'border-cyan-500/50 bg-cyan-500/15 text-cyan-300'
                      : 'border-zinc-700 bg-zinc-800 text-zinc-400 hover:text-zinc-200')
                  }
                >
                  {t(preset.labelKey)}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className="mb-1 text-[10px] uppercase tracking-wider text-zinc-500">{t('drive.gamepadSteeringAxis')}</p>
              <select
                aria-label={t('drive.gamepadSteeringAxis')}
                value={config.steering.axis}
                onChange={(e) => patchAxis('steering', { axis: Number(e.target.value) })}
                className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1 text-[11px] text-zinc-200"
              >
                {axisOptions.map((i) => (
                  <option key={i} value={i}>
                    {t('drive.gamepadAxisIndex', { index: i })}
                    {axisHint(i, mapping) ? ' · ' + axisHint(i, mapping) : ''}
                  </option>
                ))}
              </select>
              <label className="mt-1.5 flex items-center gap-1.5 text-[11px] text-zinc-400">
                <input
                  type="checkbox"
                  checked={config.steering.invert}
                  onChange={(e) => patchAxis('steering', { invert: e.target.checked })}
                  className="accent-cyan-400"
                />
                {t('drive.gamepadSteerInvert')}
              </label>
            </div>
            <div>
              <p className="mb-1 text-[10px] uppercase tracking-wider text-zinc-500">{t('drive.gamepadThrottleAxis')}</p>
              <select
                aria-label={t('drive.gamepadThrottleAxis')}
                value={config.throttle.axis}
                onChange={(e) => patchAxis('throttle', { axis: Number(e.target.value) })}
                className="w-full rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1 text-[11px] text-zinc-200"
              >
                {axisOptions.map((i) => (
                  <option key={i} value={i}>
                    {t('drive.gamepadAxisIndex', { index: i })}
                    {axisHint(i, mapping) ? ' · ' + axisHint(i, mapping) : ''}
                  </option>
                ))}
              </select>
              <label className="mt-1.5 flex items-center gap-1.5 text-[11px] text-zinc-400">
                <input
                  type="checkbox"
                  checked={config.throttle.invert}
                  onChange={(e) => patchAxis('throttle', { invert: e.target.checked })}
                  className="accent-cyan-400"
                />
                {t('drive.gamepadThrottleInvert')}
              </label>
            </div>
          </div>

          <MiniSlider
            label={t('drive.gamepadDeadzone')}
            value={config.steering.deadzone}
            min={0}
            max={0.3}
            step={0.01}
            onChange={setDeadzone}
          />
          <div className="grid grid-cols-2 gap-3">
            <MiniSlider
              label={t('drive.gamepadSteerMax')}
              value={config.steering.max}
              min={0.2}
              max={1}
              step={0.05}
              onChange={(value) => patchAxis('steering', { max: value })}
            />
            <MiniSlider
              label={t('drive.gamepadThrottleMax')}
              value={config.throttle.max}
              min={0.2}
              max={1}
              step={0.05}
              onChange={(value) => patchAxis('throttle', { max: value })}
            />
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <p className="text-[10px] uppercase tracking-wider text-zinc-500">{t('drive.gamepadAxisMonitor')}</p>
              <p className="text-[10px] text-zinc-600">{t('drive.gamepadOutputPreview')}</p>
            </div>
            {axes.length === 0 ? (
              <p className="text-[11px] text-zinc-600">{t('drive.gamepadAxisEmpty')}</p>
            ) : (
              <div className="space-y-1.5">
                {axes.map((value, i) => {
                  const isSteer = i === config.steering.axis;
                  const isThrottle = i === config.throttle.axis;
                  return (
                    <div key={i} className="flex items-center gap-2 text-[10px] text-zinc-500">
                      <span className={'w-10 shrink-0 ' + (isSteer ? 'text-cyan-400' : isThrottle ? 'text-emerald-400' : '')}>
                        {t('drive.gamepadAxisIndex', { index: i })}
                      </span>
                      <AxisBar value={value} color={isSteer ? '#22d3ee' : isThrottle ? '#34d399' : '#52525b'} />
                      <span className="w-10 shrink-0 text-right font-mono">{value.toFixed(2)}</span>
                      <span className="flex shrink-0 gap-1">
                        <button
                          type="button"
                          onClick={() => patchAxis('steering', { axis: i })}
                          className="rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] text-zinc-400 hover:text-cyan-300"
                        >
                          {t('drive.gamepadSetAsSteering')}
                        </button>
                        <button
                          type="button"
                          onClick={() => patchAxis('throttle', { axis: i })}
                          className="rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] text-zinc-400 hover:text-emerald-300"
                        >
                          {t('drive.gamepadSetAsThrottle')}
                        </button>
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
            <div className="mt-2 space-y-1.5 text-[11px] text-zinc-500">
              <div className="flex items-center gap-2">
                <span className="w-10 shrink-0">{t('drive.gamepadAngle')}</span>
                <AxisBar value={steerOut} color="#22d3ee" />
                <span className="w-12 shrink-0 text-right font-mono">{steerOut.toFixed(2)}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-10 shrink-0">{t('drive.gamepadThrottle')}</span>
                <AxisBar value={throttleOut} color="#34d399" />
                <span className="w-12 shrink-0 text-right font-mono">{throttleOut.toFixed(2)}</span>
              </div>
            </div>
          </div>

          <div className="flex gap-2 border-t border-zinc-800 pt-2">
            <button
              type="button"
              onClick={() => setWizardOpen(true)}
              className="flex flex-1 items-center justify-center gap-1 rounded bg-cyan-500/15 px-2 py-1.5 text-[11px] text-cyan-300 hover:bg-cyan-500/25"
            >
              <Wand2 className="h-3.5 w-3.5 shrink-0" />
              <span className="whitespace-nowrap">{t('drive.gamepadCalibrate')}</span>
            </button>
            <button
              type="button"
              onClick={reset}
              className="flex items-center justify-center gap-1 rounded bg-zinc-800 px-2 py-1.5 text-[11px] text-zinc-400 hover:text-zinc-200"
            >
              <RotateCcw className="h-3.5 w-3.5 shrink-0" />
              <span className="whitespace-nowrap">{t('drive.gamepadReset')}</span>
            </button>
          </div>
        </div>
      )}

      <GamepadCalibrationWizard
        open={wizardOpen}
        connected={connected}
        axes={axes}
        mapping={mapping}
        padId={padId}
        onClose={() => setWizardOpen(false)}
      />
    </div>
  );
};
