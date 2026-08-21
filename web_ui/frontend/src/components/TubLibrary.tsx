import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Card, CardContent, CardHeader } from './ui/Card';
import { SectionCardTitle } from './ui/SectionCardTitle';
import { Button } from './ui/Button';
import { useStore, type TubRecord as StoreTubRecord } from '../store/useStore';
import {
  deleteTubSession,
  downloadTubSession,
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
  ChevronsLeft,
  ChevronsRight,
  Clapperboard,
  Download,
  Pause,
  Pin,
  Play,
  RotateCcw,
  Trash2,
} from 'lucide-react';

// 图片缓存上限：按播放位置预取后续帧，无上限时长会话内存无限增长、
// 加重 GC 拖慢页面切换，超限后按 LRU（Map 插入序）淘汰最旧条目（#135）
const MAX_IMAGE_CACHE_ENTRIES = 240;

// 60fps 播放时预取窗口需覆盖 ~1s 的帧，10 帧只有 ~167ms，
// 磁盘/网络稍慢就击穿窗口导致画面冻结跳帧。60 帧给足余量（#128）。
const PREFETCH_AHEAD = 60;
// HTTP/1.1 同源并发连接约 6 个，预取并发超过它反而会挤占当前帧请求。
const PREFETCH_CONCURRENCY = 6;

// 播放时每 N 帧才更新一次 React 状态（帧计数器、进度条、统计），
// 避免每帧 re-render 整个组件树吃掉帧预算导致掉帧（#128）。
const UI_UPDATE_EVERY_N_FRAMES = 6;

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

const formatStatValue = (value: unknown, notAvailable: string) => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value.toFixed(2);
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed.toFixed(2);
    }
  }
  return notAvailable;
};

const pinnedKey = (tubPath: string) => `tubLibrary.pinned.${tubPath}`;

const loadPinned = (tubPath: string): string[] => {
  try {
    const raw = localStorage.getItem(pinnedKey(tubPath));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((v) => typeof v === 'string') : [];
  } catch {
    return [];
  }
};

const savePinned = (tubPath: string, ids: string[]) => {
  try {
    localStorage.setItem(pinnedKey(tubPath), JSON.stringify(ids));
  } catch {
    // localStorage unavailable (private mode etc.): pinning stays session-only
  }
};

interface RecordStatsProps {
  steering: string;
  throttle: string;
}

const RecordStats = React.memo(({ steering, throttle }: RecordStatsProps) => {
  const { t } = useTranslation();
  return (
    <div className="flex gap-4 text-left">
      <div className="bg-zinc-800 rounded-md flex h-[44px] w-[80px] flex-col items-start justify-center px-2.5 pt-1 pb-1 text-left">
        <div className="text-[10px] text-zinc-400 uppercase leading-tight">{t('tub.steering')}</div>
        <div className="text-sm font-mono text-cyan-400 leading-tight">{steering}</div>
      </div>
      <div className="bg-zinc-800 rounded-md flex h-[44px] w-[80px] flex-col items-start justify-center px-2.5 pt-1 pb-1 text-left">
        <div className="text-[10px] text-zinc-400 uppercase leading-tight">{t('tub.throttle')}</div>
        <div className="text-sm font-mono text-cyan-400 leading-tight">{throttle}</div>
      </div>
    </div>
  );
});

export const TubLibrary: React.FC = () => {
  const { t } = useTranslation();
  const theme = useResolvedTheme();
  const tubPath = useStore((state) => state.tubPath);
  // TM 页在 App 中常驻保活（#135）：据此在切走时停播并屏蔽全局快捷键
  const isTubManagerRoute = useLocation().pathname === '/';
  const setTub = useStore((state) => state.setTub);
  const config = useStore((state) => state.config);
  const isLoading = useStore((state) => state.isLoading);
  const requestTubRefresh = useStore((state) => state.requestTubRefresh);
  const setCurrentIndex = useStore((state) => state.setCurrentIndex);
  const setActiveSession = useStore((state) => state.setActiveSession);
  const driveLoopHz = Number(config?.DRIVE_LOOP_HZ) || 60;

  const [sessions, setSessions] = useState<TubSession[]>([]);
  const [selected, setSelected] = useState<TubSession | null>(null);
  const [records, setRecords] = useState<TubRecord[]>([]);
  const [frame, setFrame] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<TubSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [imageError, setImageError] = useState(false);
  const [frameAspect, setFrameAspect] = useState<number | null>(null);
  const [pinned, setPinned] = useState<string[]>([]);
  const [actualFps, setActualFps] = useState(0);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageCacheRef = useRef<Map<string, HTMLImageElement>>(new Map());
  const rafRef = useRef<number>();
  const lastFrameTimeRef = useRef<number>(0);
  const frameRef = useRef(0);
  const isPlayingRef = useRef(false);
  const recordsRef = useRef(records);
  const fpsStartRef = useRef<number>(0);
  const fpsFramesRef = useRef<number>(0);
  const lastIndexSyncRef = useRef<number>(0);
  // 预计算所有帧的图片 URL，避免播放循环每帧重复调用 getImageUrl()
  const imageUrlsRef = useRef<string[]>([]);

  const frameInterval = 1000 / Math.max(1, driveLoopHz);

  // LRU 写入：命中时刷新位置，超限淘汰最旧条目（#135）
  const touchImageCache = useCallback((url: string, img: HTMLImageElement) => {
    const cache = imageCacheRef.current;
    if (cache.has(url)) cache.delete(url);
    cache.set(url, img);
    while (cache.size > MAX_IMAGE_CACHE_ENTRIES) {
      const oldest = cache.keys().next().value;
      if (oldest === undefined) break;
      cache.delete(oldest);
    }
  }, []);

  // 预取：从指定索引开始向前 PREFETCH_AHEAD 帧发起加载请求。
  // 从播放循环内调用，不作为独立 React effect，避免每帧触发 effect 开销。
  const prefetchFromIndex = useCallback((idx: number) => {
    const urls = imageUrlsRef.current;
    if (!urls.length) return;
    const toFetch: string[] = [];
    for (let offset = 1; offset <= PREFETCH_AHEAD; offset += 1) {
      const url = urls[idx + offset];
      if (!url) continue;
      const cached = imageCacheRef.current.get(url);
      if (cached) {
        touchImageCache(url, cached);
        continue;
      }
      toFetch.push(url);
    }
    let cursor = 0;
    let inFlight = 0;
    const pump = () => {
      while (inFlight < PREFETCH_CONCURRENCY && cursor < toFetch.length) {
        const url = toFetch[cursor++];
        const img = new Image();
        inFlight += 1;
        img.onload = img.onerror = () => {
          inFlight -= 1;
          pump();
        };
        touchImageCache(url, img);
        img.src = url;
      }
    };
    pump();
  }, [touchImageCache]);

  const refreshSessions = useCallback(async (path: string) => {
    setError(null);
    try {
      const data = await listTubSessions(path);
      const items = data.sessions || [];
      setSessions(items);
      // Auto-select the newest recording when nothing (valid) is selected
      setSelected((prev) =>
        prev && items.some((s) => s.session_id === prev.session_id)
          ? prev
          : items[0] ?? null,
      );
    } catch (err) {
      setSessions([]);
      setError(getApiErrorMessage(err, t('tubLibrary.loadFailed')));
    }
  }, [t]);

  useEffect(() => {
    recordsRef.current = records;
  }, [records]);

  // 预计算所有帧的图片 URL，避免播放循环每帧重复调用 getImageUrl()
  useEffect(() => {
    imageUrlsRef.current = records.map((r) => {
      const path = findImagePath(r);
      return path ? getImageUrl(path, tubPath) : '';
    });
  }, [records, tubPath]);

  useEffect(() => {
    isPlayingRef.current = isPlaying;
    if (!isPlaying) {
      setActualFps(0);
      fpsStartRef.current = 0;
      fpsFramesRef.current = 0;
      // 播放结束后把实际显示帧同步到 React 状态，让进度条/统计/全局联动对齐
      setFrame(frameRef.current);
    }
  }, [isPlaying]);

  useEffect(() => {
    setSelected(null);
    setRecords([]);
    setFrame(0);
    frameRef.current = 0;
    setIsPlaying(false);
    setPinned(tubPath ? loadPinned(tubPath) : []);
    imageCacheRef.current.clear();
    setActiveSession(null, []);
    if (tubPath) {
      void refreshSessions(tubPath);
    } else {
      setSessions([]);
    }
  }, [tubPath, refreshSessions, setActiveSession]);

  // Stop playback when the selected session changes
  useEffect(() => {
    setIsPlaying(false);
    setFrame(0);
    frameRef.current = 0;
    setImageError(false);
    setRecords([]);
    imageCacheRef.current.clear();
    if (!selected || !tubPath) {
      setActiveSession(null, []);
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const data = await getSessionRecords(tubPath, selected.session_id);
        if (cancelled) return;
        setRecords(data.records || []);
        setActiveSession(selected.session_id, (data.records || []) as StoreTubRecord[]);
      } catch (err) {
        if (!cancelled) {
          setError(getApiErrorMessage(err, t('tubLibrary.loadFailed')));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected, tubPath, t, setActiveSession]);

  // 全局图表联动（原 Tub 导航器职责）：库内换帧/播放时把当前帧下标写入全局
  // currentIndex（帧下标），让 Tub Editor 的 Data Graph 红色竖线跟随；播放期间
  // 按 ~30fps 节流写回，避免 60fps 全局 re-render。
  useEffect(() => {
    if (!records.length) return;
    const now = performance.now();
    if (isPlayingRef.current && now - lastIndexSyncRef.current < 30) return;
    lastIndexSyncRef.current = now;
    if (useStore.getState().currentIndex !== frame) {
      setCurrentIndex(frame);
    }
  }, [frame, records, setCurrentIndex]);

  // 反向联动：在 Tub Editor 图表上点选帧（全局 currentIndex 变化）时，若该帧
  // 属于当前场次则跳转预览画面（播放中不打断）。
  useEffect(() => {
    const unsubscribe = useStore.subscribe((state) => {
      if (isPlayingRef.current) return;
      const recs = recordsRef.current;
      if (!recs.length) return;
      if (typeof state.currentIndex !== 'number') return;
      if (state.currentIndex < 0 || state.currentIndex >= recs.length) return;
      if (state.currentIndex !== frameRef.current) {
        frameRef.current = state.currentIndex;
        setFrame(state.currentIndex);
      }
    });
    return unsubscribe;
  }, []);

  const currentRecord = records[frame];
  const currentImagePath = useMemo(() => findImagePath(currentRecord), [currentRecord]);

  const statValue = (key: string, altKey?: string) =>
    formatStatValue(
      currentRecord?.[key] ?? (altKey ? currentRecord?.[altKey] : undefined),
      t('tub.notAvailable'),
    );

  // Draw the current frame whenever it changes (manual navigation only;
  // playback loop draws directly to canvas to avoid per-frame React re-render)
  useEffect(() => {
    // 播放期间由播放循环直接画到 canvas，跳过此 effect 避免 re-render
    if (isPlayingRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;

    if (!currentImagePath) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = theme === 'light' ? '#f4f6f9' : '#18181b';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      setFrameAspect(null);
      return;
    }

    const url = getImageUrl(currentImagePath, tubPath);
    let img = imageCacheRef.current.get(url);
    if (!img) {
      img = new Image();
      img.src = url;
    }
    touchImageCache(url, img);

    const draw = (image: HTMLImageElement) => {
      if (canvas.width !== image.width || canvas.height !== image.height) {
        canvas.width = image.width;
        canvas.height = image.height;
      }
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(image, 0, 0);
      setImageError(false);
      setFrameAspect(image.width / image.height);
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
  }, [currentImagePath, tubPath, theme, touchImageCache]);

  // Playback loop: advance frames at DRIVE_LOOP_HZ, drawing directly to canvas
  // and throttling React state updates to ~10fps to avoid per-frame re-renders
  // that eat the frame budget and cause dropped frames (#128).
  useEffect(() => {
    if (!isPlaying || !records.length) return;

    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');

    const step = (time: number) => {
      if (!isPlayingRef.current) return;
      if (lastFrameTimeRef.current === 0) {
        lastFrameTimeRef.current = time;
        fpsStartRef.current = time;
      }
      if (time - lastFrameTimeRef.current >= frameInterval) {
        lastFrameTimeRef.current = time - ((time - lastFrameTimeRef.current) % frameInterval);
        const next = frameRef.current + 1;
        if (next >= records.length) {
          setIsPlaying(false);
          setFrame(frameRef.current);
          return;
        }
        const url = imageUrlsRef.current[next];
        if (url) {
          const nextImg = imageCacheRef.current.get(url);
          if (!nextImg || !nextImg.complete) {
            rafRef.current = requestAnimationFrame(step);
            return;
          }
          // 直接画到 canvas，不触发 React re-render
          if (canvas && ctx) {
            if (canvas.width !== nextImg.width || canvas.height !== nextImg.height) {
              canvas.width = nextImg.width;
              canvas.height = nextImg.height;
            }
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(nextImg, 0, 0);
          }
        }
        frameRef.current = next;

        // 预取节流：窗口 60 帧，每 6 帧发起一次仍有 54 帧余量
        if (next % UI_UPDATE_EVERY_N_FRAMES === 0) {
          prefetchFromIndex(next);
        }

        // FPS 按实际换帧数累计（#128），画面冻结时角标跟随下降
        fpsFramesRef.current += 1;
        if (time - fpsStartRef.current >= 1000) {
          setActualFps(Math.round((fpsFramesRef.current * 1000) / (time - fpsStartRef.current)));
          fpsStartRef.current = time;
          fpsFramesRef.current = 0;
        }

        // 节流 UI 状态更新（帧计数器、进度条、统计、全局 index 联动）
        if (next % UI_UPDATE_EVERY_N_FRAMES === 0) {
          setFrame(next);
        }
      }
      rafRef.current = requestAnimationFrame(step);
    };

    lastFrameTimeRef.current = 0;
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current !== undefined) cancelAnimationFrame(rafRef.current);
    };
  }, [isPlaying, records, frameInterval, prefetchFromIndex]);

  // 空格键播放/暂停（原 Tub 导航器快捷键；输入框内不触发；TM 页切走时不响应）
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code !== 'Space') return;
      if (!isTubManagerRoute) return;
      const active = document.activeElement;
      if (
        active instanceof HTMLTextAreaElement ||
        active instanceof HTMLSelectElement ||
        (active instanceof HTMLInputElement &&
          !['range', 'checkbox', 'radio', 'button', 'submit'].includes(active.type))
      ) {
        return;
      }
      e.preventDefault();
      setIsPlaying((v) => !v);
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isTubManagerRoute]);

  // 切走时自动停止回放，避免常驻保活后后台持续拉帧占资源
  useEffect(() => {
    if (!isTubManagerRoute) {
      isPlayingRef.current = false;
      setIsPlaying(false);
    }
  }, [isTubManagerRoute]);

  const jumpToFrame = useCallback((idx: number) => {
    setIsPlaying(false);
    frameRef.current = idx;
    setFrame(idx);
  }, []);

  const handleDownload = useCallback((session: TubSession) => {
    if (!tubPath) return;
    setDownloadingId(session.session_id);
    setError(null);
    try {
      downloadTubSession(tubPath, session.session_id, session.start_time_ms);
    } catch (err) {
      setError(getApiErrorMessage(err, t('tubLibrary.downloadFailed')));
    }
    // The browser handles the actual download natively (progress bar etc.)
    setTimeout(() => setDownloadingId(null), 1000);
  }, [tubPath, t]);

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
      // Drop the deleted clip from the pinned set too
      setPinned((prev) => {
        if (!prev.includes(pendingDelete.session_id)) return prev;
        const next = prev.filter((id) => id !== pendingDelete.session_id);
        savePinned(tubPath, next);
        return next;
      });
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

  // Pinned clips float to the top; both groups keep the API's newest-first order
  const pinnedSet = useMemo(() => new Set(pinned), [pinned]);
  const sortedSessions = useMemo(() => {
    const pinnedItems = sessions.filter((s) => pinnedSet.has(s.session_id));
    const rest = sessions.filter((s) => !pinnedSet.has(s.session_id));
    return [...pinnedItems, ...rest];
  }, [sessions, pinnedSet]);

  const togglePin = (session: TubSession) => {
    if (!tubPath) return;
    setPinned((prev) => {
      const next = prev.includes(session.session_id)
        ? prev.filter((id) => id !== session.session_id)
        : [...prev, session.session_id];
      savePinned(tubPath, next);
      return next;
    });
  };

  return (
    <Card className="shrink-0">
      <CardHeader>
        <SectionCardTitle
          icon={<Clapperboard className="w-5 h-5" />}
          title={t('tubLibrary.title')}
          subtitle={t('tub.subtitle')}
        />
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
            <div className="flex flex-col min-h-0 max-h-[24vh]">
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
                {sortedSessions.map((session) => {
                  const isSelected = selected?.session_id === session.session_id;
                  const isPinned = pinnedSet.has(session.session_id);
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
                      <div className="flex items-center gap-1 shrink-0">
                        <span
                          role="button"
                          tabIndex={0}
                          aria-label={isPinned ? t('tubLibrary.unpinAria') : t('tubLibrary.pinAria')}
                          title={isPinned ? t('tubLibrary.unpinAria') : t('tubLibrary.pinAria')}
                          onClick={(e) => {
                            e.stopPropagation();
                            togglePin(session);
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.stopPropagation();
                              e.preventDefault();
                              togglePin(session);
                            }
                          }}
                          className={`p-1.5 rounded-md shrink-0 cursor-pointer transition-colors ${
                            isPinned
                              ? 'text-cyan-400 hover:bg-cyan-500/10'
                              : 'text-zinc-500 hover:text-cyan-400 hover:bg-zinc-800/60'
                          }`}
                        >
                          <Pin className={`w-4 h-4 ${isPinned ? 'fill-current' : ''}`} />
                        </span>
                        <span
                          role="button"
                          tabIndex={0}
                          aria-label={t('tubLibrary.downloadAria')}
                          title={t('tubLibrary.downloadAria')}
                          onClick={(e) => {
                            e.stopPropagation();
                            void handleDownload(session);
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.stopPropagation();
                              e.preventDefault();
                              void handleDownload(session);
                            }
                          }}
                          className={`p-1.5 rounded-md shrink-0 cursor-pointer transition-colors ${
                            downloadingId === session.session_id
                              ? 'text-cyan-400'
                              : 'text-zinc-500 hover:text-cyan-400 hover:bg-zinc-800/60'
                          }`}
                        >
                          <Download className={`w-4 h-4 ${downloadingId === session.session_id ? 'animate-bounce' : ''}`} />
                        </span>
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
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Right: player */}
            <div className="flex flex-col gap-3">
              <div
                className="w-full max-h-[36vh] bg-zinc-950 rounded-lg overflow-hidden border border-zinc-800 flex items-center justify-center relative"
                style={{ aspectRatio: frameAspect != null ? String(frameAspect) : '16 / 9' }}
              >
                <div className={`absolute right-2 top-2 z-10 rounded-md border border-white/10 bg-zinc-900/80 px-2 py-1 text-center ${theme === 'light' ? 'shadow-[0_8px_24px_rgba(15,23,42,0.12)]' : 'shadow-[0_8px_24px_rgba(0,0,0,0.25)]'}`}>
                  <div className="text-[10px] text-zinc-400 uppercase leading-none">FPS</div>
                  <div className="text-base font-mono leading-tight text-cyan-400">{actualFps}</div>
                </div>
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

              <div className="flex items-center justify-between gap-4">
                <RecordStats
                  steering={statValue('user/angle', 'pilot/angle')}
                  throttle={statValue('user/throttle', 'pilot/throttle')}
                />
                <div className="text-xs text-zinc-500">
                  {selected
                    ? t('tubLibrary.frameLabel', {
                        index: hasRecords ? frame + 1 : 0,
                        total: records.length,
                      })
                    : t('tubLibrary.selectHint')}
                </div>
              </div>

              <input
                type="range"
                min={0}
                max={Math.max(0, records.length - 1)}
                value={frame}
                disabled={!hasRecords}
                onChange={(e) => jumpToFrame(parseInt(e.target.value))}
                aria-label={t('tubLibrary.progressAria')}
                className="w-full h-2 rounded-lg appearance-none cursor-pointer accent-cyan-500 disabled:opacity-40"
              />

              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  aria-label={t('tub.firstRecordAria')}
                  disabled={!hasRecords || isPlaying}
                  onClick={() => jumpToFrame(0)}
                >
                  <ChevronsLeft className="w-4 h-4" />
                  <span className="ml-1 text-xs">{t('tub.first')}</span>
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  aria-label={t('tub.prevRecordAria')}
                  disabled={!hasRecords || isPlaying}
                  onClick={() => jumpToFrame(Math.max(0, frameRef.current - 1))}
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
                  onClick={() => jumpToFrame(Math.min(records.length - 1, frameRef.current + 1))}
                >
                  <ChevronRight className="w-4 h-4" />
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  aria-label={t('tub.lastRecordAria')}
                  disabled={!hasRecords || isPlaying}
                  onClick={() => jumpToFrame(Math.max(0, records.length - 1))}
                >
                  <span className="mr-1 text-xs">{t('tub.last')}</span>
                  <ChevronsRight className="w-4 h-4" />
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  aria-label={t('tub.refreshAria')}
                  title={t('tub.refreshTitle')}
                  disabled={isLoading}
                  onClick={requestTubRefresh}
                >
                  <RotateCcw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
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
