import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ChevronLeft, RefreshCw, X } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { useGamepadStore } from '../../store/useGamepadStore';
import { axisHint, clampNumber, mapAxis } from '../../lib/gamepadMapping';

interface GamepadCalibrationWizardProps {
  open: boolean;
  connected: boolean;
  axes: number[];
  mapping?: string;
  padId?: string;
  onClose: () => void;
}

const TOTAL_STEPS = 4;
const STEER_DETECT_MS = 3000;
const THROTTLE_DETECT_MS = 3000;
const DEADZONE_DETECT_MS = 2000;

interface DetectState {
  kind: 'steer' | 'throttle' | 'deadzone';
  startedAt: number;
  duration: number;
  baseline: number[];
  min: number[];
  max: number[];
}

const AxisBar: React.FC<{ value: number; color?: string }> = ({ value, color = '#52525b' }) => {
  const pct = Math.abs(value) * 50;
  const style: React.CSSProperties =
    value >= 0
      ? { left: '50%', width: pct + '%', background: color }
      : { right: '50%', width: pct + '%', background: color };
  return (
    <div className="relative h-2 flex-1 rounded-full bg-zinc-800 overflow-hidden">
      <div className="absolute top-0 bottom-0 left-1/2 w-px bg-zinc-600" />
      <div className="absolute top-0 bottom-0 rounded-full" style={style} />
    </div>
  );
};

export const GamepadCalibrationWizard: React.FC<GamepadCalibrationWizardProps> = ({
  open,
  connected,
  axes,
  mapping,
  padId,
  onClose,
}) => {
  const { t } = useTranslation();
  const { config, patchAxis, bindPad } = useGamepadStore();
  const [step, setStep] = useState(0);
  const [detecting, setDetecting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [detectedAxis, setDetectedAxis] = useState<number | null>(null);
  const [deadzoneResult, setDeadzoneResult] = useState<number | null>(null);
  const detectRef = useRef<DetectState | null>(null);
  const axesRef = useRef<number[]>(axes);
  axesRef.current = axes;

  const finishDetect = useCallback(() => {
    const state = detectRef.current;
    if (!state) return;
    detectRef.current = null;
    setDetecting(false);
    setProgress(1);

    const snapshot = useGamepadStore.getState();
    if (state.kind === 'deadzone') {
      const sAxis = snapshot.config.steering.axis;
      const tAxis = snapshot.config.throttle.axis;
      const sNoise = Math.max(Math.abs(state.min[sAxis] ?? 0), Math.abs(state.max[sAxis] ?? 0));
      const tNoise = Math.max(Math.abs(state.min[tAxis] ?? 0), Math.abs(state.max[tAxis] ?? 0));
      const noise = Math.max(sNoise, tNoise, 0);
      const dz = Math.round(clampNumber(noise + 0.03, 0.04, 0.3) * 100) / 100;
      snapshot.setDeadzone(dz);
      setDeadzoneResult(dz);
      return;
    }

    let best = -1;
    let bestRange = 0;
    for (let i = 0; i < state.baseline.length; i += 1) {
      const range = (state.max[i] ?? 0) - (state.min[i] ?? 0);
      if (range > bestRange) {
        bestRange = range;
        best = i;
      }
    }
    if (best >= 0 && bestRange > 0.25) {
      snapshot.patchAxis(state.kind === 'steer' ? 'steering' : 'throttle', { axis: best });
      setDetectedAxis(best);
    } else {
      setDetectedAxis(null);
    }
  }, []);

  const startDetect = useCallback((kind: DetectState['kind'], duration: number) => {
    const count = Math.max(axesRef.current.length, 1);
    const baseline = Array.from({ length: count }, (_, i) => axesRef.current[i] ?? 0);
    detectRef.current = {
      kind,
      startedAt: Date.now(),
      duration,
      baseline,
      min: baseline.slice(),
      max: baseline.slice(),
    };
    setDetecting(true);
    setProgress(0);
    setDetectedAxis(null);
    setDeadzoneResult(null);
  }, []);

  // 累积轴变化并在到达时长后结算识别结果
  useEffect(() => {
    const state = detectRef.current;
    if (!state) return;
    const now = Date.now();
    for (let i = 0; i < axes.length; i += 1) {
      const value = axes[i];
      state.min[i] = state.min[i] === undefined ? value : Math.min(state.min[i], value);
      state.max[i] = state.max[i] === undefined ? value : Math.max(state.max[i], value);
    }
    setProgress(Math.min(1, (now - state.startedAt) / state.duration));
    if (now - state.startedAt >= state.duration) finishDetect();
  }, [axes, finishDetect]);

  // 打开时重置并自动识别转向轴
  useEffect(() => {
    if (!open) {
      detectRef.current = null;
      setDetecting(false);
      return;
    }
    if (!connected) return;
    setStep(0);
    setDetectedAxis(null);
    setDeadzoneResult(null);
    const timer = window.setTimeout(() => startDetect('steer', STEER_DETECT_MS), 300);
    return () => window.clearTimeout(timer);
  }, [open, connected, startDetect]);

  if (!open) return null;

  const steerPreview = mapAxis(axes[config.steering.axis], config.steering);
  const throttlePreview = mapAxis(axes[config.throttle.axis], config.throttle);
  const axisCount = Math.max(axes.length, 1);

  const goTo = (next: number) => {
    setStep(next);
    setDetectedAxis(null);
    setDeadzoneResult(null);
    if (next === 2) startDetect('throttle', THROTTLE_DETECT_MS);
  };

  const handleSave = () => {
    if (padId) bindPad(padId);
    onClose();
  };

  const axisList = (
    <div className="mt-3 space-y-1.5">
      {Array.from({ length: axisCount }, (_, i) => {
        const value = axes[i] ?? 0;
        const active = i === detectedAxis;
        return (
          <div key={i} className="flex items-center gap-2 text-[10px] text-zinc-500">
            <span className={'w-10 shrink-0 ' + (active ? 'text-cyan-400' : '')}>
              {t('drive.gamepadAxisIndex', { index: i })}
            </span>
            <AxisBar value={value} color={active ? '#22d3ee' : '#52525b'} />
            <span className="w-10 shrink-0 text-right font-mono">{value.toFixed(2)}</span>
            <span className="w-16 shrink-0 truncate text-zinc-600">{axisHint(i, mapping)}</span>
          </div>
        );
      })}
    </div>
  );

  const progressBar = (
    <div className="mt-3">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
        <div className="h-full rounded-full bg-cyan-500 transition-[width] duration-100" style={{ width: progress * 100 + '%' }} />
      </div>
      <p className="mt-1.5 text-[11px] text-cyan-300">{t('drive.gpWizDetecting')}</p>
    </div>
  );

  const stepBody = () => {
    if (!connected && step < 3) {
      return <p className="text-[12px] text-amber-400">{t('drive.gpWizNoGamepad')}</p>;
    }
    if (step === 0) {
      return (
        <div>
          <p className="text-[12px] text-zinc-400">{t('drive.gpWizStepSteerHint')}</p>
          {axisList}
          {detecting ? progressBar : detectedAxis !== null ? (
            <p className="mt-3 text-[11px] text-emerald-400">{t('drive.gpWizDetected', { index: detectedAxis })}</p>
          ) : (
            <button type="button" onClick={() => startDetect('steer', STEER_DETECT_MS)} className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-1.5 text-[11px] text-cyan-300 hover:bg-cyan-500/20">
              <RefreshCw className="h-3.5 w-3.5" />
              {t('drive.gpWizDetectSteer')}
            </button>
          )}
        </div>
      );
    }
    if (step === 1) {
      return (
        <div>
          <p className="text-[12px] text-zinc-400">{t('drive.gpWizStepDirHint')}</p>
          <div className="mt-3 flex items-center gap-2 text-[11px] text-zinc-500">
            <span className="w-10 shrink-0">{t('drive.gamepadAngle')}</span>
            <AxisBar value={steerPreview} color="#22d3ee" />
            <span className="w-12 shrink-0 text-right font-mono">{steerPreview.toFixed(2)}</span>
          </div>
          <button type="button" onClick={() => patchAxis('steering', { invert: !config.steering.invert })} className="mt-3 rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-[11px] text-zinc-300 hover:bg-zinc-700">
            {config.steering.invert ? t('drive.gpWizInverted') : t('drive.gpWizNormal')} · {t('drive.gpWizDirectionFlip')}
          </button>
        </div>
      );
    }
    if (step === 2) {
      return (
        <div>
          <p className="text-[12px] text-zinc-400">{t('drive.gpWizStepThrottleHint')}</p>
          {axisList}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {detecting ? progressBar : detectedAxis !== null ? (
              <span className="text-[11px] text-emerald-400">{t('drive.gpWizDetected', { index: detectedAxis })}</span>
            ) : (
              <button type="button" onClick={() => startDetect('throttle', THROTTLE_DETECT_MS)} className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-1.5 text-[11px] text-cyan-300 hover:bg-cyan-500/20">
                <RefreshCw className="h-3.5 w-3.5" />
                {t('drive.gpWizDetectThrottle')}
              </button>
            )}
            {!detecting && (
              <button type="button" onClick={() => startDetect('deadzone', DEADZONE_DETECT_MS)} className="rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-[11px] text-zinc-300 hover:bg-zinc-700">
                {t('drive.gpWizDetectDeadzone')}
              </button>
            )}
          </div>
          {deadzoneResult !== null && (
            <p className="mt-2 text-[11px] text-emerald-400">{t('drive.gpWizDeadzoneSet', { value: deadzoneResult.toFixed(2) })}</p>
          )}
          <div className="mt-3 flex items-center gap-2 text-[11px] text-zinc-500">
            <span className="w-10 shrink-0">{t('drive.gamepadThrottle')}</span>
            <AxisBar value={throttlePreview} color="#34d399" />
            <span className="w-12 shrink-0 text-right font-mono">{throttlePreview.toFixed(2)}</span>
          </div>
        </div>
      );
    }
    const row = (label: string, value: React.ReactNode) => (
      <div className="flex items-center justify-between border-b border-zinc-800 py-1.5 text-[12px] last:border-0">
        <span className="text-zinc-500">{label}</span>
        <span className="font-mono text-zinc-300">{value}</span>
      </div>
    );
    return (
      <div>
        <p className="text-[12px] text-zinc-400">{t('drive.gpWizStepDoneHint')}</p>
        <div className="mt-3 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-1">
          {row(t('drive.gpWizSummarySteering'), t('drive.gamepadAxisIndex', { index: config.steering.axis }) + ' · ' + (config.steering.invert ? t('drive.gpWizInverted') : t('drive.gpWizNormal')))}
          {row(t('drive.gpWizSummaryThrottle'), t('drive.gamepadAxisIndex', { index: config.throttle.axis }) + ' · ' + (config.throttle.invert ? t('drive.gpWizInverted') : t('drive.gpWizNormal')))}
          {row(t('drive.gpWizSummaryDeadzone'), config.steering.deadzone.toFixed(2))}
        </div>
        <button type="button" onClick={() => goTo(0)} className="mt-3 rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-[11px] text-zinc-300 hover:bg-zinc-700">
          {t('drive.gpWizRecalibrate')}
        </button>
      </div>
    );
  };

  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" data-testid="gamepad-calibration-wizard">
      <div className="w-full max-w-md rounded-xl border border-zinc-700 bg-zinc-900 p-4 shadow-2xl">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-medium text-zinc-200">
            {t('drive.gpWizTitle')}
            <span className="text-[11px] font-normal text-zinc-500">{t('drive.gpWizStep', { current: step + 1, total: TOTAL_STEPS })}</span>
          </div>
          <button type="button" onClick={onClose} aria-label={t('drive.gpWizClose')} className="rounded p-1 text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="mt-3 flex gap-1.5">
          {Array.from({ length: TOTAL_STEPS }, (_, i) => (
            <span key={i} className={'h-1 flex-1 rounded-full ' + (i <= step ? 'bg-cyan-500' : 'bg-zinc-700')} />
          ))}
        </div>
        <div className="mt-4">
          <h4 className="mb-1 text-[13px] font-medium text-zinc-200">
            {[t('drive.gpWizStepSteerTitle'), t('drive.gpWizStepDirTitle'), t('drive.gpWizStepThrottleTitle'), t('drive.gpWizStepDoneTitle')][step]}
          </h4>
          {stepBody()}
        </div>
        <div className="mt-5 flex items-center justify-between gap-2">
          <button type="button" onClick={onClose} className="rounded-lg px-3 py-1.5 text-[11px] text-zinc-500 hover:text-zinc-300">
            {t('drive.gpWizSkip')}
          </button>
          <div className="flex items-center gap-2">
            {step > 0 && (
              <button type="button" onClick={() => goTo(step - 1)} className="inline-flex items-center gap-1 rounded-lg border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-[11px] text-zinc-300 hover:bg-zinc-700">
                <ChevronLeft className="h-3.5 w-3.5" />
                {t('drive.gpWizPrev')}
              </button>
            )}
            {step < TOTAL_STEPS - 1 ? (
              <button type="button" onClick={() => goTo(step + 1)} className="rounded-lg border border-cyan-500/50 bg-cyan-500/15 px-3 py-1.5 text-[11px] text-cyan-300 hover:bg-cyan-500/25">
                {t('drive.gpWizNext')}
              </button>
            ) : (
              <button type="button" onClick={handleSave} className="rounded-lg border border-cyan-500/50 bg-cyan-500/15 px-3 py-1.5 text-[11px] text-cyan-300 hover:bg-cyan-500/25">
                {t('drive.gpWizSave')}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
};
