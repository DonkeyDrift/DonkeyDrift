import React, { useEffect, useState } from 'react';
import { useTranslation } from '@/i18n';
import {
  listTubSessions,
  type TrainerTub,
  type TubSession,
} from '../../services/api';

// 本地训练的录制会话筛选状态：状态由 TrainerPage 持有，本组件受控。
export interface SessionFilterState {
  enabled: boolean;
  selected: string[];
  // 勾选覆盖全部已加载会话时等价于「不过滤」（TrainerPage 省略 session_ids）
  isFullSelection: boolean;
}

interface SessionFilterPickerProps {
  tub: string;
  tubCandidates: TrainerTub[];
  enabled: boolean;
  selected: string[];
  onChange: (next: SessionFilterState) => void;
}

// 按录制会话筛选训练数据：默认不启用（= 训练全部记录，行为与现状一致）。
export const SessionFilterPicker: React.FC<SessionFilterPickerProps> = ({
  tub,
  tubCandidates,
  enabled,
  selected,
  onChange,
}) => {
  const { t } = useTranslation();
  const [sessions, setSessions] = useState<TubSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);

  // tub 命中 /trainer/tubs 候选时用候选的 absolute_path 拉取；手输路径原样透传
  const candidate = tubCandidates.find(
    (c) => c.relative_path === tub || c.absolute_path === tub
  );
  const fetchPath = candidate ? candidate.absolute_path : tub;

  useEffect(() => {
    if (!fetchPath) {
      setSessions([]);
      setLoadFailed(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadFailed(false);
    listTubSessions(fetchPath)
      .then((data) => {
        if (cancelled) return;
        setSessions(data.sessions || []);
      })
      .catch(() => {
        if (cancelled) return;
        setSessions([]);
        setLoadFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fetchPath]);

  // 会话列表刷新后剔除已不存在的勾选（如 tub 内会话被删），避免残留旧 id
  const effectiveSelected = sessions.length
    ? selected.filter((id) => sessions.some((s) => s.session_id === id))
    : selected;

  const emit = (next: Partial<SessionFilterState>) => {
    const mergedEnabled = next.enabled ?? enabled;
    const mergedSelected = next.selected ?? effectiveSelected;
    onChange({
      enabled: mergedEnabled,
      selected: mergedSelected,
      isFullSelection:
        sessions.length > 0 && mergedSelected.length === sessions.length,
    });
  };

  const effectiveSelectedKey = effectiveSelected.join('');
  useEffect(() => {
    if (effectiveSelected.length !== selected.length) {
      emit({ selected: effectiveSelected });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveSelectedKey]);

  const allIds = sessions.map((s) => s.session_id);

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-3">
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => emit({ enabled: e.target.checked })}
          className="w-4 h-4 rounded border-zinc-700 bg-zinc-950 text-cyan-600 focus:ring-cyan-600"
          data-testid="session-filter-enable"
        />
        <span className="text-sm text-zinc-300">{t('trainer.sessionFilter')}</span>
      </label>
      <div className="text-xs text-zinc-600">{t('trainer.sessionFilterHint')}</div>

      {enabled && (
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => emit({ selected: allIds })}
              className="text-xs text-cyan-400 hover:text-cyan-300 transition-colors"
            >
              {t('trainer.sessionFilterSelectAll')}
            </button>
            <button
              type="button"
              onClick={() => emit({ selected: [] })}
              className="text-xs text-cyan-400 hover:text-cyan-300 transition-colors"
            >
              {t('trainer.sessionFilterClear')}
            </button>
            <span className="text-xs text-zinc-600">
              {t('trainer.sessionFilterSelected', {
                selected: effectiveSelected.length,
                total: sessions.length,
              })}
            </span>
          </div>

          {loading && (
            <div className="text-xs text-zinc-600">{t('trainer.loading')}</div>
          )}
          {!loading && loadFailed && (
            <div className="text-xs text-amber-500">
              {t('trainer.sessionFilterLoadFailed')}
            </div>
          )}
          {!loading && !loadFailed && sessions.length === 0 && (
            <div className="text-xs text-zinc-600">
              {t('trainer.sessionFilterEmpty')}
            </div>
          )}
          {!loading &&
            !loadFailed &&
            sessions.map((s) => (
              <label
                key={s.session_id}
                className="flex items-center gap-2 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={effectiveSelected.includes(s.session_id)}
                  onChange={(e) => {
                    const next = e.target.checked
                      ? [...effectiveSelected, s.session_id]
                      : effectiveSelected.filter((id) => id !== s.session_id);
                    emit({ selected: next });
                  }}
                  className="w-4 h-4 rounded border-zinc-700 bg-zinc-950 text-cyan-600 focus:ring-cyan-600"
                />
                <span className="text-xs text-zinc-300 font-mono">
                  {s.session_id}
                </span>
                <span className="text-xs text-zinc-600">
                  {t('trainer.sessionFilterFrames', { count: s.record_count })}
                </span>
              </label>
            ))}

          {!loading && !loadFailed && effectiveSelected.length === 0 && (
            <div className="text-xs text-amber-500">
              {t('trainer.sessionFilterNoneSelected')}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
