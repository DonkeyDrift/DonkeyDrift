import React, { useEffect, useState } from 'react';
import { useTranslation } from '@/i18n';
import {
  listFamilyTubSessions,
  type FamilyTubSession,
  type TrainerTub,
} from '../../services/api';

// 本地训练的录制会话筛选状态：状态由 TrainerPage 持有，本组件受控。
// selected 元素为 (tub_path, session_id) 复合键（与录制视频库 sessionKey 约定
// 一致）：_session_id 跨 tub 会撞名（如 data 与 tub_1 都有 26-10-23_0），
// 裸 session_id 无法区分
export interface SessionFilterState {
  enabled: boolean;
  selected: string[];
  // 勾选覆盖全部已加载会话时等价于「不过滤」（TrainerPage 省略 session_filter）
  isFullSelection: boolean;
}

interface SessionFilterPickerProps {
  tub: string;
  tubCandidates: TrainerTub[];
  enabled: boolean;
  selected: string[];
  onChange: (next: SessionFilterState) => void;
  // 家族会话列表上报（含本次拉取的 fetchPath）：TrainerPage 用它渲染
  // 「训练数据范围」摘要，避免同一份数据再拉一次
  onSessionsChange?: (fetchPath: string, sessions: FamilyTubSession[]) => void;
}

const sessionKeyOf = (s: Pick<FamilyTubSession, 'tub_path' | 'session_id'>) =>
  `${s.tub_path}::${s.session_id}`;

// 按录制会话筛选训练数据：默认不启用（= 训练全部记录，行为与现状一致）。
// 数据源为「当前 tub 所属家族」的全部会话（跨 tub 聚合），每行标注来源 tub。
export const SessionFilterPicker: React.FC<SessionFilterPickerProps> = ({
  tub,
  tubCandidates,
  enabled,
  selected,
  onChange,
  onSessionsChange,
}) => {
  const { t } = useTranslation();
  const [sessions, setSessions] = useState<FamilyTubSession[]>([]);
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
      onSessionsChange?.('', []);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadFailed(false);
    listFamilyTubSessions(fetchPath)
      .then((data) => {
        if (cancelled) return;
        const items = data.sessions || [];
        setSessions(items);
        onSessionsChange?.(fetchPath, items);
      })
      .catch(() => {
        if (cancelled) return;
        setSessions([]);
        setLoadFailed(true);
        onSessionsChange?.(fetchPath, []);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fetchPath, onSessionsChange]);

  // 会话列表刷新后剔除已不存在的勾选（如 tub 内会话被删），避免残留旧复合键
  const effectiveSelected = sessions.length
    ? selected.filter((key) => sessions.some((s) => sessionKeyOf(s) === key))
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

  const allKeys = sessions.map(sessionKeyOf);

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
              onClick={() => emit({ selected: allKeys })}
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
            sessions.map((s) => {
              const key = sessionKeyOf(s);
              return (
                <label
                  key={key}
                  className="flex items-center gap-2 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    aria-label={`${s.tub_name}/${s.session_id}`}
                    checked={effectiveSelected.includes(key)}
                    onChange={(e) => {
                      const next = e.target.checked
                        ? [...effectiveSelected, key]
                        : effectiveSelected.filter((k) => k !== key);
                      emit({ selected: next });
                    }}
                    className="w-4 h-4 rounded border-zinc-700 bg-zinc-950 text-cyan-600 focus:ring-cyan-600"
                  />
                  <span className="text-xs text-zinc-400 font-mono">
                    {s.tub_name}
                  </span>
                  <span className="text-xs text-zinc-300 font-mono">
                    /{s.session_id}
                  </span>
                  <span className="text-xs text-zinc-600">
                    {t('trainer.sessionFilterFrames', { count: s.record_count })}
                  </span>
                </label>
              );
            })}

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
