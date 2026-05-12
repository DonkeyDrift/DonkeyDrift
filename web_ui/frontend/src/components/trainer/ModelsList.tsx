import React, { useEffect, useState, useCallback, useRef } from 'react';
import { listModels } from '../../services/api';
import { useStore } from '../../store/useStore';
import { FileText, Folder, Copy } from 'lucide-react';
import { API_URL } from '../../services/api';

interface ModelItem {
  name: string;
  type: 'file' | 'directory';
  size: number;
  modified: string;
  path: string;
  previewPath?: string;
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
  const previewTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

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
      setActivePreview({ path: model.previewPath, name: model.name, rect });
    }
  };

  const hidePreview = (delay = 200) => {
    if (previewTimerRef.current) {
      clearTimeout(previewTimerRef.current);
    }
    previewTimerRef.current = setTimeout(() => {
      setActivePreview(null);
    }, delay);
  };

  const togglePreview = (model: ModelItem, rect: DOMRect) => {
    if (activePreview?.path === model.previewPath) {
      setActivePreview(null);
    } else if (model.previewPath) {
      if (previewTimerRef.current) {
        clearTimeout(previewTimerRef.current);
      }
      setActivePreview({ path: model.previewPath, name: model.name, rect });
    }
  };

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
        <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">Models</h3>
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

      <div ref={listRef} className="space-y-2 max-h-64 overflow-y-auto">
        {models.map((m) => (
          <div
            key={m.name}
            className="flex items-center justify-between bg-zinc-950 rounded px-3 py-2 border border-zinc-800/50 cursor-default"
            onMouseEnter={(e) => m.previewPath && showPreview(m, e.currentTarget.getBoundingClientRect())}
            onMouseLeave={() => hidePreview()}
            onClick={(e) => m.previewPath && togglePreview(m, e.currentTarget.getBoundingClientRect())}
          >
            <div className="flex items-center gap-2 min-w-0">
              {m.type === 'directory' ? (
                <Folder className="w-4 h-4 text-cyan-500 shrink-0" />
              ) : (
                <FileText className="w-4 h-4 text-zinc-500 shrink-0" />
              )}
              <div className="min-w-0">
                <div className="text-sm text-zinc-300 truncate" title={m.name}>{m.name}</div>
                <div className="text-xs text-zinc-600">
                  {formatSize(m.size)} · {new Date(m.modified).toLocaleString()}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  navigator.clipboard.writeText(m.path);
                }}
                title="Copy path"
                className="p-1.5 text-zinc-500 hover:text-zinc-300 transition-colors"
              >
                <Copy className="w-3.5 h-3.5" />
              </button>
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
          <img
            src={`${API_URL}/trainer/models/preview?path=${encodeURIComponent(activePreview.path)}`}
            alt="Training loss chart"
            className="w-full h-auto rounded"
            style={{ maxHeight: 220 }}
            draggable={false}
          />
        </div>
      )}
    </div>
  );
};
