import React, { useEffect, useRef, useState } from 'react';
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

function SectionFallback() {
  const { t } = useTranslation();
  return <div className="py-12 text-sm text-zinc-400">{t('common.loading')}</div>;
}

function FlowSectionHeader({ step, meta }: { step: number; meta: SectionMeta }) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-3">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-cyan-500/40 bg-cyan-500/10 text-sm font-bold text-cyan-400">
        {step}
      </span>
      <div className="min-w-0">
        <h2 className="text-xl font-bold text-zinc-100">{t(meta.titleKey)}</h2>
        <p className="text-sm text-zinc-400">{t(meta.descKey)}</p>
      </div>
    </div>
  );
}

/**
 * 统一流程大页面（#178）：Drive / TM / Trainer / PA 四页纵向堆叠为一个
 * 连续滚动页，点顶部导航平滑滚动到对应区域；hash 路由（如 #/trainer）
 * 仍可深链定位。Car Connector 保持独立路由，不在此页。
 */
export function FlowPage() {
  const location = useLocation();
  const setActiveSection = useFlowStore((s) => s.setActiveSection);
  const rootRef = useRef<HTMLDivElement>(null);
  const ratiosRef = useRef<Partial<Record<FlowSectionId, number>>>({});
  const firstScrollRef = useRef(true);
  // 各 section 是否在视口内：滚走的分区禁用全局快捷键等副作用
  const [inView, setInView] = useState<Record<FlowSectionId, boolean>>({
    drive: true,
    'tub-manager': false,
    trainer: false,
    pilot: false,
  });

  // scroll spy：可见比例最大的 section 即导航高亮项
  useEffect(() => {
    const root = rootRef.current;
    if (!root || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = entry.target.id as FlowSectionId;
          ratiosRef.current[id] = entry.isIntersecting ? entry.intersectionRatio : 0;
        }
        // 可见比例最大的 section 才是"当前活跃"分区：只有它才需要激活
        // 视频流/键盘/手柄等重型副作用。用比例而非 isIntersecting，避免
        // 滚走后仍留几像素交集导致后台视频流一直跑（#135 收尾）。
        let best: FlowSectionId | null = null;
        for (const meta of SECTIONS) {
          const ratio = ratiosRef.current[meta.id] ?? 0;
          if (ratio > 0 && (best === null || ratio > (ratiosRef.current[best] ?? 0))) {
            best = meta.id;
          }
        }
        if (!best) return;
        setActiveSection(best);
        setInView((prev) => {
          const next: Record<FlowSectionId, boolean> = {
            drive: false,
            'tub-manager': false,
            trainer: false,
            pilot: false,
          };
          next[best] = true;
          let changed = false;
          for (const meta of SECTIONS) {
            if (next[meta.id] !== prev[meta.id]) changed = true;
          }
          return changed ? next : prev;
        });
      },
      { threshold: [0, 0.15, 0.3, 0.5, 0.75, 1] },
    );
    for (const meta of SECTIONS) {
      const el = root.querySelector(`#${meta.id}`);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [setActiveSection]);

  // 深链 / 导航点击：滚动到 path 对应的 section。
  // 懒加载 chunk 未就绪时元素尚不存在，用 rAF 轮询等待（上限 3s）。
  useEffect(() => {
    const meta = SECTIONS.find((s) => s.path === location.pathname);
    if (!meta) return;
    const behavior: ScrollBehavior = firstScrollRef.current ? 'auto' : 'smooth';
    firstScrollRef.current = false;
    const deadline = Date.now() + 3000;
    let raf = 0;
    const tryScroll = () => {
      const el = document.getElementById(meta.id);
      if (el) {
        if (typeof el.scrollIntoView === 'function') {
          el.scrollIntoView({ behavior });
        }
        return;
      }
      if (Date.now() < deadline) {
        raf = requestAnimationFrame(tryScroll);
      }
    };
    tryScroll();
    return () => cancelAnimationFrame(raf);
  }, [location.pathname]);

  return (
    <div ref={rootRef} className="space-y-12">
      <section id="drive" className="scroll-mt-40 lg:scroll-mt-20 space-y-4">
        <FlowSectionHeader step={1} meta={SECTIONS[0]} />
        <React.Suspense fallback={<SectionFallback />}>
          <DrivePage active={inView.drive} />        </React.Suspense>
      </section>

      <section id="tub-manager" className="scroll-mt-40 lg:scroll-mt-20 space-y-4 border-t border-zinc-800 pt-10">
        <FlowSectionHeader step={2} meta={SECTIONS[1]} />
        <TubManagerPage />
      </section>

      <section id="trainer" className="scroll-mt-40 lg:scroll-mt-20 space-y-4 border-t border-zinc-800 pt-10">
        <FlowSectionHeader step={3} meta={SECTIONS[2]} />
        <React.Suspense fallback={<SectionFallback />}>
          <TrainerPage />
        </React.Suspense>
      </section>

      <section id="pilot" className="scroll-mt-40 lg:scroll-mt-20 space-y-4 border-t border-zinc-800 pt-10">
        <FlowSectionHeader step={4} meta={SECTIONS[3]} />
        <React.Suspense fallback={<SectionFallback />}>
          <PilotArenaPage active={inView.pilot} />
        </React.Suspense>
      </section>
    </div>
  );
}
