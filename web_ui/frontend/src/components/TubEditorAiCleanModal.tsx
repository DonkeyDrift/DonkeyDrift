import React, { useMemo } from 'react';
import { Button } from './ui/Button';
import { type AiCleanSegment } from '../services/api';
import { useTranslation } from '@/i18n';
import { AlertCircle, Sparkles, Trash2 } from 'lucide-react';

/**
 * TE「AI 一键筛选」确认层（issue #402）：
 * 展示当前 tub/录制会话识别出的「碰撞后倒车」待删片段清单与总量统计，
 * 用户确认后由父组件（TubEditor）复用现有框选删除机制执行软删除并纳入撤销栈。
 */
interface TubEditorAiCleanModalProps {
  segments: AiCleanSegment[];
  /** 是否正在删除（禁用按钮并显示进度文案） */
  busy: boolean;
  /** 删除过程中出现的错误（若有） */
  error?: string | null;
  onClose: () => void;
  onConfirm: () => void;
}

const reasonKey = (code: string) =>
  code === 'plunge_reverse' ? 'aiClean.reasonPlungeReverse' : 'aiClean.reasonStopThenReverse';

export const TubEditorAiCleanModal: React.FC<TubEditorAiCleanModalProps> = ({
  segments,
  busy,
  error,
  onClose,
  onConfirm,
}) => {
  const { t } = useTranslation();

  const totals = useMemo(() => {
    const frames = segments.reduce((sum, seg) => sum + (seg.frame_count ?? 0), 0);
    return { segments: segments.length, frames };
  }, [segments]);

  return (
    <div className="fixed inset-0 bg-black/60 z-[70] flex items-center justify-center p-4">
      <div className="bg-zinc-900 border border-zinc-700 rounded-xl max-w-2xl w-full p-5 shadow-2xl max-h-[85vh] flex flex-col">
        <div className="flex items-start gap-3">
          <div className="p-2 rounded-full bg-cyan-500/15 shrink-0">
            <Sparkles className="w-5 h-5 text-cyan-400" />
          </div>
          <div className="min-w-0">
            <h3 className="text-base font-semibold">{t('tubEditor.aiFilterTitle')}</h3>
            <p className="text-xs text-zinc-400 mt-1">{t('tubEditor.aiFilterHint')}</p>
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 text-xs text-red-400 mt-3">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span className="break-all">{error}</span>
          </div>
        )}

        <div className="mt-4 min-h-0 flex-1 flex flex-col">
          <div className="flex-1 overflow-y-auto rounded-lg border border-zinc-800 divide-y divide-zinc-800">
            {segments.map((seg) => (
              <div
                key={`${seg.start_index}-${seg.end_index}`}
                className="px-3 py-2.5 text-xs text-zinc-400"
              >
                <div>
                  <span className="font-mono text-zinc-300">
                    {t('tubEditor.aiFilterSegmentRange', {
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
              </div>
            ))}
          </div>
          <div className="flex items-center justify-between gap-2 mt-4">
            <span className="text-xs text-zinc-400">
              {t('tubEditor.aiFilterSummary', {
                segments: totals.segments,
                frames: totals.frames,
              })}
            </span>
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" disabled={busy} onClick={onClose}>
                {t('tubEditor.aiFilterCancel')}
              </Button>
              <Button
                variant="danger"
                size="sm"
                disabled={busy || totals.segments === 0}
                onClick={onConfirm}
              >
                <Trash2 className="w-4 h-4" />
                {busy ? t('tubEditor.aiFilterDeleting') : t('tubEditor.aiFilterConfirm')}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
