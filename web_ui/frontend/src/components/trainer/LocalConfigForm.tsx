import React from 'react';
import { useStore, type TrainerLocalConfig } from '../../store/useStore';

interface LocalConfigFormProps {
  config: TrainerLocalConfig;
  onConfigChange: (patch: Partial<TrainerLocalConfig>) => void;
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
}) => {
  const { configPath } = useStore();

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-4">
      <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">Training Config</h3>

      <div className="space-y-1">
        <label className="text-xs text-zinc-500">Tub Path</label>
        <div className="flex gap-2">
          <input
            type="text"
            value={config.tub}
            onChange={(e) => onConfigChange({ tub: e.target.value })}
            className="flex-1 bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
          />
        </div>
        <div className="text-xs text-zinc-600">Working dir: {configPath}</div>
      </div>

      <div className="space-y-1">
        <label className="text-xs text-zinc-500">Model Name</label>
        <input
          type="text"
          value={config.model}
          onChange={(e) => onConfigChange({ model: e.target.value })}
          placeholder="e.g. my_model"
          className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
        />
      </div>

      <div className="space-y-1">
        <label className="text-xs text-zinc-500">Model Type</label>
        <select
          value={config.modelType}
          onChange={(e) => onConfigChange({ modelType: e.target.value })}
          className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
        >
          {MODEL_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      <div className="space-y-1">
        <label className="text-xs text-zinc-500">Transfer Model (optional)</label>
        <input
          type="text"
          value={config.transfer}
          onChange={(e) => onConfigChange({ transfer: e.target.value })}
          placeholder="path to base model"
          className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
        />
      </div>

      {/* Advanced Options */}
      <div className="pt-2 border-t border-zinc-800">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={config.advancedEnabled}
            onChange={(e) => onConfigChange({ advancedEnabled: e.target.checked })}
            className="w-4 h-4 rounded border-zinc-700 bg-zinc-950 text-cyan-600 focus:ring-cyan-600"
          />
          <span className="text-sm font-medium text-zinc-300">Advanced Options</span>
        </label>

        {config.advancedEnabled && (
          <div className="mt-3 grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs text-zinc-500">Batch Size</label>
              <input
                type="number"
                value={config.batchSize}
                onChange={(e) => onConfigChange({ batchSize: parseInt(e.target.value, 10) })}
                className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-zinc-500">Train/Test Split</label>
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
              <label className="text-xs text-zinc-500">Max Epochs</label>
              <input
                type="number"
                value={config.maxEpochs}
                onChange={(e) => onConfigChange({ maxEpochs: parseInt(e.target.value, 10) })}
                className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-zinc-500">Learning Rate</label>
              <input
                type="number"
                step="0.0001"
                value={config.learningRate}
                onChange={(e) => onConfigChange({ learningRate: parseFloat(e.target.value) })}
                className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-zinc-500">Early Stop Patience</label>
              <input
                type="number"
                value={config.earlyStopPatience}
                onChange={(e) => onConfigChange({ earlyStopPatience: parseInt(e.target.value, 10) })}
                className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-zinc-500">Prune Val Loss Limit</label>
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
              <span className="text-xs text-zinc-400">Show Plot</span>
            </label>

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={config.useEarlyStop}
                onChange={(e) => onConfigChange({ useEarlyStop: e.target.checked })}
                className="w-4 h-4 rounded border-zinc-700 bg-zinc-950 text-cyan-600 focus:ring-cyan-600"
              />
              <span className="text-xs text-zinc-400">Use Early Stop</span>
            </label>

            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={config.createTfLite}
                onChange={(e) => onConfigChange({ createTfLite: e.target.checked })}
                className="w-4 h-4 rounded border-zinc-700 bg-zinc-950 text-cyan-600 focus:ring-cyan-600"
              />
              <span className="text-xs text-zinc-400">Create TF Lite</span>
            </label>
          </div>
        )}
      </div>
    </div>
  );
};
