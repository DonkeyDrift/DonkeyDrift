import React, { useEffect, useState, useCallback, useRef } from 'react';
import { listModels, deleteModel, downloadModelUrl, loadModelToCar, importModel, API_URL, getApiErrorMessage } from '../../services/api';
import { useStore } from '../../store/useStore';
import { FileText, Copy, TrendingDown, Download, Send, Trash2, Boxes, X, Upload } from 'lucide-react';
import { SectionCardTitle } from '../ui/SectionCardTitle';
import { useTranslation } from '@/i18n';

interface ModelItem {
  name: string;
  size: number;
  modified: string;
  path: string;
  previewPath?: string;
  finalLoss?: number;
  bestLoss?: number;
}

function formatSize(bytes: number): string {
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = bytes;
  let unitIdx = 0;
  while (size >= 1024 && unitIdx < units.length - 1) {
    size /= 1024;
    unitIdx++;
  }
  return `${size.toFixed(1)} ${units[unitIdx]}`;
}

export const ModelsList: React.FC = () => {
  const { t } = useTranslation();
  const { configPath, trainingJob } = useStore();
  const [models, setModels] = useState<ModelItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [activePreview, setActivePreview] = useState<{
    path: string;
    name: string;
  } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<ModelItem | null>(null);
  const [importing, setImporting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listModels(configPath);
      setModels(data.models || []);
    } catch {
      setModels([]);
    } finally {
      setLoading(false);
    }
  }, [configPath]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Auto-refresh when a training job completes
  useEffect(() => {
    if (trainingJob?.status === 'completed') {
      refresh();
    }
  }, [trainingJob?.status, refresh]);

  const openPreview = (model: ModelItem) => {
    if (model.previewPath) {
      setActivePreview({ path: model.previewPath, name: model.name });
      setPreviewLoading(true);
    }
  };

  const closePreview = () => {
    setActivePreview(null);
    setPreviewLoading(false);
  };

  useEffect(() => {
    if (!activePreview) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closePreview();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [activePreview]);

  const handleDelete = useCallback(async (model: ModelItem) => {
    setDeleting(model.path);
    try {
      await deleteModel(model.path);
      setConfirmDelete(null);
      await refresh();
    } finally {
      setDeleting(null);
    }
  }, [refresh]);

  const handleImportFile = useCallback(async (file: File) => {
    setImporting(true);
    try {
      await importModel(file, configPath);
      await refresh();
    } catch (error) {
      alert(t('trainer.importFailed', { message: getApiErrorMessage(error) }));
    } finally {
      setImporting(false);
    }
  }, [configPath, refresh, t]);

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-3 relative">
      <div className="flex items-center justify-between">
        <SectionCardTitle
          icon={<Boxes className="w-5 h-5" />}
          title={t('trainer.trainedModels')}
          subtitle={t('trainer.trainedModelsSubtitle')}
        />
        <div className="flex items-center gap-3">
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={importing}
            className="inline-flex items-center gap-1 text-xs text-cyan-500 hover:text-cyan-400 disabled:text-zinc-600 transition-colors"
            title={t('trainer.importModel')}
          >
            <Upload className="w-3.5 h-3.5" />
            {importing ? t('trainer.importing') : t('trainer.importModel')}
          </button>
          <button
            onClick={refresh}
            disabled={loading}
            className="text-xs text-cyan-500 hover:text-cyan-400 disabled:text-zinc-600 transition-colors"
          >
            {loading ? t('trainer.loading') : t('trainer.refresh')}
          </button>
        </div>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".tflite,.h5,.zip"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) {
            handleImportFile(file);
          }
          e.target.value = '';
        }}
      />

      {models.length === 0 && (
        <div className="text-sm text-zinc-600">{t('trainer.noModels')}</div>
      )}

      <div className="space-y-2 max-h-64 overflow-y-auto">
        {models.map((m) => (
          <div
            key={m.name}
            className="bg-zinc-950 rounded px-3 py-2 border border-zinc-800/50 cursor-default"
          >
            {/* Row 1: model name + loss badge */}
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <FileText className="w-4 h-4 text-zinc-500 shrink-0" />
                <span className="text-sm text-zinc-300 truncate" title={m.name}>{m.name}</span>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                {typeof m.finalLoss === 'number' && m.previewPath && (
                  <button
                    onClick={() => openPreview(m)}
                    aria-label={t('trainer.viewLossChart')}
                    title={t('trainer.viewLossChart')}
                    className="inline-flex items-center gap-1 text-xs font-medium text-emerald-400 bg-emerald-400/10 hover:bg-emerald-400/20 px-2 py-0.5 rounded mr-1 transition-colors"
                  >
                    <TrendingDown className="w-3 h-3" />
                    {m.finalLoss.toFixed(4)}
                  </button>
                )}
                {typeof m.finalLoss === 'number' && !m.previewPath && (
                  <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded mr-1">
                    <TrendingDown className="w-3 h-3" />
                    {m.finalLoss.toFixed(4)}
                  </span>
                )}
                <a
                  href={downloadModelUrl(m.path)}
                  onClick={(e) => e.stopPropagation()}
                  title={t('trainer.downloadModel')}
                  className="p-1 text-zinc-500 hover:text-cyan-400 transition-colors"
                  download
                >
                  <Download className="w-3.5 h-3.5" />
                </a>
                <button
                  onClick={async (e) => {
                    e.stopPropagation();
                    try {
                      await loadModelToCar(m.path, configPath);
                      alert(t('trainer.loadToCarSent'));
                    } catch (error) {
                      alert(t('trainer.loadFailed', { message: getApiErrorMessage(error) }));
                    }
                  }}
                  title={t('trainer.loadToCar')}
                  className="p-1 text-zinc-500 hover:text-emerald-400 transition-colors"
                >
                  <Send className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    navigator.clipboard.writeText(m.path);
                  }}
                  title={t('trainer.copyPath')}
                  className="p-1 text-zinc-500 hover:text-zinc-300 transition-colors"
                >
                  <Copy className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setConfirmDelete(m);
                  }}
                  title={t('trainer.deleteModel')}
                  className="p-1 text-red-400 hover:text-red-300 transition-colors"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {/* Row 2: metadata */}
            <div className="flex items-center justify-between mt-1">
              <span className="text-xs text-zinc-600">
                {formatSize(m.size)} · {new Date(m.modified).toLocaleString()}
                {typeof m.bestLoss === 'number' && typeof m.finalLoss === 'number' && m.bestLoss !== m.finalLoss && (
                  <span className="ml-2 text-zinc-500">
                    {t('trainer.bestLoss', { loss: m.bestLoss.toFixed(4) })}
                  </span>
                )}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Loss chart preview modal */}
      {activePreview && (
        <div
          className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
          onClick={closePreview}
          data-testid="loss-chart-overlay"
        >
          <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-4 w-[360px] shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-zinc-400 truncate" title={activePreview.name}>
                {activePreview.name}
              </span>
              <button
                onClick={closePreview}
                aria-label={t('trainer.close')}
                title={t('trainer.close')}
                className="p-1 text-zinc-500 hover:text-zinc-200 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            {previewLoading && (
              <div className="w-full h-32 flex items-center justify-center text-zinc-500 text-sm">
                {t('trainer.loading')}
              </div>
            )}
            <img
              src={`${API_URL}/trainer/models/preview?path=${encodeURIComponent(activePreview.path)}`}
              alt={t('trainer.lossChartAlt')}
              className={`w-full h-auto rounded ${previewLoading ? 'hidden' : ''}`}
              style={{ maxHeight: 220 }}
              draggable={false}
              onLoad={() => setPreviewLoading(false)}
              onError={() => setPreviewLoading(false)}
            />
          </div>
        </div>
      )}

      {/* Delete confirmation modal */}
      {confirmDelete && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setConfirmDelete(null)}>
          <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-5 w-80 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h4 className="text-sm font-semibold text-zinc-200 mb-2">{t('trainer.deleteModel')}</h4>
            <p className="text-xs text-zinc-400 mb-4">
              {t('trainer.deleteConfirm', { name: confirmDelete.name })}
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setConfirmDelete(null)}
                disabled={deleting === confirmDelete.path}
                className="px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 transition-colors disabled:text-zinc-600"
              >
                {t('trainer.cancel')}
              </button>
              <button
                onClick={() => handleDelete(confirmDelete)}
                disabled={deleting === confirmDelete.path}
                className="px-3 py-1.5 text-xs bg-red-500/20 text-red-400 hover:bg-red-500/30 rounded transition-colors disabled:text-zinc-600 disabled:bg-zinc-800"
              >
                {deleting === confirmDelete.path ? t('trainer.deleting') : t('trainer.delete')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
