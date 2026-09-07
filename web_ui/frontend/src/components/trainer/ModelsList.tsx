import React, { useEffect, useState, useCallback, useRef } from 'react';
import { listModels, deleteModel, downloadModelUrl, loadModelToCar, importModel, uploadModelLoss, API_URL, getApiErrorMessage } from '../../services/api';
import { useStore } from '../../store/useStore';
import { FileText, Copy, TrendingDown, Download, Send, Trash2, Boxes, X, Upload, ImagePlus } from 'lucide-react';
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
  return size.toFixed(1) + ' ' + units[unitIdx];
}

function previewUrl(path: string): string {
  return API_URL + '/trainer/models/preview?path=' + encodeURIComponent(path);
}

const fileInputClass =
  'mt-1 block w-full text-xs text-zinc-300 file:mr-2 file:rounded file:border-0 file:bg-cyan-500/20 file:px-2 file:py-1 file:text-xs file:text-cyan-300';

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
  const [showImport, setShowImport] = useState(false);
  const [importModelFile, setImportModelFile] = useState<File | null>(null);
  const [importLossImage, setImportLossImage] = useState<File | null>(null);
  const [importMetaJson, setImportMetaJson] = useState<File | null>(null);
  const [uploadTarget, setUploadTarget] = useState<ModelItem | null>(null);
  const [uploadLossImage, setUploadLossImage] = useState<File | null>(null);
  const [uploadMetaJson, setUploadMetaJson] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [hoverPreview, setHoverPreview] = useState<{
    path: string;
    name: string;
    x: number;
    y: number;
  } | null>(null);
  const hoverTimer = useRef<number | null>(null);
  const hoverPos = useRef({ x: 0, y: 0 });

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

  const clearHover = useCallback(() => {
    if (hoverTimer.current !== null) {
      window.clearTimeout(hoverTimer.current);
      hoverTimer.current = null;
    }
    setHoverPreview(null);
  }, []);

  // Cleanup the hover timer on unmount
  useEffect(() => clearHover, [clearHover]);

  const handleRowMouseEnter = (m: ModelItem) => (e: React.MouseEvent<HTMLDivElement>) => {
    if (!m.previewPath) return;
    hoverPos.current = { x: e.clientX + 16, y: e.clientY + 20 };
    if (hoverTimer.current !== null) {
      window.clearTimeout(hoverTimer.current);
    }
    hoverTimer.current = window.setTimeout(() => {
      setHoverPreview({
        path: m.previewPath as string,
        name: m.name,
        x: hoverPos.current.x,
        y: hoverPos.current.y,
      });
    }, 300);
  };

  const handleRowMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    hoverPos.current = { x: e.clientX + 16, y: e.clientY + 20 };
    setHoverPreview((prev) =>
      prev ? { ...prev, x: hoverPos.current.x, y: hoverPos.current.y } : prev,
    );
  };

  const handleRowMouseLeave = () => clearHover();

  const handleDelete = useCallback(
    async (model: ModelItem) => {
      setDeleting(model.path);
      try {
        await deleteModel(model.path);
        setConfirmDelete(null);
        await refresh();
      } finally {
        setDeleting(null);
      }
    },
    [refresh],
  );

  const handleImportSubmit = useCallback(async () => {
    if (!importModelFile) return;
    setImporting(true);
    try {
      await importModel(
        importModelFile,
        configPath,
        importLossImage ?? undefined,
        importMetaJson ?? undefined,
      );
      setShowImport(false);
      setImportModelFile(null);
      setImportLossImage(null);
      setImportMetaJson(null);
      await refresh();
    } catch (error) {
      alert(t('trainer.importFailed', { message: getApiErrorMessage(error) }));
    } finally {
      setImporting(false);
    }
  }, [importModelFile, importLossImage, importMetaJson, configPath, refresh, t]);

  const handleUploadLossSubmit = useCallback(async () => {
    if (!uploadTarget) return;
    setUploading(true);
    try {
      await uploadModelLoss(
        uploadTarget.name,
        configPath,
        uploadLossImage ?? undefined,
        uploadMetaJson ?? undefined,
      );
      setUploadTarget(null);
      setUploadLossImage(null);
      setUploadMetaJson(null);
      await refresh();
    } catch (error) {
      alert(t('trainer.uploadLossFailed', { message: getApiErrorMessage(error) }));
    } finally {
      setUploading(false);
    }
  }, [uploadTarget, uploadLossImage, uploadMetaJson, configPath, refresh, t]);

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
            onClick={() => setShowImport(true)}
            disabled={importing}
            className="inline-flex items-center gap-1 text-xs text-cyan-500 hover:text-cyan-400 disabled:text-zinc-600 transition-colors"
            title={t('trainer.importModel')}
          >
            <Upload className="w-3.5 h-3.5" />
            {t('trainer.importModel')}
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

      {models.length === 0 && (
        <div className="text-sm text-zinc-600">{t('trainer.noModels')}</div>
      )}

      <div className="space-y-2 max-h-64 overflow-y-auto">
        {models.map((m) => (
          <div
            key={m.name}
            className="bg-zinc-950 rounded px-3 py-2 border border-zinc-800/50 cursor-default"
            onMouseEnter={handleRowMouseEnter(m)}
            onMouseMove={handleRowMouseMove}
            onMouseLeave={handleRowMouseLeave}
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
                {!m.previewPath && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setUploadTarget(m);
                    }}
                    title={t('trainer.uploadLoss')}
                    className="inline-flex items-center gap-1 text-xs text-zinc-500 hover:text-cyan-400 px-2 py-0.5 rounded mr-1 transition-colors"
                  >
                    <ImagePlus className="w-3 h-3" />
                    {t('trainer.uploadLoss')}
                  </button>
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
              {!m.previewPath && typeof m.finalLoss !== 'number' && (
                <span className="text-xs text-zinc-600">{t('trainer.noLossData')}</span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Hover loss chart tooltip */}
      {hoverPreview && (
        <div
          className="fixed z-40 bg-zinc-900 border border-zinc-700 rounded-lg shadow-2xl p-3 pointer-events-none"
          style={{
            left: Math.min(hoverPreview.x, Math.max(0, window.innerWidth - 260)),
            top: Math.min(hoverPreview.y, Math.max(0, window.innerHeight - 220)),
          }}
          data-testid="loss-chart-tooltip"
        >
          <div className="text-xs text-zinc-400 mb-1 truncate max-w-[220px]" title={hoverPreview.name}>
            {hoverPreview.name}
          </div>
          <img
            src={previewUrl(hoverPreview.path)}
            alt={t('trainer.lossChartAlt')}
            className="rounded max-w-[220px]"
            style={{ maxHeight: 180 }}
            draggable={false}
          />
        </div>
      )}

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
              src={previewUrl(activePreview.path)}
              alt={t('trainer.lossChartAlt')}
              className={'w-full h-auto rounded ' + (previewLoading ? 'hidden' : '')}
              style={{ maxHeight: 220 }}
              draggable={false}
              onLoad={() => setPreviewLoading(false)}
              onError={() => setPreviewLoading(false)}
            />
          </div>
        </div>
      )}

      {/* Import model dialog */}
      {showImport && (
        <div
          className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
          onClick={() => setShowImport(false)}
          data-testid="import-model-dialog"
        >
          <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-5 w-96 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-sm font-semibold text-zinc-200">{t('trainer.importModel')}</h4>
              <button
                onClick={() => setShowImport(false)}
                aria-label={t('trainer.close')}
                title={t('trainer.close')}
                className="p-1 text-zinc-500 hover:text-zinc-200 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="space-y-3">
              <label className="block">
                <span className="text-xs text-zinc-400">{t('trainer.importModelFile')}</span>
                <input
                  type="file"
                  accept=".tflite,.h5,.zip"
                  className={fileInputClass}
                  onChange={(e) => setImportModelFile(e.target.files?.[0] ?? null)}
                />
              </label>
              <label className="block">
                <span className="text-xs text-zinc-400">{t('trainer.importLossImage')}</span>
                <input
                  type="file"
                  accept=".png,.jpg,.jpeg"
                  className={fileInputClass}
                  onChange={(e) => setImportLossImage(e.target.files?.[0] ?? null)}
                />
              </label>
              <label className="block">
                <span className="text-xs text-zinc-400">{t('trainer.importMetaJson')}</span>
                <input
                  type="file"
                  accept=".json,application/json"
                  className={fileInputClass}
                  onChange={(e) => setImportMetaJson(e.target.files?.[0] ?? null)}
                />
              </label>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setShowImport(false)}
                disabled={importing}
                className="px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 transition-colors disabled:text-zinc-600"
              >
                {t('trainer.cancel')}
              </button>
              <button
                onClick={handleImportSubmit}
                disabled={!importModelFile || importing}
                className="px-3 py-1.5 text-xs bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30 rounded transition-colors disabled:text-zinc-600 disabled:bg-zinc-800"
              >
                {importing ? t('trainer.importing') : t('trainer.importConfirm')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Upload loss (补传) dialog */}
      {uploadTarget && (
        <div
          className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
          onClick={() => setUploadTarget(null)}
          data-testid="upload-loss-dialog"
        >
          <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-5 w-96 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-1">
              <h4 className="text-sm font-semibold text-zinc-200">{t('trainer.uploadLossTitle')}</h4>
              <button
                onClick={() => setUploadTarget(null)}
                aria-label={t('trainer.close')}
                title={t('trainer.close')}
                className="p-1 text-zinc-500 hover:text-zinc-200 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <p className="text-xs text-zinc-500 mb-3">
              <span className="text-zinc-300">{uploadTarget.name}</span> · {t('trainer.uploadLossHint')}
            </p>
            <div className="space-y-3">
              <label className="block">
                <span className="text-xs text-zinc-400">{t('trainer.importLossImage')}</span>
                <input
                  type="file"
                  accept=".png,.jpg,.jpeg"
                  className={fileInputClass}
                  onChange={(e) => setUploadLossImage(e.target.files?.[0] ?? null)}
                />
              </label>
              <label className="block">
                <span className="text-xs text-zinc-400">{t('trainer.importMetaJson')}</span>
                <input
                  type="file"
                  accept=".json,application/json"
                  className={fileInputClass}
                  onChange={(e) => setUploadMetaJson(e.target.files?.[0] ?? null)}
                />
              </label>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setUploadTarget(null)}
                disabled={uploading}
                className="px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 transition-colors disabled:text-zinc-600"
              >
                {t('trainer.cancel')}
              </button>
              <button
                onClick={handleUploadLossSubmit}
                disabled={uploading}
                className="px-3 py-1.5 text-xs bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30 rounded transition-colors disabled:text-zinc-600 disabled:bg-zinc-800"
              >
                {uploading ? t('trainer.loading') : t('trainer.uploadLoss')}
              </button>
            </div>
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
