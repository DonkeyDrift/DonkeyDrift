import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Button } from './ui/Button';
import { useStore } from '../store/useStore';
import {
  deleteTubSession,
  getApiErrorMessage,
  getImageUrl,
  getSessionRecords,
  listTubSessions,
  type TubSession,
  type TubRecord,
} from '../services/api';
import { useTranslation } from '@/i18n';
import { useResolvedTheme } from '@/lib/theme';
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  Clapperboard,
  Pause,
  Play,
  Trash2,
} from 'lucide-react';

const formatDateTime = (ms: number | null) => {
  if (ms === null || ms === undefined) return null;
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return null;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
};

const formatDuration = (startMs: number | null, endMs: number | null) => {
  if (startMs === null || endMs === null || endMs < startMs) return null;
  return `${((endMs - startMs) / 1000).toFixed(1)}s`;
};

const findImagePath = (record: TubRecord | undefined) => {
  if (!record) return null;
  const key = Object.keys(record).find((k) => k.endsWith('image_array'));
  return key && typeof record[key] === 'string' ? (record[key] as string) : null;
};

export const TubLibrary: React.FC = () => {
  const { t } = useTranslation();
  const theme = useResolvedTheme();
  const tubPath = useStore((state) => state.tubPath);
  const setTub = useStore((state) => state.setTub);
  const fields = useStore((state) => state.fields);
  const driveLoopHz = useStore((state) => Number(state.config?.DRIVE_LOOP_HZ) || 60);

  const [sessions, setSessions] = useState<TubSession[]>([]);
  const [selected, setSelected] = useState<TubSession | null>(null);
  const [records, setRecords] = useState<TubRecord[]>([]);
  const [frame, setFrame] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<TubSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [imageError, setImageError] = useState(false);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageCacheRef = useRef<Map<string, HTMLImageElement>>(new Map());
  const rafRef = useRef<number>();
  const lastFrameTimeRef = useRef<number>(0);
  const frameRef = useRef(0);

  const frameInterval = 1000 / Math.max(1, driveLoopHz);

  const refreshSessions = useCallback(async (path: string) => {
    setError(null);
    try {
      const data = await listTubSessions(path);
      setSessions(data.sessions || []);
    } catch (err) {
      setSessions([]);
      setError(getApiErrorMessage(err, t('tubLibrary.loadFailed')));
    }
  }, [t]);

  useEffect(() => {
    setSelected(null);
    setRecords([]);
    setFrame(0);
    setIsPlaying(false);
    if (tubPath) {
      void refreshSessions(tubPath);
    } else {
      setSessions([]);
    }
  }, [tubPath, refreshSessions]);

  // Stop playback when the selected session changes
  useEffect(() => {
    setIsPlaying(false);
    setFrame(0);
    frameRef.current = 0;
    setImageError(false);
    setRecords([]);
    imageCacheRef.current.clear();
    if (!selected || !tubPath) return;

    let cancelled = false;
    (async () => {
      try {
        const data = await getSessionRecords(tubPath, selected.session_id);
        if (cancelled) return;
        setRecords(data.records || []);
      } catch (err) {
        if (!cancelled) {
          setError(getApiErrorMessage(err, t('tubLibrary.loadFailed')));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected, tubPath, t]);

  const currentImagePath = useMemo(() => findImagePath(records[frame]), [records, frame]);

  // Draw the current frame whenever it changes
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;

    if (!currentImagePath) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = theme === 'light' ? '#f4f6f9' : '#18181b';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      return;
    }

    const url = getImageUrl(currentImagePath, tubPath);
    let img = imageCacheRef.current.get(url);
    if (!img) {
      img = new Image();
      img.src = url;
      imageCacheRef.current.set(url, img);
    }

    const draw = (image: HTMLImageElement) => {
      if (canvas.width !== image.width || canvas.height !== image.height) {
        canvas.width = image.width;
        canvas.height = image.height;
      }
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(image, 0, 0);
      setImageError(false);
    };

    if (img.complete && img.naturalWidth > 0) {
      draw(img);
    } else {
      const onLoad = () => draw(img as HTMLImageElement);
      const onError = () => setImageError(true);
      img.addEventListener('load', onLoad);
      img.addEventListener('error', onError);
      return () => {
        img?.removeEventListener('load', onLoad);
        img?.removeEventListener('error', onError);
      };
    }
  }, [currentImagePath, tubPath, theme]);

  // Prefetch upcoming frames so playback does not stall on image fetches
  useEffect(() => {
    if (!records.length) return;
    for (let offset = 1; offset <= 30; offset += 1) {
      const nextPath = findImagePath(records[frame + offset]);
      if (!nextPath) continue;
      const url = getImageUrl(nextPath, tubPath);
      if (imageCacheRef.current.has(url)) continue;
      const img = new Image();
      img.src = url;
      imageCacheRef.current.set(url, img);
    }
  }, [frame, records, tubPath]);

  // Playback loop: advance frames at DRIVE_LOOP_HZ, only when cached to avoid stalls
  useEffect(() => {
    if (!isPlaying || !records.length) return;

    const step = (time: number) => {
      if (lastFrameTimeRef.current === 0) {
        lastFrameTimeRef.current = time;
      }
      if (time - lastFrameTimeRef.current >= frameInterval) {
        lastFrameTimeRef.current = time - ((time - lastFrameTimeRef.current) % frameInterval);
        let next = frameRef.current + 1;
        if (next >= records.length) {
          next = 0;
        }
        const nextPath = findImagePath(records[next]);
        if (nextPath) {
          const nextImg = imageCacheRef.current.get(getImageUrl(nextPath, tubPath));
          if (!nextImg || !nextImg.complete) {
            // Frame not ready yet: hold on the current frame instead of skipping
            rafRef.current = requestAnimationFrame(step);
            return;
          }
        }
        frameRef.current = next;
        setFrame(next);
      }
      rafRef.current = requestAnimationFrame(step);
    };

    lastFrameTimeRef.current = 0;
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [isPlaying, records, frameInterval]);

  const confirmDelete = useCallback(async () => {
    if (!pendingDelete || !tubPath) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteTubSession(tubPath, pendingDelete.session_id);
      setPendingDelete(null);
      if (selected?.session_id === pendingDelete.session_id) {
        setSelected(null);
      }
      await refreshSessions(tubPath);
      // Keep the global tub in sync so other panels drop the deleted frames too
      try {
        const { loadTub } = await import('../services/api');
        const data = await loadTub(tubPath);
        setTub(
          data.path,
          data.records || [],
          data.fields || [],
          data.total_physical_records,
          data.deleted_indexes,
        );
      } catch {
        // Refreshing the global tub is best-effort; the library list is already updated
      }
    } catch (err) {
      setError(getApiErrorMessage(err, t('tubLibrary.deleteFailed')));
    } finally {
      setDeleting(false);
    }
  }, [pendingDelete, tubPath, selected, refreshSessions, setTub, t]);

  const hasRecords = records.length > 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Clapperboard className="w-5 h-5" />
          {t('tubLibrary.title')}
        </CardTitle>
        <p className="text-sm text-zinc-400">{t('tubLibrary.subtitle')}</p>
      </CardHeader>
      <CardContent>
        {!tubPath ? (
          <div className="h-40 flex items-center justify-center text-zinc-500 text-sm">
            {t('tubLibrary.noTubLoaded')}
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-[minmax(220px,320px)_1fr] gap-4">
            {/* Left: recording list */}
            <div className="flex flex-col min-h-0 max-h-[520px]">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-zinc-400">
                  {t('tubLibrary.recordingsCount', { count: sessions.length })}
                </span>
              </div>
              {error && (
                <div className="flex items-center gap-2 text-xs text-red-400 mb-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span className="break-all">{error}</span>
                </div>
              )}
              <div className="flex-1 overflow-y-auto rounded-lg border border-zinc-800 divide-y divide-zinc-800">
                {sessions.length === 0 && !error && (
                  <div className="p-4 text-sm text-zinc-500 text-center">
                    {t('tubLibrary.noRecordings')}
                  </div>
                )}
                {sessions.map((session) => {
                  const isSelected = selected?.session_id === session.session_id;
                  return (
                    <button
                      key={session.session_id}
                      type="button"
                      onClick={() => setSelected(session)}
                      className={`w-full text-left px-3 py-2.5 flex items-center justify-between gap-2 transition-colors ${
                        isSelected
                          ? 'bg-cyan-500/10 border-l-2 border-cyan-400'
                          : 'hover:bg-zinc-800/60 border-l-2 border-transparent'
                      }`}
                    >
                      <div className="min-w-0">
                        <div className="text-sm font-medium truncate">
                          {formatDateTime(session.start_time_ms)
                            ?? session.session_id}
                        </div>
                        <div className="text-xs text-zinc-500">
                          {t('tubLibrary.frames', { count: session.record_count })}
                          {formatDuration(session.start_time_ms, session.end_time_ms)
                            ? ` · ${formatDuration(session.start_time_ms, session.end_time_ms)}`
                            : ''}
                        </div>
                      </div>
                      <span
                        role="button"
                        tabIndex={0}
                        aria-label={t('tubLibrary.deleteAria')}
                        title={t('tubLibrary.deleteAria')}
                        onClick={(e) => {
                          e.stopPropagation();
                          setPendingDelete(session);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.stopPropagation();
                            e.preventDefault();
                            setPendingDelete(session);
                          }
                        }}
                        className="p-1.5 rounded-md text-zinc-500 hover:text-red-400 hover:bg-red-500/10 shrink-0 cursor-pointer"
                      >
                        <Trash2 className="w-4 h-4" />
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Right: player */}
            <div className="flex flex-col gap-3">
              <div className="w-full aspect-video bg-zinc-950 rounded-lg overflow-hidden border border-zinc-800 flex items-center justify-center relative">
                {imageError ? (
                  <div className="flex flex-col items-center justify-center text-zinc-600 gap-2">
                    <AlertCircle className="w-8 h-8 text-red-500" />
                    <span className="text-red-500">{t('tub.imageLoadError')}</span>
                  </div>
                ) : currentImagePath ? (
                  <canvas ref={canvasRef} className="w-full h-full object-contain" width={640} height={240} />
                ) : (
                  <span className="text-zinc-600 text-sm">
                    {selected ? t('tubLibrary.loading') : t('tubLibrary.selectHint')}
                  </span>
                )}
              </div>

              <input
                type="range"
                min={0}
                max={Math.max(0, records.length - 1)}
                value={frame}
                disabled={!hasRecords}
                onChange={(e) => {
                  const idx = parseInt(e.target.value);
                  setIsPlaying(false);
                  frameRef.current = idx;
                  setFrame(idx);
                }}
                aria-label={t('tubLibrary.progressAria')}
                className="w-full h-2 rounded-lg appearance-none cursor-pointer accent-cyan-500 disabled:opacity-40"
              />

              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  aria-label={t('tub.prevRecordAria')}
                  disabled={!hasRecords || isPlaying}
                  onClick={() => {
                    const idx = Math.max(0, frameRef.current - 1);
                    frameRef.current = idx;
                    setFrame(idx);
                  }}
                >
                  <ChevronLeft className="w-4 h-4" />
                </Button>
                <Button
                  size="sm"
                  variant={isPlaying ? 'danger' : 'primary'}
                  className="flex-1"
                  disabled={!hasRecords}
                  aria-label={isPlaying ? t('tub.stopPlaybackAria') : t('tub.startPlaybackAria')}
                  onClick={() => setIsPlaying((v) => !v)}
                >
                  {isPlaying
                    ? <><Pause className="w-4 h-4" /> {t('tub.stop')}</>
                    : <><Play className="w-4 h-4" /> {t('tub.play')}</>}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  aria-label={t('tub.nextRecordAria')}
                  disabled={!hasRecords || isPlaying}
                  onClick={() => {
                    const idx = Math.min(records.length - 1, frameRef.current + 1);
                    frameRef.current = idx;
                    setFrame(idx);
                  }}
                >
                  <ChevronRight className="w-4 h-4" />
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  disabled={!selected || deleting}
                  aria-label={t('tubLibrary.deleteAria')}
                  onClick={() => selected && setPendingDelete(selected)}
                >
                  <Trash2 className="w-4 h-4" />
                  <span className="ml-1 text-xs">{t('tubLibrary.delete')}</span>
                </Button>
              </div>

              <div className="text-xs text-zinc-500">
                {selected
                  ? t('tubLibrary.frameLabel', {
                      index: hasRecords ? frame + 1 : 0,
                      total: records.length,
                    })
                  : t('tubLibrary.selectHint')}
              </div>
            </div>
          </div>
        )}

        {/* Delete confirmation */}
        {pendingDelete && (
          <div className="fixed inset-0 bg-black/60 z-[70] flex items-center justify-center p-4">
            <div className="bg-zinc-900 border border-zinc-700 rounded-xl max-w-md w-full p-5 shadow-2xl">
              <div className="flex items-start gap-3">
                <div className="p-2 rounded-full bg-red-500/15 shrink-0">
                  <Trash2 className="w-5 h-5 text-red-400" />
                </div>
                <div className="min-w-0">
                  <h3 className="text-base font-semibold">{t('tubLibrary.confirmTitle')}</h3>
                  <p className="text-sm text-zinc-400 mt-1 break-all">
                    {t('tubLibrary.confirmBody', {
                      name: formatDateTime(pendingDelete.start_time_ms) ?? pendingDelete.session_id,
                      count: pendingDelete.record_count,
                    })}
                  </p>
                </div>
              </div>
              <div className="flex justify-end gap-2 mt-5">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={deleting}
                  onClick={() => setPendingDelete(null)}
                >
                  {t('tubLibrary.cancel')}
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  disabled={deleting}
                  onClick={() => void confirmDelete()}
                >
                  {deleting ? t('tubLibrary.deleting') : t('tubLibrary.confirmDelete')}
                </Button>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
