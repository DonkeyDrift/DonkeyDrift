import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
  listFamilyTubSessions,
  loadTub,
  type ChildTubInfo,
  type FamilyTubSession,
  type TubRecord,
} from '../services/api';
import { useTranslation } from '@/i18n';
import { useResolvedTheme } from '@/lib/theme';
import {
  AlertCircle,
  Check,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Clapperboard,
  Download,
  Loader2,
  Pause,
  Pin,
  Play,
  RotateCcw,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { AiCleanModal } from './AiCleanModal';

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

// 墙钟播放调度（60fps 目标）：播放位置由「起点 + 经过的墙钟时间」推算，
// 每个 rAF tick 把进度追平到墙钟目标——某帧图片还没加载完时跳过它画最新可用的，
// 不再停摆等网络（旧逻辑一帧未 ready 整段播放冻住，且墙钟时间永久丢失）。
// 单个 tick 最多推进的帧数：抖动恢复后按此速率追帧，避免单 tick 爆冲。
const MAX_CATCHUP_FRAMES = 10;
// 落后墙钟超过这么多帧（~1s）视为长停顿（切后台/网络卡死）：
// 从当前帧重新对表继续 1x 播放，不追帧、不快进。
const MAX_RESUME_LAG_FRAMES = 60;

// 自动刷新规则（录制库缓存治理）：TM section 常驻挂载（#178），录制列表与
// 选中录制的帧只在 tubPath 变化/删除/AI 清理后拉取，Drive 页新录制的场次
// 不会自动出现，新老数据混在一起。除手动「刷新」外，激活期间每 30s 静默
// 检查一次新录制；播放中与浏览器后台标签页暂停；激活时数据已过期立即补一次。
const AUTO_REFRESH_INTERVAL_MS = 30_000;

/** 从根元素 computed style 解析 CSS 变量颜色；取不到（jsdom/变量缺失）回退 fallback。
 *  canvas 占位底色按 --surface 随主题（深/浅）切换自动重取色。 */
const cssVarColor = (name: string, fallback: string): string => {
  try {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  } catch {
    return fallback;
  }
};

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

// 家族聚合视图（方案 B）：_session_id 跨 tub 会撞名（如 tub_6/tub_7 都有
// 26-10-20_0），列表选中/置顶/下载态一律用 (tub_path, session_id) 复合键
const sessionKey = (session: Pick<FamilyTubSession, 'tub_path' | 'session_id'>) =>
  `${session.tub_path}::${session.session_id}`;

// 多选合并/批量操作的统一顺序：start_time_ms 升序（连续录制的时间序），
// 与点击先后、列表置顶顺序无关
const orderByStartTimeAsc = (list: FamilyTubSession[]) =>
  [...list].sort((a, b) => (a.start_time_ms ?? 0) - (b.start_time_ms ?? 0));

// 多选合并拉取：按各会话自己的 (tub_path, session_id) 并发取帧，给每条 record
// 打 __tubPath 标（跨 tub 播放取图按标走，见 imageUrlsRef 预计算），结果按
// ordered 顺序 concat（调用方传 time-asc 列表即得时间升序合并）
const fetchMergedSessionRecords = async (ordered: FamilyTubSession[]): Promise<TubRecord[]> => {
  const results = await Promise.all(
    ordered.map((s) => getSessionRecords(s.tub_path, s.session_id)),
  );
  return results.flatMap((r, i) =>
    (r.records || []).map((rec) => ({ ...rec, __tubPath: ordered[i].tub_path })),
  );
};

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
      <div className="bg-zinc-800 rounded-md flex h-[60px] w-[88px] flex-col items-start justify-center px-3 pt-[10px] pb-[10px] text-left">
        <div className="text-xs text-zinc-400 uppercase">{t('tub.steering')}</div>
        <div className="text-lg font-mono text-cyan-400">{steering}</div>
      </div>
      <div className="bg-zinc-800 rounded-md flex h-[60px] w-[88px] flex-col items-start justify-center px-3 pt-[10px] pb-[10px] text-left">
        <div className="text-xs text-zinc-400 uppercase">{t('tub.throttle')}</div>
        <div className="text-lg font-mono text-cyan-400">{throttle}</div>
      </div>
    </div>
  );
});

export const TubLibrary: React.FC<{ active?: boolean }> = ({ active = false }) => {
  const { t } = useTranslation();
  const theme = useResolvedTheme();
  const tubPath = useStore((state) => state.tubPath);
  // TM 并入统一流程大页面（#178）：section 在视口内（active）时才响应全局快捷键
  const isTubManagerActive = active;
  const setTub = useStore((state) => state.setTub);
  const config = useStore((state) => state.config);
  const isLoading = useStore((state) => state.isLoading);
  const requestTubRefresh = useStore((state) => state.requestTubRefresh);
  const setCurrentIndex = useStore((state) => state.setCurrentIndex);
  const setActiveSession = useStore((state) => state.setActiveSession);
  const driveLoopHz = Number(config?.DRIVE_LOOP_HZ) || 60;

  const [sessions, setSessions] = useState<FamilyTubSession[]>([]);
  // 录制为空（如全部被软删）时由 /tub/family_sessions 附带的子 tub 列表，用于引导切换
  const [childTubs, setChildTubs] = useState<ChildTubInfo[]>([]);
  const [switchingChildPath, setSwitchingChildPath] = useState<string | null>(null);
  // 异 tub 会话切换中（目标行的复合键，该行转圈/禁用）
  const [switchingSessionKey, setSwitchingSessionKey] = useState<string | null>(null);
  const [selected, setSelected] = useState<FamilyTubSession | null>(null);
  // 多选会话筛选集合（(tub_path, session_id) 复合键）：size 0 = 空视图，
  // 1 = 单选，>1 = 多选（锚点 = selected，即最后点击行）。shift 范围选锚点
  // 也复用 selected，不另设 ref（单一事实来源）
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [records, setRecords] = useState<TubRecord[]>([]);
  const [frame, setFrame] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<FamilyTubSession | null>(null);
  // 批量删除确认弹窗开关（selectedKeys.size > 1 时「删除所选」进入）
  const [pendingBatchDelete, setPendingBatchDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [imageError, setImageError] = useState(false);
  const [frameAspect, setFrameAspect] = useState<number | null>(null);
  const [pinned, setPinned] = useState<string[]>([]);
  const [actualFps, setActualFps] = useState(0);
  const [aiCleanOpen, setAiCleanOpen] = useState(false);
  // 手动刷新进行中（按钮转圈/禁用）；refreshEpoch 递增使帧图片 URL 变化，
  // 绕过浏览器对 /tub/image 的 HTTP 缓存（max-age=86400）
  const [refreshing, setRefreshing] = useState(false);
  const [refreshEpoch, setRefreshEpoch] = useState(0);
  const refreshingRef = useRef(false);
  const lastRefreshRef = useRef<number>(Date.now());

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageCacheRef = useRef<Map<string, HTMLImageElement>>(new Map());
  const rafRef = useRef<number>();
  // 墙钟播放基准：进入播放的首个 tick 记录起点时间与起点帧
  const playStartTimeRef = useRef<number>(0);
  const playStartFrameRef = useRef<number>(0);
  const frameRef = useRef(0);
  const isPlayingRef = useRef(false);
  const recordsRef = useRef(records);
  const selectedRef = useRef<FamilyTubSession | null>(null);
  // 多选集合的 ref 镜像：refreshSessions/softRefresh/hardRefresh 等回调依赖
  // selectedKeys 最新值但不把它列进 deps（避免集合每次变化重建回调）
  const selectedKeysRef = useRef<Set<string>>(selectedKeys);
  // 用户手动清空选择（取消到最后空集合）后置位：本次工作 tub 内抑制
  // refreshSessions 的自动重选（否则 30s 轮询又把 items[0] 选回来）
  const userClearedSelectionRef = useRef(false);
  // 异 tub 选中的目标复合键：loadTub+setTub 触发 tubPath 变化 → 列表重拉后
  // 按此键匹配并选中（而非回落到「选最新」）
  const pendingSelectKeyRef = useRef<string | null>(null);
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
        img.onload = () => {
          // 预解码（60fps）：帧到期前完成 JPEG 解码，drawImage 不再触发主线程同步解码
          img.decode?.().catch(() => {});
          inFlight -= 1;
          pump();
        };
        img.onerror = () => {
          inFlight -= 1;
          pump();
        };
        touchImageCache(url, img);
        img.src = url;
      }
    };
    pump();
  }, [touchImageCache]);

  const pinnedSet = useMemo(() => new Set(pinned), [pinned]);
  // 置顶在前、其余保持 API 最新在前的顺序。多选合并/范围选都以此顺序为准，
  // 定义靠前的回调（记录加载 effect/刷新路径）也依赖它
  const sortedSessions = useMemo(() => {
    const pinnedItems = sessions.filter((s) => pinnedSet.has(sessionKey(s)));
    const rest = sessions.filter((s) => !pinnedSet.has(sessionKey(s)));
    return [...pinnedItems, ...rest];
  }, [sessions, pinnedSet]);

  // sortedSessions 的 ref 镜像：记录加载 effect 需要按它合并多选帧，但绝不能把它
  // 列进 effect deps——否则录制列表一刷新（setSessions 重建 memo）就重拉当前选中帧。
  // 本 effect 声明在记录加载 effect 之前，同一次 commit 里先同步 ref 再跑加载
  const sortedSessionsRef = useRef(sortedSessions);
  useEffect(() => {
    sortedSessionsRef.current = sortedSessions;
  }, [sortedSessions]);

  // 多选合并结果的编辑器挂接（按 tub 去重判定）：集合收敛单 tub 且即当前全局
  // tub → 挂会话作用域（锚点 sid + 合并 records + ids）；跨 tub（编辑器逐 tub
  // 编辑）或单 tub 非当前全局 → 回退整 tub 视图。各刷新路径写回都走这里
  const commitMergedSelection = useCallback(
    (anchorSessionId: string | null, ordered: FamilyTubSession[], merged: TubRecord[]) => {
      const uniqueTubs = [...new Set(ordered.map((s) => s.tub_path))];
      if (uniqueTubs.length === 1 && uniqueTubs[0] === tubPath) {
        setActiveSession(
          anchorSessionId,
          merged as StoreTubRecord[],
          ordered.map((s) => s.session_id),
        );
      } else {
        setActiveSession(null, []);
      }
    },
    [tubPath, setActiveSession],
  );

  // 全局工作 tub 切换（复用 pendingSelectKeyRef 机制）：切换发起时保留当前
  // selected/selectedKeys（tubPath 变化 effect 识别 pending 非空不清空），
  // refreshSessions 按 pending 键命中锚点后由选中 effect 重新挂接。
  // 单 tub 多选/单选挂接编辑器、普通点击跨 tub 都走这里。
  const switchWorkingTub = useCallback(
    (targetTubPath: string, anchor: FamilyTubSession) => {
      pendingSelectKeyRef.current = sessionKey(anchor);
      setSwitchingSessionKey(sessionKey(anchor));
      setError(null);
      loadTub(targetTubPath)
        .then((data) => {
          setTub(
            data.path,
            data.records || [],
            data.fields || [],
            data.total_physical_records,
            data.deleted_indexes,
          );
        })
        .catch((err) => {
          pendingSelectKeyRef.current = null;
          setError(getApiErrorMessage(err, t('tubLibrary.loadFailed')));
        })
        .finally(() => setSwitchingSessionKey(null));
    },
    [setTub, t],
  );

  // 统一选中入口（家族视图核心语义）：同 tub 会话直接选中；异 tub 会话先切
  // 全局工作 tub 再选中——编辑器删除/恢复只作用于全局 current_tub，选中即切换避免打错 tub。
  // 切换期间目标行转圈；失败保持原选中。不直接 setSelected：setTub 触发 tubPath 变化 →
  // refreshSessions 重拉家族列表，按 pendingSelectKeyRef 匹配后选中（家族列表与 tub
  // 无关，目标必然命中）。单选会折叠多选集合：普通点击/删除后自动重选都经此入口，
  // 集合随之重置为仅目标行（多选手势见 handleRowClick/toggleKey/rangeSelectTo）
  const applySelection = useCallback((session: FamilyTubSession | null) => {
    userClearedSelectionRef.current = false;
    if (!session) {
      setSelected(null);
      setSelectedKeys(new Set());
      return;
    }
    if (session.tub_path === tubPath) {
      setSelected(session);
      setSelectedKeys(new Set([sessionKey(session)]));
      return;
    }
    // 异 tub：清空旧多选集合，退化为该行单选（pending 命中后再落 {目标}）
    setSelectedKeys(new Set());
    switchWorkingTub(session.tub_path, session);
  }, [tubPath, switchWorkingTub]);

  const refreshSessions = useCallback(async (path: string): Promise<{
    items: FamilyTubSession[];
    target: FamilyTubSession | null;
  }> => {
    setError(null);
    try {
      const data = await listFamilyTubSessions(path);
      const items = data.sessions || [];
      lastRefreshRef.current = Date.now();
      setSessions(items);
      // 录制为空（如全部被软删）时后端附带子 tub 列表，供「切换目录」引导；
      // 录制非空时清空，避免残留旧目录的引导数据
      setChildTubs(items.length === 0 ? data.child_tubs || [] : []);
      // 自动选择：异 tub 切换的 pending 目标 > 维持当前选中 > 最新一条。
      // 选中一律经 applySelection——最新一条可能属于其它家族成员 tub，
      // 按核心语义先切全局工作 tub 再选中。
      const pendingKey = pendingSelectKeyRef.current;
      if (pendingKey) {
        const match = items.find((s) => sessionKey(s) === pendingKey);
        if (match && match.tub_path === path) {
          pendingSelectKeyRef.current = null;
          setSelected(match);
          if (selectedKeysRef.current.size <= 1) {
            setSelectedKeys(new Set([sessionKey(match)]));
          }
          // 多选发起的切换：集合 >1 时保留（成员本就都属于新 tub），挂接由选中 effect 完成
          userClearedSelectionRef.current = false;
          return { items, target: match };
        }
        pendingSelectKeyRef.current = null;
        if (match) {
          // 列表已含目标但当前工作 tub 还不是它（切换被中途刷新打断）：重走切换
          applySelection(match);
          return { items, target: match };
        }
        // 目标会话已不在家族列表里（切换期间被删）：落到常规逻辑
      }
      const prev = selectedRef.current;
      if (prev && items.some((s) => sessionKey(s) === sessionKey(prev))) {
        return { items, target: prev };
      }
      if (userClearedSelectionRef.current) {
        // 用户已手动清空选择：保持空集合，不自动重选最新一条（30s 轮询也不选回）
        return { items, target: null };
      }
      const target = items[0] ?? null;
      applySelection(target);
      return { items, target };
    } catch (err) {
      setSessions([]);
      setChildTubs([]);
      setError(getApiErrorMessage(err, t('tubLibrary.loadFailed')));
      return { items: [], target: null };
    }
  }, [applySelection, t]);

  // 子 tub 引导面板点击：加载该子 tub 并切换全局 tubPath，
  // 后续列表/帧重拉由 tubPath 变化的 effect 自动完成
  const switchToChildTub = useCallback(async (child: ChildTubInfo) => {
    setSwitchingChildPath(child.path);
    setError(null);
    try {
      const data = await loadTub(child.path);
      setTub(
        data.path,
        data.records || [],
        data.fields || [],
        data.total_physical_records,
        data.deleted_indexes,
      );
    } catch (err) {
      setError(getApiErrorMessage(err, t('tubLibrary.loadFailed')));
    } finally {
      setSwitchingChildPath(null);
    }
  }, [setTub, t]);

  useEffect(() => {
    recordsRef.current = records;
  }, [records]);

  useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);

  useEffect(() => {
    selectedKeysRef.current = selectedKeys;
  }, [selectedKeys]);

  // 手动刷新纪元：刷新后帧图片 URL 追加 &r=<epoch>。后端 /tub/image 带
  // max-age=86400，同一 tub 路径重建后同名帧文件会命中浏览器旧图——
  // 换 URL 强制绕过 HTTP 缓存，保证「刷新后看到新数据」。
  // recordTubPath：跨 tub 多选合并的帧自带 __tubPath 标，取图按标走（默认当前全局 tub）
  const imageUrlWithEpoch = useCallback(
    (path: string, recordTubPath?: string) => {
      const url = getImageUrl(path, recordTubPath ?? tubPath);
      return refreshEpoch > 0 ? `${url}&r=${refreshEpoch}` : url;
    },
    [tubPath, refreshEpoch],
  );

  // 预计算所有帧的图片 URL，避免播放循环每帧重复调用 getImageUrl()。
  // 合并 records 的 __tubPath 标让跨 tub 帧取到各自 tub 的图（URL 含 tubPath 查询参，
  // 图片缓存 key=URL 天然按 tub 隔离，不串图）
  useEffect(() => {
    imageUrlsRef.current = records.map((r) => {
      const path = findImagePath(r);
      const recordTub = (r['__tubPath'] as string | undefined) ?? tubPath;
      return path ? imageUrlWithEpoch(path, recordTub) : '';
    });
  }, [records, imageUrlWithEpoch, tubPath]);

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
    // 自己发起的全局 tub 切换（pendingSelectKeyRef 非空：单 tub 多选挂接/单选跨 tub）：
    // 保留锚点与集合（成员本就都属于新 tub），切换落定后由 refreshSessions 的
    // pending 命中 + 选中 effect 重新拉取挂接；其余 tubPath 变化（加载器/子 tub
    // 引导）照旧清空选中
    const keepSelection = pendingSelectKeyRef.current != null;
    if (!keepSelection) {
      setSelected(null);
      // 同步清 ref：refreshSessions 在本 effect 内立即执行，异步 setSelected(null)
      // 还没提交，不清的话自动选择会把旧 tub 的选中当成「维持当前」
      selectedRef.current = null;
      setSelectedKeys(new Set());
      selectedKeysRef.current = new Set();
      userClearedSelectionRef.current = false;
    }
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
      setChildTubs([]);
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
      // 空集合（含用户手动清空）：编辑器回退整 tub 视图，播放区显示 selectHint
      setActiveSession(null, []);
      return;
    }

    // 单选守卫：异 tub 跳过只在 size<=1 时生效——普通点击跨 tub 切换提交前 selected
    // 还是旧 tub 会话，拉帧会拿新 tub 路径配旧会话 id（撞名还会拉到错画面）；
    // 多选（允许跨 tub）不受此限，按各会话自己的 tub_path 拉取
    if (selectedKeys.size <= 1 && selected.tub_path !== tubPath) {
      if (pendingSelectKeyRef.current == null) {
        // 无切换在进行（多选收敛/取消选择后的单 tub 单选）：切过去挂接编辑器
        switchWorkingTub(selected.tub_path, selected);
      }
      setActiveSession(null, []);
      return;
    }

    let cancelled = false;
    if (selectedKeys.size <= 1) {
      // 0/1：单会话路径（既有行为）
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
    } else {
      // N：多选（允许跨 tub）——成员按 start_time_ms 升序（连续录制时间序）。
      // 收敛单 tub 且非当前全局：发起切换并保留集合，落定后本 effect 重跑再拉取挂接；
      // 其余情况直接按各会话自己的 tub_path 并发拉取合并（帧带 __tubPath 标，
      // 播放器播合并序列），编辑器挂接由 commitMergedSelection 按 tub 去重判定
      const ordered = orderByStartTimeAsc(
        sortedSessionsRef.current.filter((s) => selectedKeys.has(sessionKey(s))),
      );
      const uniqueTubs = [...new Set(ordered.map((s) => s.tub_path))];
      if (uniqueTubs.length === 1 && uniqueTubs[0] !== tubPath) {
        if (pendingSelectKeyRef.current == null) {
          switchWorkingTub(uniqueTubs[0], selected);
        }
        setActiveSession(null, []);
        return () => {
          cancelled = true;
        };
      }
      (async () => {
        try {
          const merged = await fetchMergedSessionRecords(ordered);
          if (cancelled) return;
          setRecords(merged);
          commitMergedSelection(selected.session_id, ordered, merged);
        } catch (err) {
          if (!cancelled) {
            setError(getApiErrorMessage(err, t('tubLibrary.loadFailed')));
          }
        }
      })();
    }
    return () => {
      cancelled = true;
    };
    // sortedSessions 经 sortedSessionsRef 读取（见该 ref 注释），不进 deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, selectedKeys, tubPath, t, setActiveSession, switchWorkingTub, commitMergedSelection]);

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
  // 跨 tub 多选：当前帧可能来自其它 tub 的会话（records 带 __tubPath 标）
  const currentRecordTubPath = useMemo(
    () => (currentRecord?.['__tubPath'] as string | undefined) ?? tubPath,
    [currentRecord, tubPath],
  );

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
      ctx.fillStyle = cssVarColor('--surface', theme === 'light' ? '#f4f6f9' : '#18181b');
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      setFrameAspect(null);
      return;
    }

    const url = imageUrlWithEpoch(currentImagePath, currentRecordTubPath);
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
  }, [currentImagePath, currentRecordTubPath, imageUrlWithEpoch, theme, touchImageCache]);

  // Playback loop: wall-clock scheduled — position derives from elapsed time
  // (start frame + elapsed/frameInterval), each rAF tick draws the newest
  // ready frame up to the wall-clock target instead of stalling on a frame
  // that hasn't loaded yet; React state updates stay throttled (#128, 60fps).
  useEffect(() => {
    if (!isPlaying || !records.length) return;

    // 播放启动时立即预取前 PREFETCH_AHEAD 帧——否则播放循环在帧 1 图片未加载时
    // 死循环不推进（预取只在帧推进后才触发，形成死锁）。
    prefetchFromIndex(frameRef.current);

    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');

    const step = (time: number) => {
      if (!isPlayingRef.current) return;
      if (playStartTimeRef.current === 0) {
        playStartTimeRef.current = time;
        playStartFrameRef.current = frameRef.current;
        fpsStartRef.current = time;
      }
      const total = records.length;
      const prevFrame = frameRef.current;
      // 墙钟目标帧：起点帧 + 经过时间对应的帧数
      let target =
        playStartFrameRef.current +
        Math.floor((time - playStartTimeRef.current) / frameInterval);
      if (target > total - 1) target = total - 1;
      const lag = target - prevFrame;
      if (lag > MAX_RESUME_LAG_FRAMES) {
        // 长停顿（切后台/网络卡死）：从当前帧重新对表，不追帧不快进
        playStartFrameRef.current = prevFrame;
        playStartTimeRef.current = time;
        target = prevFrame + 1;
      }
      let next = prevFrame;
      if (target > prevFrame) {
        // 窗口内取最后一个可画帧（中间未 ready/损坏的帧跳过，不停摆）
        const windowEnd = Math.min(prevFrame + MAX_CATCHUP_FRAMES, target);
        let drawIndex = -1;
        for (let i = prevFrame + 1; i <= windowEnd; i += 1) {
          const url = imageUrlsRef.current[i];
          const img = url ? imageCacheRef.current.get(url) : undefined;
          if (img && img.complete && img.naturalWidth > 0) drawIndex = i;
        }
        if (drawIndex >= 0) {
          const img = imageCacheRef.current.get(imageUrlsRef.current[drawIndex]);
          if (img && canvas && ctx) {
            // 直接画到 canvas，不触发 React re-render
            if (canvas.width !== img.width || canvas.height !== img.height) {
              canvas.width = img.width;
              canvas.height = img.height;
            }
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(img, 0, 0);
          }
          next = drawIndex;
          // FPS 按实际换帧数累计（#128），画面冻结时角标跟随下降
          fpsFramesRef.current += 1;
        }
        // 窗口内没有任何可画帧：停在当前帧等下一轮（网络抖动自愈）
        frameRef.current = next;

        // 预取节流 + 节流 UI 状态更新（帧计数器、进度条、统计、全局 index 联动）
        if (
          Math.floor(next / UI_UPDATE_EVERY_N_FRAMES) !==
            Math.floor(prevFrame / UI_UPDATE_EVERY_N_FRAMES) ||
          next >= total - 1
        ) {
          prefetchFromIndex(next);
          setFrame(next);
        }

        // FPS 按实际换帧数累计（#128），画面冻结时角标跟随下降
        if (time - fpsStartRef.current >= 1000) {
          setActualFps(Math.round((fpsFramesRef.current * 1000) / (time - fpsStartRef.current)));
          fpsStartRef.current = time;
          fpsFramesRef.current = 0;
        }
      }
      if (next >= total - 1 && target >= total - 1) {
        // 到尾：停止播放（最后一帧拿不到也停，不死等缺帧）
        setIsPlaying(false);
        setFrame(next);
        return;
      }
      rafRef.current = requestAnimationFrame(step);
    };

    playStartTimeRef.current = 0;
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current !== undefined) cancelAnimationFrame(rafRef.current);
    };
  }, [isPlaying, records, frameInterval, prefetchFromIndex]);

  // 空格键播放/暂停（原 Tub 导航器快捷键；输入框内不触发；TM 页切走时不响应）
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code !== 'Space') return;
      if (!isTubManagerActive) return;
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
  }, [isTubManagerActive]);

  // 切走时自动停止回放，避免常驻保活后后台持续拉帧占资源
  useEffect(() => {
    if (!isTubManagerActive) {
      isPlayingRef.current = false;
      setIsPlaying(false);
    }
  }, [isTubManagerActive]);

  const jumpToFrame = useCallback((idx: number) => {
    setIsPlaying(false);
    frameRef.current = idx;
    setFrame(idx);
  }, []);

  const handleDownload = useCallback((session: FamilyTubSession) => {
    const key = sessionKey(session);
    setDownloadingId(key);
    setError(null);
    try {
      downloadTubSession(session.tub_path, session.session_id, session.start_time_ms);
    } catch (err) {
      setError(getApiErrorMessage(err, t('tubLibrary.downloadFailed')));
    }
    // The browser handles the actual download natively (progress bar etc.)
    setTimeout(() => setDownloadingId((prev) => (prev === key ? null : prev)), 1000);
  }, [t]);

  const confirmDelete = useCallback(async () => {
    if (!pendingDelete || !tubPath) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteTubSession(pendingDelete.tub_path, pendingDelete.session_id);
      setPendingDelete(null);
      // 多选集合同步剔除被删行（集合大小变化交给选中 effect 收敛；
      // 锚点被删则清空 selected，列表刷新后走自动选择）
      const deletedRowKey = sessionKey(pendingDelete);
      setSelectedKeys((prev) => {
        if (!prev.has(deletedRowKey)) return prev;
        const next = new Set(prev);
        next.delete(deletedRowKey);
        return next;
      });
      if (selected && sessionKey(selected) === deletedRowKey) {
        setSelected(null);
      }
      // Drop the deleted clip from the pinned set too
      const deletedKey = sessionKey(pendingDelete);
      setPinned((prev) => {
        if (!prev.includes(deletedKey)) return prev;
        const next = prev.filter((id) => id !== deletedKey);
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

  // AI 清理执行成功后：刷新录制列表、当前选中录制的帧与全局 tub，
  // 让各面板立即丢弃被删帧（与整条删除后的同步逻辑一致）
  const refreshAfterAiClean = useCallback(async () => {
    if (!tubPath) return;
    await refreshSessions(tubPath);
    if (selectedKeysRef.current.size > 1 && selected) {
      // 多选（允许跨 tub）：AI 清理可能删了任一会话的帧，按 time-asc 重拉合并写回
      const ordered = orderByStartTimeAsc(
        sortedSessions.filter((s) => selectedKeysRef.current.has(sessionKey(s))),
      );
      try {
        const merged = await fetchMergedSessionRecords(ordered);
        setRecords(merged);
        commitMergedSelection(selected.session_id, ordered, merged);
        setFrame(0);
        frameRef.current = 0;
      } catch {
        // 会话级刷新尽力而为：全局 tub 仍会刷新
      }
    } else if (selected) {
      try {
        const data = await getSessionRecords(tubPath, selected.session_id);
        setRecords(data.records || []);
        setActiveSession(selected.session_id, (data.records || []) as StoreTubRecord[]);
        setFrame(0);
        frameRef.current = 0;
      } catch {
        // 会话级刷新尽力而为：全局 tub 仍会刷新
      }
    }
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
  }, [tubPath, selected, refreshSessions, setTub, setActiveSession, sortedSessions, commitMergedSelection]);

  // 手动「刷新」（用户报障：常驻挂载下录制列表与选中帧长期停留在旧快照，
  // 新老数据混在一起）：清空浏览器内暂存的数据后全量重拉——录制列表、当前
  // 选中录制的帧、全局 tub（编辑器等面板同步），并递增图片 URL 纪元绕过
  // 浏览器 HTTP 缓存（/tub/image 带 max-age=86400）。选中目标由
  // refreshSessions 的自动选择落定（同 tub 直接选中；异 tub 触发切换，
  // 帧随后由选中 effect 重拉），这里只同步选中帧与全局 tub。
  const hardRefresh = useCallback(async () => {
    if (!tubPath || refreshingRef.current) return;
    refreshingRef.current = true;
    setRefreshing(true);
    // 停止播放并清空内存帧缓存，避免旧图继续贴在画面上
    isPlayingRef.current = false;
    setIsPlaying(false);
    imageCacheRef.current.clear();
    setRefreshEpoch((e) => e + 1);
    setError(null);
    try {
      const { target } = await refreshSessions(tubPath);

      // 预拉帧：多选（允许跨 tub）时按 time-asc 顺序并发拉集合内全部会话合并；
      // 否则目标属于当前 tub 才预拉单会话帧（异 tub 目标的帧由切换后的选中 effect 拉取）
      let nextRecords: TubRecord[] | null = null;
      let nextSessionId: string | null = null;
      let nextOrdered: FamilyTubSession[] | null = null;
      if (selectedKeysRef.current.size > 1 && selected) {
        const ordered = orderByStartTimeAsc(
          sortedSessions.filter((s) => selectedKeysRef.current.has(sessionKey(s))),
        );
        if (ordered.length > 1) {
          try {
            nextRecords = await fetchMergedSessionRecords(ordered);
            nextSessionId = selected.session_id;
            nextOrdered = ordered;
          } catch {
            // 会话级刷新尽力而为：列表已更新，下方全局 tub 仍会刷新
          }
        }
      }
      if (nextRecords === null && target && target.tub_path === tubPath) {
        try {
          const data = await getSessionRecords(target.tub_path, target.session_id);
          nextRecords = data.records || [];
          nextSessionId = target.session_id;
        } catch {
          // 会话级刷新尽力而为：列表已更新，下方全局 tub 仍会刷新
        }
      }
      // 全局 tub 同步（与整条删除后的逻辑一致）；setTub 会清空 activeSession，
      // 因此必须在 setTub 之后重新写入 activeSession
      try {
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
      if (nextRecords !== null) {
        setRecords(nextRecords);
        if (nextOrdered) {
          commitMergedSelection(nextSessionId, nextOrdered, nextRecords);
        } else {
          setActiveSession(nextSessionId, nextRecords as StoreTubRecord[]);
        }
      }
      setFrame(0);
      frameRef.current = 0;
      setImageError(false);
    } catch (err) {
      setError(getApiErrorMessage(err, t('tubLibrary.loadFailed')));
    } finally {
      refreshingRef.current = false;
      setRefreshing(false);
    }
  }, [tubPath, selected, refreshSessions, setTub, setActiveSession, sortedSessions, commitMergedSelection, t]);

  // 自动刷新（静默）：只重拉录制列表；当前选中录制有新增帧且未在播放时，
  // 一并静默重拉其帧并保持当前帧位置。不动图片缓存、不递增纪元，
  // 避免周期性全量重载拖慢页面。
  const softRefresh = useCallback(async () => {
    if (!tubPath || refreshingRef.current || isPlayingRef.current) return;
    if (switchingSessionKey) return; // 异 tub 切换中，避免旧 tub 轮询打断
    try {
      const { items } = await refreshSessions(tubPath);
      if (!isPlayingRef.current && selectedKeysRef.current.size > 1 && selected) {
        // 多选（允许跨 tub）：逐会话比较 record_count（旧列表 vs 新列表），
        // 任一变化则按 time-asc 重拉合并并保持当前帧位置
        const members = sessions.filter((s) => selectedKeysRef.current.has(sessionKey(s)));
        const changed = members.some((s) => {
          const fresh = items.find((i) => sessionKey(i) === sessionKey(s));
          return !fresh || fresh.record_count !== s.record_count;
        });
        if (changed && members.length > 1) {
          const ordered = orderByStartTimeAsc(
            sortedSessions.filter((s) => selectedKeysRef.current.has(sessionKey(s))),
          );
          try {
            const next = await fetchMergedSessionRecords(ordered);
            setRecords(next);
            commitMergedSelection(selected.session_id, ordered, next);
            frameRef.current = Math.min(frameRef.current, Math.max(0, next.length - 1));
            setFrame(frameRef.current);
          } catch {
            // 会话级刷新尽力而为：轮询失败不打断用户操作
          }
        }
        return;
      }
      if (
        selected &&
        !isPlayingRef.current &&
        items.some((s) => sessionKey(s) === sessionKey(selected))
      ) {
        const current = items.find((s) => sessionKey(s) === sessionKey(selected));
        if (current && current.record_count !== selected.record_count) {
          const data = await getSessionRecords(selected.tub_path, selected.session_id);
          const next = data.records || [];
          setRecords(next);
          setActiveSession(selected.session_id, next as StoreTubRecord[]);
          frameRef.current = Math.min(frameRef.current, Math.max(0, next.length - 1));
          setFrame(frameRef.current);
        }
      }
    } catch {
      // refreshSessions 内部已 setError；轮询失败不打断用户操作
    }
  }, [tubPath, selected, sessions, switchingSessionKey, refreshSessions, setActiveSession, sortedSessions, commitMergedSelection]);

  // 自动刷新调度：TM section 激活期间每 30s 检查一次；播放中与浏览器后台
  // 标签页暂停；激活（滚回视口/切回标签页）时数据已过期则立即补一次。
  useEffect(() => {
    if (!isTubManagerActive || !tubPath) return;
    const tick = () => {
      if (document.hidden) return;
      if (isPlayingRef.current) return;
      if (Date.now() - lastRefreshRef.current < AUTO_REFRESH_INTERVAL_MS) return;
      void softRefresh();
    };
    tick();
    const timer = window.setInterval(tick, AUTO_REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [isTubManagerActive, tubPath, softRefresh]);

  const hasRecords = records.length > 0;

  // 统一总帧数口径：列表头合计显示所有录制的有效帧之和（record_count 为迭代
  // 跳过软删除后的有效帧数），与 Tub 编辑器的有效帧数对齐
  const totalFrameCount = useMemo(
    () => sessions.reduce((sum, s) => sum + s.record_count, 0),
    [sessions],
  );

  // Pinned clips float to the top; both groups keep the API's newest-first order.
  // 置顶集合同步换成复合键（tub_path::session_id），旧的裸 session_id 条目
  // 自然失效（可接受：点击一次即重新置顶）
  const togglePin = (session: FamilyTubSession) => {
    if (!tubPath) return;
    const key = sessionKey(session);
    setPinned((prev) => {
      const next = prev.includes(key)
        ? prev.filter((id) => id !== key)
        : [...prev, key];
      savePinned(tubPath, next);
      return next;
    });
  };

  // ---- 多选会话筛选（家族视图）----
  // 集合允许跨 tub（真实数据一段会话一个兄弟 tub，「一整套连续录制」天然跨 tub）；
  // 多选手势不切换全局 tub，编辑器作用域只在集合收敛单 tub 且即当前全局 tub 时挂接。
  // 锚点语义：selected 即「最后点击行」，shift 范围选也以此为起点。

  // ctrl/⌘/checkbox 切换：加入/移出集合（允许跨 tub，手势不切换全局 tub）；
  // 维护锚点——加入则锚点移到该行，移除锚点行则锚点回最近添加的剩余成员
  // （Set 迭代序即插入序），取消到空集合时置 userClearedSelectionRef 抑制自动重选。
  // 切换进行中（pending 非空）锚点变化要同步 pending 键，否则切换落定后
  // refreshSessions 按旧锚点命中，把用户后点的锚点覆盖回去
  const toggleKey = useCallback(
    (session: FamilyTubSession) => {
      const key = sessionKey(session);
      userClearedSelectionRef.current = false;
      const next = new Set(selectedKeys);
      let nextAnchor: FamilyTubSession | null = selected;
      if (next.has(key)) {
        next.delete(key);
        if (next.size === 0) {
          nextAnchor = null;
          userClearedSelectionRef.current = true;
        } else if (selected && sessionKey(selected) === key) {
          const rest = Array.from(next);
          nextAnchor =
            sessions.find((s) => sessionKey(s) === rest[rest.length - 1]) ?? null;
        }
        // 移出非锚点行：锚点不动
      } else {
        next.add(key);
        nextAnchor = session;
      }
      setSelected(nextAnchor);
      setSelectedKeys(next);
      if (pendingSelectKeyRef.current != null) {
        pendingSelectKeyRef.current = nextAnchor ? sessionKey(nextAnchor) : null;
      }
    },
    [selected, sessions, selectedKeys],
  );

  // shift 范围选：锚点行到目标行按 sortedSessions 全列表取闭区间（允许跨 tub），
  // 锚点移到目标行；无锚点（空集合后）退化为目标行单选。切换进行中同步 pending 键
  const rangeSelectTo = useCallback(
    (session: FamilyTubSession) => {
      userClearedSelectionRef.current = false;
      const key = sessionKey(session);
      if (!selected) {
        setSelected(session);
        setSelectedKeys(new Set([key]));
        if (pendingSelectKeyRef.current != null) {
          pendingSelectKeyRef.current = key;
        }
        return;
      }
      const keys = sortedSessions.map(sessionKey);
      const from = keys.indexOf(sessionKey(selected));
      const to = keys.indexOf(key);
      if (from === -1 || to === -1) {
        setSelected(session);
        setSelectedKeys(new Set([key]));
        if (pendingSelectKeyRef.current != null) {
          pendingSelectKeyRef.current = key;
        }
        return;
      }
      const [lo, hi] = from <= to ? [from, to] : [to, from];
      setSelected(session);
      setSelectedKeys(new Set(keys.slice(lo, hi + 1)));
      if (pendingSelectKeyRef.current != null) {
        pendingSelectKeyRef.current = key;
      }
    },
    [selected, sortedSessions],
  );

  // 行点击分流：普通=单选（折叠集合，必要时跨 tub 切换）；ctrl/⌘=切换；
  // shift=范围选。多选手势一律不切换全局 tub（切换只在挂接编辑器时发生）
  const handleRowClick = useCallback(
    (session: FamilyTubSession, e: React.MouseEvent) => {
      if (e.ctrlKey || e.metaKey) {
        toggleKey(session);
        return;
      }
      if (e.shiftKey) {
        rangeSelectTo(session);
        return;
      }
      applySelection(session);
    },
    [applySelection, rangeSelectTo, toggleKey],
  );

  // 批量操作条「取消」：清空多选集合，保留锚点单选；锚点在异 tub 时顺手切过去挂接
  const clearMultiSelection = useCallback(() => {
    if (!selected) return;
    setSelectedKeys(new Set([sessionKey(selected)]));
    if (selected.tub_path !== tubPath) {
      switchWorkingTub(selected.tub_path, selected);
    }
  }, [selected, tubPath, switchWorkingTub]);

  // 多选成员（start_time_ms 升序 = 连续录制时间序，允许跨 tub）：
  // 批量操作条统计与批量删除顺序都以此为准
  const orderedSelectedSessions = useMemo(
    () => orderByStartTimeAsc(sortedSessions.filter((s) => selectedKeys.has(sessionKey(s)))),
    [sortedSessions, selectedKeys],
  );
  const selectedFrameCount = useMemo(
    () => orderedSelectedSessions.reduce((sum, s) => sum + s.record_count, 0),
    [orderedSelectedSessions],
  );
  // 跨 tub 选择：编辑器逐 tub 编辑（不挂会话作用域），操作条给出提示
  const isCrossTubSelection = useMemo(
    () => new Set(orderedSelectedSessions.map((s) => s.tub_path)).size > 1,
    [orderedSelectedSessions],
  );

  // 批量删除：确认弹窗后按 start_time_ms 升序逐条删除（每行自带 tub_path，
  // 天然支持跨 tub；顺序删避免 manifest 并发写），单次 refreshSessions 同步，
  // 全局 tub 在被删集合里才 loadTub，最后清空集合走自动选择
  const confirmBatchDelete = useCallback(async () => {
    if (!tubPath || orderedSelectedSessions.length < 2) return;
    setDeleting(true);
    setError(null);
    try {
      const deletedKeys = new Set(orderedSelectedSessions.map(sessionKey));
      const includesWorkingTub = orderedSelectedSessions.some((s) => s.tub_path === tubPath);
      for (const s of orderedSelectedSessions) {
        await deleteTubSession(s.tub_path, s.session_id);
      }
      setPendingBatchDelete(false);
      setSelectedKeys(new Set());
      if (selected && deletedKeys.has(sessionKey(selected))) {
        setSelected(null);
      }
      // 被删会话同时从置顶集合剔除
      setPinned((prev) => {
        const next = prev.filter((k) => !deletedKeys.has(k));
        savePinned(tubPath, next);
        return next;
      });
      await refreshSessions(tubPath);
      // 全局 tub 在被删集合里才同步（编辑器等面板丢弃被删帧）
      if (includesWorkingTub) {
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
      }
    } catch (err) {
      setError(getApiErrorMessage(err, t('tubLibrary.deleteFailed')));
    } finally {
      setDeleting(false);
    }
  }, [tubPath, orderedSelectedSessions, selected, refreshSessions, setTub, t]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <SectionCardTitle
            icon={<Clapperboard className="w-5 h-5" />}
            title={t('tubLibrary.title')}
            subtitle={t('tubLibrary.subtitle')}
          />
          <div className="flex items-center gap-2 shrink-0">
            <Button
              size="sm"
              variant="secondary"
              disabled={!tubPath || refreshing}
              aria-label={t('tubLibrary.refreshAria')}
              title={t('tubLibrary.refreshTitle')}
              onClick={() => void hardRefresh()}
            >
              <RotateCcw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
              <span className="text-xs">
                {refreshing ? t('tubLibrary.refreshing') : t('tubLibrary.refresh')}
              </span>
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={!tubPath}
              aria-label={t('aiClean.entryAria')}
              title={t('aiClean.entryAria')}
              onClick={() => setAiCleanOpen(true)}
            >
              <Sparkles className="w-4 h-4" />
              <span className="text-xs">{t('aiClean.entry')}</span>
            </Button>
          </div>
        </div>
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
              <div className="flex items-center justify-between mb-2 gap-2">
                <span
                  className="text-xs text-zinc-400"
                  title={t('tubLibrary.multiSelectHint')}
                >
                  {t('tubLibrary.recordingsSummary', {
                    recordings: sessions.length,
                    count: totalFrameCount,
                  })}
                </span>
                {selectedKeys.size > 1 && (
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-cyan-400 whitespace-nowrap">
                        {t('tubLibrary.selectedSummary', {
                          segments: selectedKeys.size,
                          count: selectedFrameCount,
                        })}
                      </span>
                      <Button
                        size="sm"
                        variant="danger"
                        disabled={deleting}
                        aria-label={t('tubLibrary.deleteSelected')}
                        title={t('tubLibrary.deleteSelected')}
                        onClick={() => setPendingBatchDelete(true)}
                      >
                        <Trash2 className="w-4 h-4" />
                        <span className="text-xs">{t('tubLibrary.deleteSelected')}</span>
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        aria-label={t('tubLibrary.clearSelection')}
                        title={t('tubLibrary.clearSelection')}
                        onClick={clearMultiSelection}
                      >
                        <span className="text-xs">{t('tubLibrary.clearSelection')}</span>
                      </Button>
                    </div>
                    {isCrossTubSelection && (
                      <span className="text-[11px] text-amber-400/90 whitespace-nowrap">
                        {t('tubLibrary.crossTubHint')}
                      </span>
                    )}
                  </div>
                )}
              </div>
              {error && (
                <div className="flex items-center gap-2 text-xs text-red-400 mb-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span className="break-all">{error}</span>
                </div>
              )}
              {/* 卡片内嵌列表用 10px 控件圆角（外层卡片 18px，rounded-lg 被主题映射为 18px，
                  故用 arbitrary 值锁定，不随主题圆角映射放大） */}
              <div className="flex-1 overflow-y-auto rounded-[10px] border border-zinc-800 divide-y divide-zinc-800">
                {sessions.length === 0 && !error && childTubs.length === 0 && (
                  <div className="p-4 text-sm text-zinc-500 text-center">
                    {t('tubLibrary.noRecordings')}
                  </div>
                )}
                {sessions.length === 0 && !error && childTubs.length > 0 && (
                  <div className="p-3 flex flex-col gap-2">
                    <div className="text-xs text-zinc-400">{t('tubLibrary.childTubsHint')}</div>
                    {childTubs.map((child) => {
                      const isSwitching = switchingChildPath === child.path;
                      return (
                        <button
                          key={child.path}
                          type="button"
                          onClick={() => void switchToChildTub(child)}
                          disabled={isSwitching}
                          aria-label={t('tubLibrary.openChildAria', { name: child.name })}
                          className="w-full text-left px-3 py-2.5 flex items-center justify-between gap-2 transition-colors hover:bg-zinc-800/60 border-l-2 border-transparent"
                        >
                          <div className="min-w-0">
                            <div className="text-sm font-medium truncate">{child.name}</div>
                            <div className="text-xs text-zinc-500">
                              {t('tubLibrary.frames', { count: child.record_count })}
                              {formatDateTime(child.last_modified_ms)
                                ? ` · ${formatDateTime(child.last_modified_ms)}`
                                : ''}
                            </div>
                          </div>
                          {isSwitching && (
                            <Loader2 className="w-4 h-4 animate-spin text-cyan-400 shrink-0" />
                          )}
                        </button>
                      );
                    })}
                  </div>
                )}
                {sortedSessions.map((session) => {
                  const key = sessionKey(session);
                  const isSelected = selected ? sessionKey(selected) === key : false;
                  // 多选成员（非锚点）：次高亮；锚点行保留既有主高亮
                  const isMultiMember = !isSelected && selectedKeys.has(key);
                  const isPinned = pinnedSet.has(key);
                  const isSwitching = switchingSessionKey === key;
                  const isChecked = isSelected || isMultiMember;
                  return (
                    <button
                      key={key}
                      type="button"
                      onClick={(e) => handleRowClick(session, e)}
                      disabled={isSwitching}
                      className={`w-full text-left px-3 py-2.5 flex items-center justify-between gap-2 transition-colors ${
                        isSelected
                          ? 'bg-cyan-500/10 border-l-2 border-cyan-400'
                          : isMultiMember
                            ? 'bg-cyan-500/5 border-l-2 border-cyan-500/40'
                            : 'hover:bg-zinc-800/60 border-l-2 border-transparent'
                      }`}
                    >
                      {/* 行首多选勾选框：等价 ctrl/⌘+点击（给不熟悉修饰键的用户可见入口），
                          沿用行内操作按钮的 stopPropagation 模式；跨 tub 行照常加入集合 */}
                      <span
                        role="checkbox"
                        aria-checked={isChecked}
                        tabIndex={0}
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleKey(session);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.stopPropagation();
                            e.preventDefault();
                            toggleKey(session);
                          }
                        }}
                        className={`mr-2 w-4 h-4 rounded border flex items-center justify-center shrink-0 transition-colors ${
                          isChecked
                            ? 'border-cyan-400 bg-cyan-500/20 text-cyan-400'
                            : 'border-zinc-600 text-transparent hover:border-cyan-400/60'
                        }`}
                      >
                        <Check className="w-3 h-3" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium truncate">
                          {formatDateTime(session.start_time_ms)
                            ?? session.session_id}
                          {/* 家族视图：不同 tub 的会话可能同一天录制，标注来源 tub */}
                          <span className="ml-1.5 align-middle text-[10px] font-normal px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400">
                            {session.tub_name}
                          </span>
                        </div>
                        <div className="text-xs text-zinc-500">
                          {t('tubLibrary.frames', { count: session.record_count })}
                          {formatDuration(session.start_time_ms, session.end_time_ms)
                            ? ` · ${formatDuration(session.start_time_ms, session.end_time_ms)}`
                            : ''}
                        </div>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        {isSwitching && (
                          <Loader2 className="w-4 h-4 animate-spin text-cyan-400 shrink-0" />
                        )}
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
                            downloadingId === key
                              ? 'text-cyan-400'
                              : 'text-zinc-500 hover:text-cyan-400 hover:bg-zinc-800/60'
                          }`}
                        >
                          {downloadingId === key ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : (
                            <Download className="w-4 h-4" />
                          )}
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
                className="w-full max-w-[640px] mx-auto bg-zinc-950 rounded-lg overflow-hidden border border-zinc-800 flex items-center justify-center relative"
                style={{ aspectRatio: frameAspect != null ? String(frameAspect) : '16 / 9' }}
              >
                <div className="absolute right-2 top-2 z-10 rounded-md border border-white/10 bg-zinc-900/80 px-2 py-1 text-center shadow-lg">
                  <div className="text-xs text-zinc-400 uppercase leading-none">FPS</div>
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

        {/* AI 清理碰撞后倒车（issue #373） */}
        {aiCleanOpen && tubPath && (
          <AiCleanModal
            tubPath={tubPath}
            onClose={() => setAiCleanOpen(false)}
            onExecuted={() => void refreshAfterAiClean()}
          />
        )}

        {/* Delete confirmation：单条（pendingDelete）与批量（pendingBatchDelete）复用同一弹窗壳 */}
        {(pendingDelete || pendingBatchDelete) && (
          <div className="fixed inset-0 bg-black/60 z-[70] flex items-center justify-center p-4">
            <div className="bg-zinc-900 border border-zinc-700 rounded-xl max-w-md w-full p-5 shadow-float">
              <div className="flex items-start gap-3">
                <div className="p-2 rounded-full bg-red-500/15 shrink-0">
                  <Trash2 className="w-5 h-5 text-red-400" />
                </div>
                <div className="min-w-0">
                  <h3 className="text-base font-semibold">
                    {pendingBatchDelete
                      ? t('tubLibrary.confirmBatchTitle', { segments: orderedSelectedSessions.length })
                      : t('tubLibrary.confirmTitle')}
                  </h3>
                  <p className="text-sm text-zinc-400 mt-1 break-all">
                    {pendingBatchDelete
                      ? t('tubLibrary.confirmBatchBody', {
                          segments: orderedSelectedSessions.length,
                          count: selectedFrameCount,
                        })
                      : t('tubLibrary.confirmBody', {
                          name: formatDateTime(pendingDelete!.start_time_ms) ?? pendingDelete!.session_id,
                          count: pendingDelete!.record_count,
                        })}
                  </p>
                </div>
              </div>
              <div className="flex justify-end gap-2 mt-5">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={deleting}
                  onClick={() => {
                    setPendingDelete(null);
                    setPendingBatchDelete(false);
                  }}
                >
                  {t('tubLibrary.cancel')}
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  disabled={deleting}
                  onClick={() => void (pendingBatchDelete ? confirmBatchDelete() : confirmDelete())}
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
