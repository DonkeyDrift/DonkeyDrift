import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Button } from './ui/Button';
import {
  executeAiClean,
  getApiErrorMessage,
  listAiCleanCandidates,
  scanAiClean,
  type AiCleanCandidate,
  type AiCleanSegment,
  type AiCleanTubScan,
} from '../services/api';
import { useTranslation } from '@/i18n';
import { AlertCircle, Sparkles, Trash2 } from 'lucide-react';

/**
 * AI 清理「碰撞后倒车」弹窗（issue #373）：
 * 勾选 tub 范围 → 扫描 → 展示待删片段清单（每 tub 几段、共多少帧）
 * → 用户确认 → 批量软删除 → 结果反馈。
 */
interface AiCleanModalProps {
  tubPath: string;
  onClose: () => void;
  /** 删除执行成功后回调，父组件负责刷新 tub 数据 */
  onExecuted: () => void;
}

type Step = 'scope' | 'result' | 'done';

const reasonKey = (code: string) =>
  code === 'plunge_reverse' ? 'aiClean.reasonPlungeReverse' : 'aiClean.reasonStopThenReverse';

export const AiCleanModal: React.FC<AiCleanModalProps> = ({ tubPath, onClose, onExecuted }) => {
  const { t } = useTranslation();
  const [step, setStep] = useState<Step>('scope');
  const [candidates, setCandidates] = useState<AiCleanCandidate[]>([]);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [scanResults, setScanResults] = useState<AiCleanTubScan[]>([]);
  const [included, setIncluded] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deletedTotal, setDeletedTotal] = useState(0);

  // 打开时列出当前 tub 与同目录兄弟 tub，默认只勾当前 tub
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await listAiCleanCandidates(tubPath);
        if (cancelled) return;
        setCandidates(data.tubs || []);
        const initial: Record<string, boolean> = {};
        for (const tub of data.tubs || []) {
          initial[tub.path] = tub.is_current;
        }
        setChecked(initial);
      } catch (err) {
        if (!cancelled) {
          setError(getApiErrorMessage(err, t('aiClean.scanFailed')));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tubPath, t]);

  const handleScan = useCallback(async () => {
    const paths = candidates.filter((c) => checked[c.path]).map((c) => c.path);
    if (!paths.length) return;
    setBusy(true);
    setError(null);
    try {
      const data = await scanAiClean(paths);
      setScanResults(data.tubs || []);
      const include: Record<string, boolean> = {};
      for (const tub of data.tubs || []) {
        include[tub.tub_path] = !tub.error && (tub.segment_count ?? 0) > 0;
      }
      setIncluded(include);
      setStep('result');
    } catch (err) {
      setError(getApiErrorMessage(err, t('aiClean.scanFailed')));
    } finally {
      setBusy(false);
    }
  }, [candidates, checked, t]);

  const totals = useMemo(() => {
    let segments = 0;
    let frames = 0;
    for (const tub of scanResults) {
      if (!included[tub.tub_path]) continue;
      segments += tub.segment_count ?? 0;
      frames += tub.frame_count ?? 0;
    }
    return { segments, frames };
  }, [scanResults, included]);

  const handleExecute = useCallback(async () => {
    const deletions = scanResults
      .filter((tub) => included[tub.tub_path] && (tub.segment_count ?? 0) > 0)
      .map((tub) => ({
        tub_path: tub.tub_path,
        indexes: (tub.segments ?? []).flatMap((seg: AiCleanSegment) => seg.indexes),
      }));
    if (!deletions.length) return;
    setBusy(true);
    setError(null);
    try {
      const data = await executeAiClean(deletions);
      setDeletedTotal(data.total_deleted ?? 0);
      setStep('done');
      onExecuted();
    } catch (err) {
      setError(getApiErrorMessage(err, t('aiClean.deleteFailed')));
    } finally {
      setBusy(false);
    }
  }, [scanResults, included, onExecuted, t]);

  return (
    <div className="fixed inset-0 bg-black/60 z-[70] flex items-center justify-center p-4">
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl max-w-2xl w-full p-5 shadow-2xl max-h-[85vh] flex flex-col">
        <div className="flex items-start gap-3">
          <div className="p-2 rounded-full bg-cyan-500/15 shrink-0">
            <Sparkles className="w-5 h-5 text-cyan-400" />
          </div>
          <div className="min-w-0">
            <h3 className="text-base font-semibold">{t('aiClean.title')}</h3>
            <p className="text-xs text-zinc-400 mt-1">{t('aiClean.hint')}</p>
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 text-xs text-red-400 mt-3">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span className="break-all">{error}</span>
          </div>
        )}

        {/* 第 1 步：勾选扫描范围 */}
        {step === 'scope' && (
          <div className="mt-4 min-h-0 flex-1 flex flex-col">
            <div className="text-xs text-zinc-400 mb-2">{t('aiClean.scopeLabel')}</div>
            <div className="flex-1 overflow-y-auto rounded-lg border border-zinc-800 divide-y divide-zinc-800">
              {candidates.map((tub) => (
                <label
                  key={tub.path}
                  className="flex items-center gap-2 px-3 py-2.5 text-sm cursor-pointer hover:bg-zinc-800/60"
                >
                  <input
                    type="checkbox"
                    className="accent-cyan-500"
                    checked={!!checked[tub.path]}
                    onChange={(e) =>
                      setChecked((prev) => ({ ...prev, [tub.path]: e.target.checked }))
                    }
                  />
                  <span className="font-medium truncate">{tub.name}</span>
                  {tub.is_current && (
                    <span className="rounded-full bg-cyan-500/20 px-2 py-0.5 text-[10px] text-cyan-400">
                      {t('aiClean.currentBadge')}
                    </span>
                  )}
                  <span className="ml-auto text-xs text-zinc-500 truncate">{tub.path}</span>
                </label>
              ))}
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <Button variant="secondary" size="sm" disabled={busy} onClick={onClose}>
                {t('aiClean.cancel')}
              </Button>
              <Button
                size="sm"
                disabled={busy || !candidates.some((c) => checked[c.path])}
                onClick={() => void handleScan()}
              >
                <Sparkles className="w-4 h-4" />
                {busy ? t('aiClean.scanning') : t('aiClean.scan')}
              </Button>
            </div>
          </div>
        )}

        {/* 第 2 步：待删片段清单，用户勾选确认 */}
        {step === 'result' && (
          <div className="mt-4 min-h-0 flex-1 flex flex-col">
            {totals.segments === 0 && !scanResults.some((tub) => tub.error) ? (
              <div className="flex-1 flex items-center justify-center text-sm text-zinc-400 py-8">
                {t('aiClean.noSegments')}
              </div>
            ) : (
              <div className="flex-1 overflow-y-auto rounded-lg border border-zinc-800 divide-y divide-zinc-800">
                {scanResults.map((tub) => (
                  <div key={tub.tub_path} className="px-3 py-2.5">
                    {tub.error ? (
                      <div className="flex items-center gap-2 text-xs text-red-400">
                        <AlertCircle className="w-4 h-4 shrink-0" />
                        <span className="break-all">{tub.tub_path}: {tub.error}</span>
                      </div>
                    ) : (
                      <>
                        <label className="flex items-center gap-2 text-sm cursor-pointer">
                          <input
                            type="checkbox"
                            className="accent-cyan-500"
                            disabled={(tub.segment_count ?? 0) === 0}
                            checked={!!included[tub.tub_path]}
                            onChange={(e) =>
                              setIncluded((prev) => ({ ...prev, [tub.tub_path]: e.target.checked }))
                            }
                          />
                          <span className="font-medium truncate">{tub.tub_path}</span>
                          <span className="ml-auto shrink-0 text-xs text-zinc-400">
                            {t('aiClean.tubSummary', {
                              segments: tub.segment_count ?? 0,
                              frames: tub.frame_count ?? 0,
                            })}
                          </span>
                        </label>
                        {(tub.segments ?? []).map((seg) => (
                          <div
                            key={`${seg.start_index}-${seg.end_index}`}
                            className="ml-6 mt-1 text-xs text-zinc-400"
                          >
                            <span className="font-mono text-zinc-300">
                              {t('aiClean.segmentRange', {
                                start: seg.start_index,
                                end: seg.end_index,
                                frames: seg.frame_count,
                              })}
                            </span>
                            <span className="ml-2 text-amber-400/90">
                              {t(reasonKey(seg.reason_code))}
                            </span>
                            {typeof seg.detail?.collision_index === 'number' && (
                              <span className="ml-2 text-zinc-500">
                                {t('aiClean.segmentDetail', {
                                  collision: seg.detail.collision_index,
                                  frames: seg.detail.reverse_frames ?? 0,
                                })}
                              </span>
                            )}
                          </div>
                        ))}
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}
            <div className="flex items-center justify-between gap-2 mt-4">
              <span className="text-xs text-zinc-400">
                {t('aiClean.summary', { segments: totals.segments, frames: totals.frames })}
              </span>
              <div className="flex gap-2">
                <Button variant="secondary" size="sm" disabled={busy} onClick={onClose}>
                  {t('aiClean.cancel')}
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  disabled={busy || totals.segments === 0}
                  onClick={() => void handleExecute()}
                >
                  <Trash2 className="w-4 h-4" />
                  {busy ? t('aiClean.deleting') : t('aiClean.confirmDelete')}
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* 第 3 步：结果反馈 */}
        {step === 'done' && (
          <div className="mt-4">
            <p className="text-sm text-emerald-400">{t('aiClean.doneTitle')}</p>
            <p className="text-sm text-zinc-400 mt-1">
              {t('aiClean.doneBody', { count: deletedTotal })}
            </p>
            <div className="flex justify-end mt-4">
              <Button size="sm" onClick={onClose}>
                {t('aiClean.close')}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
