import React from 'react';
import { useTranslation } from '@/i18n';
import type { TrainerTub } from '../../services/api';

interface TubSelectorProps {
  tub: string;
  onTubChange: (v: string) => void;
  tubCandidates: TrainerTub[];
  currentTubPath: string;
}

// Reusable tub picker: dropdown of candidate tubs with a manual-input fallback
// when the current value is not one of the candidates.
export const TubSelector: React.FC<TubSelectorProps> = ({
  tub,
  onTubChange,
  tubCandidates,
  currentTubPath,
}) => {
  const { t } = useTranslation();

  const candidatePaths = tubCandidates.map((c) => c.relative_path);
  const selectedCandidate = candidatePaths.includes(tub) ? tub : '';

  return (
    <div className="space-y-1">
      <label className="text-xs text-zinc-500">{t('trainer.tubPath')}</label>
      <div className="flex gap-2">
        <select
          value={selectedCandidate}
          onChange={(e) => {
            if (e.target.value) {
              onTubChange(e.target.value);
            }
          }}
          className="flex-1 bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
          aria-label={t('trainer.tubPath')}
        >
          <option value="">{t('trainer.tubPathManual')}</option>
          {tubCandidates.map((c) => (
            <option key={c.absolute_path} value={c.relative_path}>
              {c.absolute_path === currentTubPath
                ? `${c.relative_path} (${t('trainer.tubLoaded')})`
                : c.relative_path}
            </option>
          ))}
        </select>
        {selectedCandidate === '' && (
          <input
            type="text"
            value={tub}
            onChange={(e) => onTubChange(e.target.value)}
            className="flex-1 bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
          />
        )}
      </div>
    </div>
  );
};
