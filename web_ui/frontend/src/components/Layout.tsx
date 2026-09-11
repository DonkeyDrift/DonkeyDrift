import React, { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Menu, MoreHorizontal, X } from 'lucide-react';
import { FabActions } from './FabActions';
import { LanguageSwitcher } from './LanguageSwitcher';
import { GitHubLink } from './GitHubLink';
import { CarConnectorButton } from './CarConnectorButton';
import { VersionBadge } from './VersionBadge';
import { DonkeyEntryLink, DshEntryLink, DrifterConsoleEntryLink, FindCarEntryLink, KimiCodeWebEntryLink, ZCodeEntryLink } from './EnterButtons';
import { ConsoleDevToggle, ConsoleMuteButton, ConsoleOtaButton } from './ConsoleControls';
import { ThemeSwitcher } from './ThemeSwitcher';
import { SkinSwitcher } from './SkinSwitcher';
import { useTranslation } from '@/i18n';
import { useFlowStore, type FlowSectionId } from '../store/useFlowStore';

/** 统一流程大页面（#178）中四个导航锚点：点击滚动到对应 section，
 *  激活态随滚动位置联动（scroll spy，见 FlowPage 的 IntersectionObserver） */
const FLOW_NAV_ITEMS: { path: string; section: FlowSectionId; labelKey: string }[] = [
  { path: '/drive', section: 'drive', labelKey: 'common.nav.drive' },
  { path: '/tub', section: 'tub-manager', labelKey: 'common.nav.tubManager' },
  { path: '/trainer', section: 'trainer', labelKey: 'common.nav.trainer' },
  { path: '/pilot', section: 'pilot', labelKey: 'common.nav.pilotArena' },
];

export const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { t } = useTranslation();
  const location = useLocation();
  const activeSection = useFlowStore((s) => s.activeSection);
  // Car Connector 是独立路由，只在 /connector 上高亮
  const isConnector = location.pathname === '/connector';
  // Drifter Console（/console）与 Donkey 菜单（/donkey）也是独立路由：由各自入口
  // 自身高亮，此时 Drive 等流程锚点一律不高亮
  const isConsole = location.pathname === '/console';
  const isDonkey = location.pathname === '/donkey';
  const isFullBleed = isConsole || isDonkey;
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  // 桌面端「更多入口」溢出菜单（KCW / ZCode / DSH / FindCar）——顶栏拥挤时收起
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const moreMenuRef = useRef<HTMLDivElement>(null);

  // 切换路由后收起手机菜单与溢出菜单
  useEffect(() => {
    setMobileMenuOpen(false);
    setMoreMenuOpen(false);
  }, [location.pathname]);

  // 点击溢出菜单外部或按 Esc 时收起
  useEffect(() => {
    if (!moreMenuOpen) return;
    const onPointerDown = (e: PointerEvent) => {
      if (moreMenuRef.current && !moreMenuRef.current.contains(e.target as Node)) {
        setMoreMenuOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMoreMenuOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [moreMenuOpen]);

  const flowClass = (section: FlowSectionId) =>
    `transition-colors hover:text-cyan-400 whitespace-nowrap ${
      !isConnector && !isFullBleed && activeSection === section ? 'text-cyan-500' : 'text-zinc-400'
    }`;

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans">
      <header className="bg-zinc-950 sticky top-0 z-50">
        <div className="px-3">
          <div className="h-14 flex items-center">
            {/* 标题左侧 logo：与 Drifter Console 独立页 headerLogo 完全一致 —— 32px 内容 + 1px 边框外凸（box-sizing content-box，总 34px）、圆角 8px、边框随主题（深色 #2b3441 / 浅色 #d5dce4，见 theme-*.css 的 .header-logo）、与标题 gap 12px */}
            <div className="font-bold text-xl lg:mr-4">
              {/* logo 与标题文字同包一个链接（Issue #179）：点击任意一处均可跳转官网，文字继承主题色无链接默认样式 */}
              <a href="https://www.donkeydrift.com" target="_blank" rel="noopener" className="flex items-center gap-3"><img src="/logo.png" alt="DonkeyDrifter" className="w-8 h-8 border header-logo" />DonkeyDrifter</a>
            </div>
            {/* GitHub 图标 + 版本号紧跟标题右侧（全宽度显示，不占右侧控制区空间） */}
            <div className="ml-2 flex items-center gap-2">
              <GitHubLink />
              <VersionBadge />
            </div>
            {/* 桌面导航（≥lg）；手机/竖屏平板收进汉堡菜单。
                流程页锚点（#178）；Car Connector 已改为右侧控制区图标按钮（Issue #406）；
                高级入口（Donkey / Drift Console / Kimi Code Web / DeepSeek Harness）融入导航行但弱化样式，
                见 EnterButtons.tsx（Issue #175） */}
            <nav className="hidden lg:flex items-center space-x-4 text-sm font-medium h-14">
              {/* Donkey / Drifter Console 入口在 ≥xl 进主导航，lg 档收进「⋯」菜单 */}
              <div className="hidden xl:contents">
                <DonkeyEntryLink />
                <DrifterConsoleEntryLink />
              </div>
              {FLOW_NAV_ITEMS.map((item) => (
                <Link key={item.path} to={item.path} className={flowClass(item.section)}>
                  {t(item.labelKey)}
                </Link>
              ))}
              {/* 高级工具入口收进「⋯」溢出菜单（顶栏空间让给主导航与风格切换） */}
              <div className="relative" ref={moreMenuRef}>
                <button
                  type="button"
                  aria-label={t('common.nav.more')}
                  aria-expanded={moreMenuOpen}
                  onClick={() => setMoreMenuOpen((open) => !open)}
                  className="flex items-center justify-center w-8 h-8 rounded-full text-zinc-400 hover:text-zinc-100 transition-colors"
                >
                  <MoreHorizontal className="w-5 h-5" />
                </button>
                {moreMenuOpen && (
                  <div className="absolute right-0 top-10 z-50 flex min-w-[180px] flex-col gap-1 rounded-xl border border-zinc-800 bg-zinc-900 p-2 shadow-xl">
                    <div className="flex flex-col gap-1 xl:hidden">
                      <DonkeyEntryLink />
                      <DrifterConsoleEntryLink />
                    </div>
                    <KimiCodeWebEntryLink />
                    <ZCodeEntryLink />
                    <DshEntryLink />
                    <FindCarEntryLink />
                  </div>
                )}
              </div>
            </nav>
            <div className="ml-auto hidden lg:flex items-center gap-3">
              <CarConnectorButton />
              <ConsoleMuteButton />
              <ThemeSwitcher />
              <SkinSwitcher />
              <LanguageSwitcher />
              <ConsoleOtaButton />
              <ConsoleDevToggle />
            </div>
            {/* 手机端右侧：仅汉堡按钮 */}
            <div className="ml-auto flex items-center lg:hidden">
              <button
                type="button"
                aria-label={t('common.nav.menu')}
                aria-expanded={mobileMenuOpen}
                onClick={() => setMobileMenuOpen((open) => !open)}
                className="p-2 text-zinc-400 hover:text-zinc-100 transition-colors"
              >
                {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
              </button>
            </div>
          </div>
          {/* 手机端标题区第二行：CC + 静音 + 主题 + 语言 + OTA + DEV（与桌面顶栏顺序一致） */}
          <div className="flex items-center gap-3 pb-3 lg:hidden">
            <CarConnectorButton />
            <ConsoleMuteButton />
            <ThemeSwitcher />
            <LanguageSwitcher />
            <ConsoleOtaButton />
            <ConsoleDevToggle />
          </div>
        </div>
        {/* 手机菜单面板：导航项 + 高级入口（Donkey / Drifter Console / Kimi Code Web /
            DeepSeek Harness，弱化样式与桌面一致）+ 座舱/Apple 风格切换；
            主题/语言/版本号与 Car Connector 已移至标题区 */}
        {mobileMenuOpen && (
          <div className="lg:hidden border-t border-zinc-800 bg-zinc-900">
            <nav className="container mx-auto px-4 py-2 flex flex-col text-sm font-medium">
              {FLOW_NAV_ITEMS.map((item) => (
                <Link
                  key={item.path}
                  to={item.path}
                  onClick={() => setMobileMenuOpen(false)}
                  className={`py-2.5 ${flowClass(item.section)}`}
                >
                  {t(item.labelKey)}
                </Link>
              ))}
              <div className="mt-1 border-t border-zinc-800/60">
                <DonkeyEntryLink />
                <DrifterConsoleEntryLink />
                <KimiCodeWebEntryLink />
                <ZCodeEntryLink />
                <DshEntryLink />
                <FindCarEntryLink />
              </div>
              {/* 风格切换（座舱/Apple）：移动端放在折叠菜单里，与桌面顶栏控制组同款 */}
              <div className="mt-1 border-t border-zinc-800/60 pt-3 pb-2">
                <SkinSwitcher />
              </div>
            </nav>
          </div>
        )}
      </header>
      <main className={isFullBleed ? 'py-0' : 'container mx-auto px-4 py-6 space-y-6'}>
        {children}
      </main>
      {/* /donkey 是铺满的 launcher 内嵌页，右下角帮助小球应由 Donkey 自己提供，
          隐藏 DD 的 FAB 避免与 launcher 自带 FAB 重叠（Issue #263 补强）。 */}
      {!isDonkey && <FabActions />}
    </div>
  );
};
