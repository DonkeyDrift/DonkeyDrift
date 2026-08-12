import React, { useRef, useState } from 'react';
import { ChevronDown, ChevronUp, RotateCcw, Download, Upload } from 'lucide-react';
import { useDriveStore, DriveParams } from '../../store/useDriveStore';
import { useTranslation } from '@/i18n';

interface ParamSliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  unit?: string;
}

const ParamSlider: React.FC<ParamSliderProps> = ({ label, value, min, max, step, onChange, unit = '' }) => (
  <div>
    <div className="flex items-center justify-between mb-1">
      <span className="text-xs text-zinc-400">{label}</span>
      <span className="text-xs text-zinc-500">{value.toFixed(step < 0.01 ? 3 : 2)}{unit}</span>
    </div>
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-full h-1.5 appearance-none cursor-pointer
        [&::-webkit-slider-runnable-track]:h-1.5 [&::-webkit-slider-runnable-track]:bg-zinc-800 [&::-webkit-slider-runnable-track]:rounded-lg
        [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-2
        [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:border-none
        [&::-webkit-slider-thumb]:-mt-px [&::-webkit-slider-thumb]:cursor-pointer
        [&::-moz-range-track]:h-1.5 [&::-moz-range-track]:bg-zinc-800 [&::-moz-range-track]:rounded-lg
        [&::-moz-range-thumb]:w-3 [&::-moz-range-thumb]:h-2 [&::-moz-range-thumb]:rounded-full
        [&::-moz-range-thumb]:bg-white [&::-moz-range-thumb]:border-none [&::-moz-range-thumb]:cursor-pointer"
    />
  </div>
);

interface ParameterPanelProps {
  className?: string;
}

export const ParameterPanel: React.FC<ParameterPanelProps> = ({ className = '' }) => {
  const { t } = useTranslation();
  const { params, setParam, setPidParam, resetToDefault, importParams } = useDriveStore();
  const [open, setOpen] = useState(false);
  const importRef = useRef<HTMLInputElement>(null);

  const handleExport = () => {
    const blob = new Blob([JSON.stringify({ params }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `drive-params-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const data = JSON.parse(ev.target?.result as string) as DriveParams;
        importParams(data);
        alert(t('driveViz.importSuccess'));
      } catch {
        alert(t('driveViz.importFormatError'));
      }
    };
    reader.readAsText(file);
  };

  return (
    <div className={`w-full bg-zinc-950 border border-zinc-800 rounded-lg overflow-hidden ${className}`}>
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-3 py-2 flex items-center justify-between text-xs text-zinc-400 hover:text-zinc-200"
      >
        <span className="font-medium">{t('driveViz.controlParams')}</span>
        {open ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
      </button>

      {open && (
        <div className="px-3 pb-3 space-y-3 border-t border-zinc-800 pt-3">
          <div className="space-y-3">
            <p className="text-[10px] text-zinc-500 font-medium uppercase tracking-wider">{t('driveViz.pidParams')}</p>
            <ParamSlider
              label={t('driveViz.kp')}
              value={params.pid.kp}
              min={0}
              max={3}
              step={0.05}
              onChange={(v) => setPidParam('kp', v)}
            />
            <ParamSlider
              label={t('driveViz.ki')}
              value={params.pid.ki}
              min={0}
              max={1}
              step={0.01}
              onChange={(v) => setPidParam('ki', v)}
            />
            <ParamSlider
              label={t('driveViz.kd')}
              value={params.pid.kd}
              min={0}
              max={0.1}
              step={0.001}
              onChange={(v) => setPidParam('kd', v)}
            />
          </div>

          <div className="space-y-3">
            <p className="text-[10px] text-zinc-500 font-medium uppercase tracking-wider">{t('driveViz.responseRates')}</p>
            <ParamSlider
              label={t('driveViz.recenterRate')}
              value={params.recenterRate}
              min={0}
              max={2}
              step={0.05}
              onChange={(v) => setParam('recenterRate', v)}
              unit=" /s"
            />
            <ParamSlider
              label={t('driveViz.steerRate')}
              value={params.steerRate}
              min={0}
              max={3}
              step={0.05}
              onChange={(v) => setParam('steerRate', v)}
              unit=" /s"
            />
            <ParamSlider
              label={t('driveViz.accelRate')}
              value={params.accelRate}
              min={0}
              max={3}
              step={0.05}
              onChange={(v) => setParam('accelRate', v)}
              unit=" /s"
            />
            <ParamSlider
              label={t('driveViz.brakeRate')}
              value={params.brakeRate}
              min={0}
              max={3}
              step={0.05}
              onChange={(v) => setParam('brakeRate', v)}
              unit=" /s"
            />
          </div>

          <div className="flex gap-2 pt-2 border-t border-zinc-800">
            <button
              onClick={resetToDefault}
              className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-[11px] whitespace-nowrap text-zinc-400 hover:text-zinc-200 bg-zinc-800 rounded transition-colors"
            >
              <RotateCcw size={12} className="shrink-0" />
              <span className="whitespace-nowrap">{t('driveViz.resetDefault')}</span>
            </button>
            <button
              onClick={handleExport}
              className="flex-1 flex items-center justify-center gap-1 px-2 py-1.5 text-[11px] whitespace-nowrap text-zinc-400 hover:text-zinc-200 bg-zinc-800 rounded transition-colors"
            >
              <Download size={12} className="shrink-0" />
              <span className="whitespace-nowrap">{t('driveViz.export')}</span>
            </button>
            <label className="flex-1">
              <input
                ref={importRef}
                type="file"
                accept=".json"
                onChange={handleImport}
                className="hidden"
              />
              <button
                onClick={() => importRef.current?.click()}
                className="w-full flex items-center justify-center gap-1 px-2 py-1.5 text-[11px] whitespace-nowrap text-zinc-400 hover:text-zinc-200 bg-zinc-800 rounded transition-colors"
              >
                <Upload size={12} className="shrink-0" />
                <span className="whitespace-nowrap">{t('driveViz.import')}</span>
              </button>
            </label>
          </div>
          <p className="text-[10px] text-zinc-600 text-center">
            {t('driveViz.autoSaveNote')}
          </p>
        </div>
      )}
    </div>
  );
};
