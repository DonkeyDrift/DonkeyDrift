import React, { useState } from 'react';
import { getApiErrorMessage, sendCalibrate } from '../services/api';
import { Save, Send } from 'lucide-react';

interface CalibrateParams {
  STEERING_LEFT_PWM: number;
  STEERING_RIGHT_PWM: number;
  THROTTLE_FORWARD_PWM: number;
  THROTTLE_STOPPED_PWM: number;
  THROTTLE_REVERSE_PWM: number;
}

const DEFAULT_PARAMS: CalibrateParams = {
  STEERING_LEFT_PWM: 460,
  STEERING_RIGHT_PWM: 290,
  THROTTLE_FORWARD_PWM: 500,
  THROTTLE_STOPPED_PWM: 370,
  THROTTLE_REVERSE_PWM: 220,
};

const SliderRow: React.FC<{
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
  onTest: () => void;
  isTesting?: boolean;
  hint?: string;
}> = ({ label, value, min, max, onChange, onTest, isTesting = false, hint }) => (
  <div className="space-y-2">
    <div className="flex items-center justify-between">
      <span className="text-sm text-zinc-300">{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-xs text-cyan-400 font-mono w-12 text-right">{value}</span>
        <button
          onClick={onTest}
          disabled={isTesting}
          className="p-1 text-zinc-500 hover:text-cyan-400 transition-colors disabled:opacity-50"
          title="实时测试当前值"
        >
          <Send className={`w-3.5 h-3.5 ${isTesting ? 'animate-pulse text-cyan-400' : ''}`} />
        </button>
      </div>
    </div>
    <input
      type="range"
      min={min}
      max={max}
      step={1}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-full h-1.5 bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-cyan-500"
    />
    {hint && <p className="text-[10px] text-zinc-500">{hint}</p>}
  </div>
);

export const CalibratePage: React.FC = () => {
  const [params, setParams] = useState<CalibrateParams>(DEFAULT_PARAMS);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);

  const setParam = <K extends keyof CalibrateParams>(key: K, value: CalibrateParams[K]) => {
    setParams((prev) => ({ ...prev, [key]: value }));
  };

  const testValue = async (key: keyof CalibrateParams) => {
    setTesting(key);
    try {
      await sendCalibrate({ [key]: params[key] });
    } finally {
      setTimeout(() => setTesting(null), 300);
    }
  };

  const saveAll = async () => {
    setSaving(true);
    try {
      await sendCalibrate({ ...params, save: true });
      alert('校准参数已保存到车端配置');
    } catch (error) {
      alert(`保存失败: ${getApiErrorMessage(error)}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-zinc-200">舵机与电调校准</h2>
        <button
          onClick={saveAll}
          disabled={saving}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30 rounded text-xs font-medium transition-colors disabled:opacity-50"
        >
          <Save className="w-3.5 h-3.5" />
          {saving ? '保存中...' : '保存全部到车端'}
        </button>
      </div>

      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-5 space-y-6">
        <div>
          <h3 className="text-sm font-medium text-zinc-300 mb-4 border-b border-zinc-800 pb-2">舵机 PWM 校准</h3>
          <div className="space-y-5">
            <SliderRow
              label="左转极限 PWM"
              value={params.STEERING_LEFT_PWM}
              min={200}
              max={600}
              onChange={(v) => setParam('STEERING_LEFT_PWM', v)}
              onTest={() => testValue('STEERING_LEFT_PWM')}
              isTesting={testing === 'STEERING_LEFT_PWM'}
              hint="向左打满舵时的 PWM 值"
            />
            <SliderRow
              label="右转极限 PWM"
              value={params.STEERING_RIGHT_PWM}
              min={200}
              max={600}
              onChange={(v) => setParam('STEERING_RIGHT_PWM', v)}
              onTest={() => testValue('STEERING_RIGHT_PWM')}
              isTesting={testing === 'STEERING_RIGHT_PWM'}
              hint="向右打满舵时的 PWM 值"
            />
          </div>
        </div>

        <div>
          <h3 className="text-sm font-medium text-zinc-300 mb-4 border-b border-zinc-800 pb-2">电调 PWM 校准</h3>
          <div className="space-y-5">
            <SliderRow
              label="全油门前进 PWM"
              value={params.THROTTLE_FORWARD_PWM}
              min={100}
              max={700}
              onChange={(v) => setParam('THROTTLE_FORWARD_PWM', v)}
              onTest={() => testValue('THROTTLE_FORWARD_PWM')}
              isTesting={testing === 'THROTTLE_FORWARD_PWM'}
              hint="踩满油门时的 PWM 值，先从小值开始测试"
            />
            <SliderRow
              label="油门零点 PWM"
              value={params.THROTTLE_STOPPED_PWM}
              min={200}
              max={600}
              onChange={(v) => setParam('THROTTLE_STOPPED_PWM', v)}
              onTest={() => testValue('THROTTLE_STOPPED_PWM')}
              isTesting={testing === 'THROTTLE_STOPPED_PWM'}
              hint="电机完全静止时的 PWM 值"
            />
            <SliderRow
              label="全油门倒车 PWM"
              value={params.THROTTLE_REVERSE_PWM}
              min={100}
              max={500}
              onChange={(v) => setParam('THROTTLE_REVERSE_PWM', v)}
              onTest={() => testValue('THROTTLE_REVERSE_PWM')}
              isTesting={testing === 'THROTTLE_REVERSE_PWM'}
              hint="踩满倒车时的 PWM 值，先从小值开始测试"
            />
          </div>
        </div>
      </div>

      <p className="text-xs text-zinc-500 text-center">
        提示：点击每项右侧的「发送」按钮可以实时测试当前 PWM 值，确认无误后再点击顶部按钮保存全部参数
      </p>
    </div>
  );
};
