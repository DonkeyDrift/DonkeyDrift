import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { TubManagerPage } from './TubManagerPage';
import { useFlowStore, type FlowSectionId } from '../store/useFlowStore';
import { useTranslation } from '@/i18n';


const TrainerPage = React.lazy(() => import('./TrainerPage').then((module) => ({ default: module.TrainerPage })));
const DrivePage = React.lazy(() => import('./DrivePage').then((module) => ({ default: module.DrivePage })));
const PilotArenaPage = React.lazy(() => import('./PilotArenaPage').then((module) => ({ default: module.PilotArenaPage })));

type SectionMeta = {
  id: FlowSectionId;
  /** 深链路由：点导航 / 直接访问该 path 时平滑滚动到本 section */
  path: string;
  titleKey: string;
  descKey: string;
};

/** Drive → TM → Trainer → PA 的固定顺序（#178）：自上而下对应 采数据 → 管数据 → 训练 → 评测 的流程引导 */
const SECTIONS: SectionMeta[] = [
  { id: 'drive', path: '/drive', titleKey: 'common.nav.drive', descKey: 'flow.drive.desc' },
  { id: 'tub-manager', path: '/tub', titleKey: 'common.nav.tubManager', descKey: 'flow.tubManager.desc' },
  { id: 'trainer', path: '/trainer', titleKey: 'common.nav.trainer', descKey: 'flow.trainer.desc' },
  { id: 'pilot', path: '/pilot', titleKey: 'common.nav.pilotArena', descKey: 'flow.pilotArena.desc' },
];

/**
 * 四个 section 常驻挂载但未必都在视口内；用 content-visibility:auto 让浏览器
 * 跳过视口外 section 的布局/绘制（DOM 仍在、状态保留），只按 contain-intrinsic-size
 * 占位。这样切导航平滑滚动时不用每一帧重算/重绘整页，是 #135 滚动卡顿的关键一刀。
 */
const SECTION_STYLE: React.CSSProperties = {
  contentVisibility: 'auto',
  containIntrinsicSize: 'auto 640px',
  // section 内容（视频挂载/数据列表流式展开）会造成布局位移，Chrome 的滚动
  // 锚定会把视口反向顶走或把程序化滚动按回原地（#135 第六轮实测的跳变根源）；
  // 排除锚点候选后浏览器不再"补偿"，滚动完全由用户/滑动动画控制。
  overflowAnchor: 'none',
};

function SectionFallback() {
  const { t } = useTranslation();
  return <div className="py-12 text-sm text-zinc-400">{t('common.loading')}</div>;
}

function FlowSectionHeader({ step, meta }: { step: number; meta: SectionMeta }) {
  const { t } = useTranslation();
  return (
    <div className="group flex items-center gap-3">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-cyan-500/40 bg-cyan-500/10 text-sm font-bold text-cyan-400">
        {step}
      </span>
      <div className="flex min-w-0 items-center">
        <h2 className="text-xl font-bold text-zinc-100">{t(meta.titleKey)}</h2>
        <span className="max-w-0 overflow-hidden whitespace-nowrap opacity-0 transition-all duration-300 ease-in-out group-hover:ml-3 group-hover:max-w-[400px] group-hover:opacity-100 text-sm text-zinc-400 font-normal">
          {t(meta.descKey)}
        </span>
      </div>
    </div>
  );
}

/**
 * 统一流程大页面（#178）：Drive / TM / Trainer / PA 四页纵向堆叠为一个
 * 连续滚动页，点顶部导航快速平滑滑到对应区域（#135 第六轮：rAF 逐帧重取
 * 目标的自定义滑动，替代原生 scrollIntoView）；hash 路由（如 #/trainer）
 * 仍可深链定位。Car Connector 保持独立路由，不在此页。
 *
 * 卡顿防护（#135 风暴根源）：
 * - 滑动期间冻结 IntersectionObserver scroll-spy：途经 section 不抢"活跃"身份，
 *   不会反复启停视频流/WebRTC/WebSocket（每次翻转都是一次完整重连）。
 * - 点击瞬间先把目标 section 设为活跃：目标内容边滑边就绪，落位即用。
 * - 手动滚动时 spy 去抖 100ms：可见比例在边界附近来回翻转时不再抖动提交。
 */
export function FlowPage() {
  const location = useLocation();
  const { pathname, key: locationKey } = location;
  const setActiveSection = useFlowStore((s) => s.setActiveSection);
  const rootRef = useRef<HTMLDivElement>(null);
  const ratiosRef = useRef<Partial<Record<FlowSectionId, number>>>({});
  const firstScrollRef = useRef(true);
  const activeRef = useRef<FlowSectionId>('drive');
  // 各 section 是否在视口内：滚走的分区禁用全局快捷键等副作用
  const [inView, setInView] = useState<Record<FlowSectionId, boolean>>({
    drive: true,
    'tub-manager': false,
    trainer: false,
    pilot: false,
  });

  // 程序化滑动状态：滑动期间 spy 冻结
  const animatingRef = useRef(false);
  const glideRafRef = useRef(0);
  const glideCleanupRef = useRef<(() => void) | null>(null);
  const glideSeqRef = useRef(0);
  const verifyTimersRef = useRef<number[]>([]);
  const commitTimerRef = useRef(0);
  const observerRef = useRef<IntersectionObserver | null>(null);

  /** 提交"当前活跃 section"：驱动导航高亮与各 section 的重型副作用启停 */
  const applyBest = useCallback(
    (best: FlowSectionId) => {
      if (best === activeRef.current) return;
      activeRef.current = best;
      setActiveSection(best);
      setInView((prev) => {
        if (prev[best]) return prev;
        const next: Record<FlowSectionId, boolean> = {
          drive: false,
          'tub-manager': false,
          trainer: false,
          pilot: false,
        };
        next[best] = true;
        return next;
      });
    },
    [setActiveSection],
  );

  /** 可见比例最大的 section 即"当前活跃"（用比例而非 isIntersecting，避免滚走后
   *  仍留几像素交集导致后台视频流一直跑，#135 收尾） */
  const bestFromRatios = useCallback((): FlowSectionId | null => {
    let best: FlowSectionId | null = null;
    for (const meta of SECTIONS) {
      const ratio = ratiosRef.current[meta.id] ?? 0;
      if (ratio > 0 && (best === null || ratio > (ratiosRef.current[best] ?? 0))) {
        best = meta.id;
      }
    }
    return best;
  }, []);

  // scroll spy：IntersectionObserver 只更新比例，提交走 100ms 去抖
  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(
      (entries) => {
        // 程序化滑动期间冻结：途经 section 不抢激活（#135 第六轮）
        if (animatingRef.current) return;
        for (const entry of entries) {
          const id = entry.target.id as FlowSectionId;
          ratiosRef.current[id] = entry.isIntersecting ? entry.intersectionRatio : 0;
        }
        if (!bestFromRatios()) return;
        // 去抖提交：手动滚动经过边界时比例来回翻转，停顿 100ms 才落定，
        // 避免视频流/WebRTC/WS 因 active 抖动反复启停
        window.clearTimeout(commitTimerRef.current);
        commitTimerRef.current = window.setTimeout(() => {
          const best = bestFromRatios();
          if (best) applyBest(best);
        }, 100);
      },
      { threshold: [0, 0.15, 0.3, 0.5, 0.75, 1] },
    );
    observerRef.current = observer;
    for (const meta of SECTIONS) {
      const el = root.querySelector(`#${meta.id}`);
      if (el) observer.observe(el);
    }
    return () => {
      observer.disconnect();
      observerRef.current = null;
    };
  }, [applyBest, bestFromRatios]);

  /** 重新 observe 触发一轮全量上报：滑动结束/被打断后让 spy 与实际位置对齐 */
  const resyncObserver = useCallback(() => {
    const observer = observerRef.current;
    const root = rootRef.current;
    if (!observer || !root) return;
    observer.disconnect();
    for (const meta of SECTIONS) {
      const el = root.querySelector(`#${meta.id}`);
      if (el) observer.observe(el);
    }
  }, []);

  const stopGlide = useCallback(() => {
    glideSeqRef.current++; // 作废在途会话（含落定后的延迟校验）
    glideCleanupRef.current?.();
    glideCleanupRef.current = null;
    for (const t of verifyTimersRef.current) window.clearTimeout(t);
    verifyTimersRef.current = [];
  }, []);

  /**
   * 快速平滑滑到目标 section（像一次快进的手动滚动，而非瞬跳）：
   * - rAF 逐帧重取目标位置：途经 section 因 content-visibility 展开导致目标
   *   漂移时以当前位置重新起滑（原生 smooth 会落错）。
   * - 滑动期间禁用 scroll anchoring：目标 section 激活导致上方内容展开时，
   *   浏览器滚动锚定会把视口反向顶走一截，观感像先跳错方向再滑回来。
   * - 落定后 250/750/1500ms 三次校验：content-visibility 占位在滑近/落定后
   *   才展开，把目标推走超过 32px 时再补一次短滑，保证最终精准落位。
   * - 时长按距离 250–750ms + easeOutCubic，快而有"翻页"感。
   * - 用户滚轮/触摸/按键立即接管：取消滑动并作废后续校验，绝不与用户抢滚动。
   * - prefers-reduced-motion 或首次深链直接落位（落位后同样校验）。
   */
  const glideTo = useCallback(
    (id: FlowSectionId, instant: boolean) => {
      const el = document.getElementById(id);
      if (!el) return;
      const seq = glideSeqRef.current + 1;
      glideSeqRef.current = seq;
      const reduced =
        typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const margin = parseFloat(getComputedStyle(el).scrollMarginTop) || 0;
      const targetTop = () => el.getBoundingClientRect().top + window.scrollY - margin;
      const live = () => glideSeqRef.current === seq;
      stopGlide();
      glideSeqRef.current = seq; // stopGlide 会递增作废，重新登记本会话

      /** 落定后的延迟校验：目标被布局展开推走时补一次短滑 */
      const scheduleVerify = () => {
        for (const delay of [250, 750, 1500]) {
          const t = window.setTimeout(() => {
            if (!live()) return;
            const node = document.getElementById(id);
            if (!node) return;
            const m = parseFloat(getComputedStyle(node).scrollMarginTop) || 0;
            if (Math.abs(node.getBoundingClientRect().top - m) > 32) {
              glideTo(id, false); // 新会话：内部会再次登记校验
            }
          }, delay);
          verifyTimersRef.current.push(t);
        }
      };

      if (instant || reduced) {
        window.scrollTo(0, targetTop());
        scheduleVerify();
        return;
      }
      animatingRef.current = true;
      document.documentElement.style.overflowAnchor = 'none';
      document.body.style.overflowAnchor = 'none';
      let from = window.scrollY;
      let target = targetTop();
      let dur = Math.min(750, 250 + Math.abs(target - from) * 0.08);
      let raf = 0;
      let timer = 0;
      let done = false;

      const finish = (userTookOver: boolean) => {
        if (done) return;
        done = true;
        cancelAnimationFrame(raf);
        glideRafRef.current = 0;
        window.clearTimeout(timer);
        window.removeEventListener('wheel', onUserInput);
        window.removeEventListener('touchstart', onUserInput);
        window.removeEventListener('keydown', onUserInput);
        document.documentElement.style.overflowAnchor = '';
        document.body.style.overflowAnchor = '';
        glideCleanupRef.current = null;
        if (userTookOver) {
          // 用户接管：作废本会话后续校验，立即解冻 spy 对齐实际位置
          if (live()) glideSeqRef.current++;
          animatingRef.current = false;
          resyncObserver();
          return;
        }
        // 落定后等布局稳定再解冻 spy，并让 IO 全量重报对齐一次；随后延迟校验
        timer = window.setTimeout(() => {
          if (!live()) return;
          animatingRef.current = false;
          resyncObserver();
          scheduleVerify();
        }, 180);
      };
      const onUserInput = () => finish(true);
      glideCleanupRef.current = () => finish(false);

      // 用户主动滚动立即接管
      window.addEventListener('wheel', onUserInput, { passive: true });
      window.addEventListener('touchstart', onUserInput, { passive: true });
      window.addEventListener('keydown', onUserInput);

      const easeOut = (p: number) => 1 - Math.pow(1 - p, 3);
      // 进度用"每帧限幅增量"推进：点击后主线程可能被数据加载/渲染占住几秒，
      // rAF 全程饿死，等恢复时若按真实墙钟算进度会一步跳到终点（#135 实测
      // "点了很久才动、一动就瞬跳"的根源）。限幅后无论饿多久，恢复首帧都
      // 只推进一小步，动画完整走完。
      let progress = 0;
      let lastTs = 0;
      const step = (now: number) => {
        if (done) return;
        const actual = targetTop();
        if (Math.abs(actual - target) > 4) {
          // 目标漂移（途经/目标 section 高度展开）：以当前位置重新起滑，短滑程收敛
          from = window.scrollY;
          target = actual;
          progress = 0;
          lastTs = now;
          dur = Math.min(400, Math.max(120, Math.abs(target - from) * 0.25));
        }
        if (lastTs === 0) lastTs = now;
        progress = Math.min(1, progress + Math.min(48, now - lastTs) / dur);
        lastTs = now;
        window.scrollTo(0, from + (target - from) * easeOut(progress));
        if (progress >= 1) {
          finish(false);
          return;
        }
        raf = requestAnimationFrame(step);
        glideRafRef.current = raf;
      };
      raf = requestAnimationFrame(step);
      glideRafRef.current = raf;
    },
    [resyncObserver, stopGlide],
  );

  // 深链 / 导航点击：滑动到 path 对应的 section。
  // 懒加载 chunk 未就绪时元素尚不存在，用 rAF 轮询等待（上限 3s）。
  // 依赖 location.key 而非仅 pathname：点同一导航项（path 不变）也要能再次滚动。
  useEffect(() => {
    const meta = SECTIONS.find((s) => s.path === pathname);
    if (!meta) return;
    const instant = firstScrollRef.current;
    firstScrollRef.current = false;
    // 点击瞬间先把目标设为活跃：目标内容（视频/图表）边滑边就绪；
    // 滑动期间 spy 冻结，途经 section 不会触发它们的重型副作用
    applyBest(meta.id);
    const deadline = Date.now() + 3000;
    let raf = 0;
    const tryScroll = () => {
      const el = document.getElementById(meta.id);
      if (el) {
        glideTo(meta.id, instant);
        return;
      }
      if (Date.now() < deadline) {
        raf = requestAnimationFrame(tryScroll);
      }
    };
    tryScroll();
    return () => cancelAnimationFrame(raf);
  }, [pathname, locationKey, applyBest, glideTo]);

  // 卸载清理：停止滑动与去抖提交
  useEffect(
    () => () => {
      stopGlide();
      cancelAnimationFrame(glideRafRef.current);
      window.clearTimeout(commitTimerRef.current);
      animatingRef.current = false;
    },
    [stopGlide],
  );

  return (
    <div ref={rootRef} className="space-y-12">
      <section id="drive" style={SECTION_STYLE} className="scroll-mt-40 lg:scroll-mt-20 space-y-4">
        <FlowSectionHeader step={1} meta={SECTIONS[0]} />
        <React.Suspense fallback={<SectionFallback />}>
          <DrivePage active={inView.drive} />
        </React.Suspense>
      </section>

      <section id="tub-manager" style={SECTION_STYLE} className="scroll-mt-40 lg:scroll-mt-20 space-y-4 border-t border-zinc-800 pt-10">
        <FlowSectionHeader step={2} meta={SECTIONS[1]} />
        <TubManagerPage />
      </section>

      <section id="trainer" style={SECTION_STYLE} className="scroll-mt-40 lg:scroll-mt-20 space-y-4 border-t border-zinc-800 pt-10">
        <FlowSectionHeader step={3} meta={SECTIONS[2]} />
        <React.Suspense fallback={<SectionFallback />}>
          <TrainerPage />
        </React.Suspense>
      </section>

      <section id="pilot" style={SECTION_STYLE} className="scroll-mt-40 lg:scroll-mt-20 space-y-4 border-t border-zinc-800 pt-10">
        <FlowSectionHeader step={4} meta={SECTIONS[3]} />
        <React.Suspense fallback={<SectionFallback />}>
          <PilotArenaPage active={inView.pilot} />
        </React.Suspense>
      </section>
    </div>
  );
}
