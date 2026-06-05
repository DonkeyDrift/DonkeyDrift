import React, { useEffect, useState, useCallback, useRef } from 'react';
import { listModels, deleteModel, downloadModelUrl, loadModelToCar, API_URL, getApiErrorMessage } from '../../services/api';
import { useStore } from '../../store/useStore';
import { FileText, Copy, TrendingDown, Download, Send } from 'lucide-react';

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
  const { configPath, trainingJob } = useStore();
  const [models, setModels] = useState<ModelItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [activePreview, setActivePreview] = useState<{
    path: string;
    name: string;
    rect: DOMRect;
  } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<ModelItem | null>(null);
  const previewTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  const showPreview = (model: ModelItem, rect: DOMRect) => {
    if (previewTimerRef.current) {
      clearTimeout(previewTimerRef.current);
    }
    if (model.previewPath) {
      if (previewLoading && activePreview?.path !== model.previewPath) {
        return;
      }
      setActivePreview({ path: model.previewPath, name: model.name, rect });
      setPreviewLoading(true);
    }
  };

  const hidePreview = (delay = 200) => {
    if (previewTimerRef.current) {
      clearTimeout(previewTimerRef.current);
    }
    previewTimerRef.current = setTimeout(() => {
      setActivePreview(null);
      setPreviewLoading(false);
    }, delay);
  };

  const togglePreview = (model: ModelItem, rect: DOMRect) => {
    if (activePreview?.path === model.previewPath) {
      setActivePreview(null);
      setPreviewLoading(false);
    } else if (model.previewPath) {
      if (previewLoading) {
        return;
      }
      if (previewTimerRef.current) {
        clearTimeout(previewTimerRef.current);
      }
      setActivePreview({ path: model.previewPath, name: model.name, rect });
      setPreviewLoading(true);
    }
  };

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

  // Compute fixed-position popover coordinates
  const getPopoverStyle = (): React.CSSProperties => {
    if (!activePreview) return { display: 'none' };
    const rect = activePreview.rect;
    const padding = 12;
    const popoverWidth = 320;
    const popoverHeight = 260;

    let left = rect.left + rect.width / 2 - popoverWidth / 2;
    let top = rect.top - popoverHeight - padding;

    // Keep inside viewport
    if (left < 8) left = 8;
    if (left + popoverWidth > window.innerWidth - 8) {
      left = window.innerWidth - popoverWidth - 8;
    }
    if (top < 8) {
      top = rect.bottom + padding;
    }

    return {
      position: 'fixed',
      left,
      top,
      width: popoverWidth,
      zIndex: 9999,
    };
  };

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-3 relative">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">Trained Models</h3>
        <button
          onClick={refresh}
          disabled={loading}
          className="text-xs text-cyan-500 hover:text-cyan-400 disabled:text-zinc-600 transition-colors"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {models.length === 0 && (
        <div className="text-sm text-zinc-600">No models found in ./models</div>
      )}

      <div className="space-y-2 max-h-64 overflow-y-auto">
        {models.map((m) => (
          <div
            key={m.name}
            className="bg-zinc-950 rounded px-3 py-2 border border-zinc-800/50 cursor-default"
            onMouseEnter={(e) => m.previewPath && showPreview(m, e.currentTarget.getBoundingClientRect())}
            onMouseLeave={() => hidePreview()}
            onClick={(e) => m.previewPath && togglePreview(m, e.currentTarget.getBoundingClientRect())}
          >
            {/* Row 1: model name + loss badge */}
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <FileText className="w-4 h-4 text-zinc-500 shrink-0" />
                <span className="text-sm text-zinc-300 truncate" title={m.name}>{m.name}</span>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                {typeof m.finalLoss === 'number' && (
                  <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded mr-1">
                    <TrendingDown className="w-3 h-3" />
                    {m.finalLoss.toFixed(4)}
                  </span>
                )}
                <a
                  href={downloadModelUrl(m.path)}
                  onClick={(e) => e.stopPropagation()}
                  title="Download model"
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
                      alert('模型加载指令已下发到车端');
                    } catch (error) {
                      alert(`加载失败: ${getApiErrorMessage(error)}`);
                    }
                  }}
                  title="加载到车端"
                  className="p-1 text-zinc-500 hover:text-emerald-400 transition-colors"
                >
                  <Send className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    navigator.clipboard.writeText(m.path);
                  }}
                  title="Copy path"
                  className="p-1 text-zinc-500 hover:text-zinc-300 transition-colors"
                >
                  <Copy className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {/* Row 2: metadata */}
            <div className="flex items-center justify-between mt-1">
              <span className="text-xs text-zinc-600">
                {formatSize(m.size)} · {new Date(m.modified).toLocaleString()}
                {typeof m.bestLoss === 'number' && typeof m.finalLoss === 'number' && m.bestLoss !== m.finalLoss && (
                  <span className="ml-2 text-zinc-500">
                    best: {m.bestLoss.toFixed(4)}
                  </span>
                )}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Fixed-position preview popover */}
      {activePreview && (
        <div
          className="bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl p-2"
          style={getPopoverStyle()}
          onMouseEnter={() => {
            if (previewTimerRef.current) clearTimeout(previewTimerRef.current);
          }}
          onMouseLeave={() => hidePreview()}
        >
          <div className="text-xs text-zinc-400 mb-1 text-center truncate" title={activePreview.name}>
            {activePreview.name}
          </div>
          {previewLoading && (
            <div className="w-full h-32 flex items-center justify-center text-zinc-500 text-sm">
              Loading...
            </div>
          )}
          <img
            src={`${API_URL}/trainer/models/preview?path=${encodeURIComponent(activePreview.path)}`}
            alt="Training loss chart"
            className={`w-full h-auto rounded ${previewLoading ? 'hidden' : ''}`}
            style={{ maxHeight: 220 }}
            draggable={false}
            onLoad={() => setPreviewLoading(false)}
            onError={() => setPreviewLoading(false)}
          />
        </div>
      )}

      {/* Delete confirmation modal */}
      {confirmDelete && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={() => setConfirmDelete(null)}>
          <div className="bg-zinc-900 border border-zinc-700 rounded-lg p-5 w-80 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <h4 className="text-sm font-semibold text-zinc-200 mb-2">Delete Model</h4>
            <p className="text-xs text-zinc-400 mb-4">
              Are you sure you want to delete <span className="text-zinc-200 font-medium">{confirmDelete.name}</span>? This will also remove its preview image and metadata. This action cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setConfirmDelete(null)}
                disabled={deleting === confirmDelete.path}
                className="px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 transition-colors disabled:text-zinc-600"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDelete(confirmDelete)}
                disabled={deleting === confirmDelete.path}
                className="px-3 py-1.5 text-xs bg-red-500/20 text-red-400 hover:bg-red-500/30 rounded transition-colors disabled:text-zinc-600 disabled:bg-zinc-800"
              >
                {deleting === confirmDelete.path ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
