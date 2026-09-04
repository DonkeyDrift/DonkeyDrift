import React from 'react';
import { ChevronDown, ChevronUp, SlidersHorizontal } from 'lucide-react';
import { SectionCardTitle } from '../ui/SectionCardTitle';
import { TubSelector } from './TubSelector';
import { useStore, type TrainerLocalConfig } from '../../store/useStore';
import { useTranslation } from '@/i18n';
import type { TrainerTub } from '../../services/api';

interface LocalConfigFormProps {
  config: TrainerLocalConfig;
  onConfigChange: (patch: Partial<TrainerLocalConfig>) => void;
  tubCandidates: TrainerTub[];
  currentTubPath: string;
}

const MODEL_TYPES = [
  'linear',
  'categorical',
  'rnn',
  'imu',
  'behavior',
  'localizer',
  '3d',
];

export const LocalConfigForm: React.FC<LocalConfigFormProps> = ({
  config,
  onConfigChange,
  tubCandidates,
  currentTubPath,
}) => {
  const { t } = useTranslation();
  const { configPath } = useStore();

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-4">
      <SectionCardTitle
        icon={<SlidersHorizontal className="w-5 h-5" />}
        title={t('trainer.trainingConfig')}
        subtitle={t('trainer.trainingConfigSubtitle')}
      />

      <div className="space-y-1">
        <TubSelector
          tub={config.tub}
          onTubChange={(v) => onConfigChange({ tub: v })}
          tubCandidates={tubCandidates}
          currentTubPath={currentTubPath}
        />
        <div className="text-xs text-zinc-600">{t('trainer.workingDir', { path: configPath })}</div>
      </div>

      <div className="space-y-1">
        <label className="text-xs text-zinc-500">{t('trainer.modelName')}</label>
        <input
          type="text"
          value={config.model}
          onChange={(e) => onConfigChange({ model: e.target.value })}
          placeholder={t('trainer.modelNamePlaceholder')}
          className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
        />
      </div>

      <div className="space-y-1">
        <label className="text-xs text-zinc-500">{t('trainer.modelType')}</label>
        <select
          value={config.modelType}
          onChange={(e) => onConfigChange({ modelType: e.target.value })}
          className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
        >
          {MODEL_TYPES.map((type) => (
            <option key={type} value={type}>{type}</option>
          ))}
        </select>
      </div>

      <div className="space-y-1">
        <label className="text-xs text-zinc-500">{t('trainer.transferModel')}</label>
        <input
          type="text"
          value={config.transfer}
          onChange={(e) => onConfigChange({ transfer: e.target.value })}
          placeholder={t('trainer.transferPlaceholder')}
          className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
        />
      </div>

      {/* Advanced: collapsible row (expanded = advanced overrides active, same semantics as the old checkbox) */}
      <div className="pt-2 border-t border-zinc-800">
        <button
          type="button"
          onClick={() => onConfigChange({ advancedEnabled: !config.advancedEnabled })}
          aria-expanded={config.advancedEnabled}
          className="w-full flex items-center justify-between text-sm text-zinc-400 hover:text-zinc-200 transition-colors"
        >
          <span className="font-medium">{t('trainer.advancedOptions')}</span>
          {config.advancedEnabled ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>

        {config.advancedEnabled && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs text-zinc-500">{t('trainer.batchSize')}</label>
              <input
                type="number"
                value={config.batchSize}
                onChange={(e) => onConfigChange({ batchSize: parseInt(e.target.value, 10) })}
                className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-zinc-500">{t('trainer.trainTestSplit')}</label>
              <input
                type="number"
                step="0.01"
                min="0"
                max="1"
                value={config.trainTestSplit}
                onChange={(e) => onConfigChange({ trainTestSplit: parseFloat(e.target.value) })}
                className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-zinc-500">{t('trainer.maxEpochs')}</label>
              <input
                type="number"
                value={config.maxEpochs}
                onChange={(e) => onConfigChange({ maxEpochs: parseInt(e.target.value, 10) })}
                className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-zinc-500">{t('trainer.learningRate')}</label>
              <input
                type="number"
                step="0.0001"
                value={config.learningRate}
                onChange={(e) => onConfigChange({ learningRate: parseFloat(e.target.value) })}
                className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-zinc-500">{t('trainer.earlyStopPatience')}</label>
              <input
                type="number"
                value={config.earlyStopPatience}
                onChange={(e) => onConfigChange({ earlyStopPatience: parseInt(e.target.value, 10) })}
                className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-zinc-500">{t('trainer.pruneValLossLimit')}</label>
              <input
                type="number"
                step="0.1"
                value={config.pruneValLossDegradationLimit}
                onChange={(e) => onConfigChange({ pruneValLossDegradationLimit: parseFloat(e.target.value) })}
                className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
              />
            </div>

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={config.showPlot}
                onChange={(e) => onConfigChange({ showPlot: e.target.checked })}
                className="w-4 h-4 rounded border-zinc-700 bg-zinc-950 text-cyan-600 focus:ring-cyan-600"
              />
              <span className="text-xs text-zinc-400">{t('trainer.showPlot')}</span>
            </label>

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={config.useEarlyStop}
                onChange={(e) => onConfigChange({ useEarlyStop: e.target.checked })}
                className="w-4 h-4 rounded border-zinc-700 bg-zinc-950 text-cyan-600 focus:ring-cyan-600"
              />
              <span className="text-xs text-zinc-400">{t('trainer.useEarlyStop')}</span>
            </label>

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={config.createTfLite}
                onChange={(e) => onConfigChange({ createTfLite: e.target.checked })}
                className="w-4 h-4 rounded border-zinc-700 bg-zinc-950 text-cyan-600 focus:ring-cyan-600"
              />
              <span className="text-xs text-zinc-400">{t('trainer.createTfLite')}</span>
            </label>
          </div>
        )}
      </div>
    </div>
  );
};
