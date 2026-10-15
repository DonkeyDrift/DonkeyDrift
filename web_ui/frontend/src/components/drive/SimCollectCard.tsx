import React, { useState } from 'react';
import { ChevronDown, ChevronRight, FlaskConical, Loader2, Play, Square, X } from 'lucide-react';
import { SectionCardTitle } from '../ui/SectionCardTitle';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { useTranslation } from '@/i18n';
import { useSimCollectJob } from '../../hooks/useSimCollectJob';
import type { SimCollectStartParams } from '../../services/api';

/** 数字输入串 → number；空串/非法值返回 undefined（对应字段不发给后端，用其后端默认值）。 */
const parseNum = (s: string): number | undefined => {
  const v = parseFloat(s);
  return Number.isFinite(v) ? v : undefined;
};

interface NumberFieldProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  min?: number;
  max?: number;
  step?: number;
}

const NumberField: React.FC<NumberFieldProps> = ({ label, value, onChange, disabled, min, max, step }) => (
  <div>
    <label className="block text-xs text-zinc-400 mb-1">{label}</label>
    <Input
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      min={min}
      max={max}
      step={step}
    />
  </div>
);

/**
 * 「模拟器采集」抽屉面板内容：后端经 SSH 控制 Mac（dkc-mac）上的 donkey_sim 跑采集。
 * 由 DrivePage 右侧抽屉渲染——与虚拟摇杆共用面板槽（把手列中模拟器采集标签在摇杆下侧，
 * 互斥展开），仅模拟器目标渲染。有任务时详情自动展开（进度/结果反馈不可藏），
 * 空闲时手动展开高级参数，终态可关闭复位。
 */
export const SimCollectCard: React.FC = () => {
  const { t } = useTranslation();
  const { job, start, stop, reset } = useSimCollectJob();

  const [steps, setSteps] = useState('1500');
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [kp, setKp] = useState('0.55');
  const [kd, setKd] = useState('0.8');
  const [throttle, setThrottle] = useState('0.30');
  const [minThrottle, setMinThrottle] = useState('0.15');

  const running = job?.status === 'running' || job?.status === 'pending';
  const progress = job && job.total > 0 ? Math.min(100, Math.round((job.step / job.total) * 100)) : 0;
  // 有任务时详情区自动展开；空闲时由 advancedOpen 控制
  const hasJob = job !== null;
  const terminal = hasJob && (job.status === 'done' || job.status === 'error' || job.status === 'stopped');
  const showBody = hasJob || advancedOpen;

  const handleStart = () => {
    const params: SimCollectStartParams = {
      steps: parseNum(steps),
      kp: parseNum(kp),
      kd: parseNum(kd),
      throttle: parseNum(throttle),
      min_throttle: parseNum(minThrottle),
    };
    void start(params);
  };

  return (
    <div className="space-y-3">
      {/* 头部：与摇杆面板同款「标题 + 右侧控制」 */}
      <div className="flex items-center justify-between gap-2">
        <SectionCardTitle
          icon={<FlaskConical className="w-5 h-5" />}
          title={t('drive.simCollectTitle')}
          subtitle={t('drive.simCollectHint')}
          subtitleMarquee
        />
        {running ? (
          <Button onClick={() => void stop()} variant="danger" size="sm">
            <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" />
            <Square className="w-3.5 h-3.5 fill-current" />
            {t('drive.simCollectStop')}
          </Button>
        ) : (
          <Button onClick={handleStart} size="sm">
            <Play className="w-4 h-4" />
            {t('drive.simCollectStart')}
          </Button>
        )}
      </div>

      {/* 步数 */}
      <div className="max-w-xs">
        <NumberField
          label={t('drive.simCollectSteps')}
          value={steps}
          onChange={setSteps}
          disabled={running}
          min={1}
          step={100}
        />
      </div>

      {/* 高级参数：空闲时手动展开，运行中禁用编辑 */}
      {!hasJob && (
        <button
          type="button"
          onClick={() => setAdvancedOpen((v) => !v)}
          aria-expanded={advancedOpen}
          className="flex items-center gap-1 text-xs text-zinc-400 hover:text-zinc-200 transition-colors"
        >
          {advancedOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          {t('drive.simCollectAdvanced')}
        </button>
      )}

      {/* 详情区：空闲=高级参数表单；有任务=进度/结果/日志（自动展开） */}
      {showBody && (
        <div className="space-y-2">
          {/* 高级参数（showBody = advancedOpen，此处必有 advancedOpen） */}
          {!hasJob && advancedOpen && (
            <div className="grid grid-cols-2 gap-3">
              <NumberField label={t('drive.simCollectKp')} value={kp} onChange={setKp} disabled={running} step={0.05} />
              <NumberField label={t('drive.simCollectKd')} value={kd} onChange={setKd} disabled={running} step={0.05} />
              <NumberField label={t('drive.simCollectThrottle')} value={throttle} onChange={setThrottle} disabled={running} min={0} max={1} step={0.05} />
              <NumberField label={t('drive.simCollectMinThrottle')} value={minThrottle} onChange={setMinThrottle} disabled={running} min={0} max={1} step={0.05} />
            </div>
          )}

          {/* 运行中：进度条 + 实时 cte / speed */}
          {running && job && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs text-zinc-400">
                <span>{t('drive.simCollectRunning', { step: job.step, total: job.total })}</span>
                <span className="font-mono tnum">{progress}%</span>
              </div>
              <div className="w-full bg-zinc-800 rounded-full h-2">
                <div
                  className="bg-cyan-500 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <div className="flex gap-4 text-xs text-zinc-400">
                <span>
                  {t('drive.simCollectCte')}:{' '}
                  <span className="font-mono text-zinc-200">{job.cte != null ? job.cte.toFixed(3) : '-'}</span>
                </span>
                <span>
                  {t('drive.simCollectSpeed')}:{' '}
                  <span className="font-mono text-zinc-200">{job.speed != null ? job.speed.toFixed(2) : '-'}</span>
                </span>
              </div>
            </div>
          )}

          {/* 完成：结果摘要 */}
          {job?.status === 'done' && job.result && (
            <div className="space-y-2">
              <div className="text-green-400 text-sm">{t('drive.simCollectResult')}</div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <div className="text-zinc-500">{t('drive.simCollectResultSteps')}</div>
                  <div className="font-mono text-zinc-200">{job.result.steps}</div>
                </div>
                <div>
                  <div className="text-zinc-500">{t('drive.simCollectMeanCte')}</div>
                  <div className="font-mono text-zinc-200">{job.result.mean_cte.toFixed(4)}</div>
                </div>
                <div>
                  <div className="text-zinc-500">{t('drive.simCollectMaxCte')}</div>
                  <div className="font-mono text-zinc-200">{job.result.max_cte.toFixed(4)}</div>
                </div>
                <div>
                  <div className="text-zinc-500">{t('drive.simCollectCrashed')}</div>
                  <div className={job.result.crashed ? 'font-mono text-red-400' : 'font-mono text-zinc-200'}>
                    {job.result.crashed ? t('drive.simCollectCrashedYes') : t('drive.simCollectCrashedNo')}
                  </div>
                </div>
              </div>
              <div className="text-xs text-zinc-500">
                {t('drive.simCollectOutDir')}:{' '}
                <span className="font-mono text-zinc-400 break-all">{job.result.result_out}</span>
              </div>
            </div>
          )}

          {/* 手动停止 */}
          {job?.status === 'stopped' && (
            <div className="text-amber-400 text-sm">{t('drive.simCollectStopped')}</div>
          )}

          {/* 出错：错误信息 + 可展开的最后若干行日志 */}
          {job?.status === 'error' && (
            <div className="space-y-2">
              <div className="text-red-400 text-sm">{t('drive.simCollectError', { error: job.error ?? '' })}</div>
              {job.logs.length > 0 && (
                <details className="text-xs">
                  <summary className="cursor-pointer text-zinc-400 hover:text-zinc-200 transition-colors">
                    {t('drive.simCollectLogs')}
                  </summary>
                  <div className="mt-1 max-h-48 overflow-y-auto space-y-0.5 font-mono text-zinc-400 bg-zinc-950 rounded p-3">
                    {job.logs.map((line, i) => (
                      <div key={i} className="break-all">{line}</div>
                    ))}
                  </div>
                </details>
              )}
            </div>
          )}

          {/* 终态关闭复位：收起详情回到纯表单 */}
          {terminal && (
            <button
              type="button"
              onClick={reset}
              className="flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-200 transition-colors"
            >
              <X className="w-3.5 h-3.5" />
              {t('common.close')}
            </button>
          )}
        </div>
      )}
    </div>
  );
};
