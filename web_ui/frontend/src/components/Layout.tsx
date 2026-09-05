import React, { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Menu, Settings, X } from 'lucide-react';
import { FabActions } from './FabActions';
import { LanguageSwitcher } from './LanguageSwitcher';
import { GitHubLink } from './GitHubLink';
import { VersionBadge } from './VersionBadge';
import { DonkeyEntryLink, DshEntryLink, DrifterConsoleEntryLink, entryLinkCls, KimiCodeWebEntryLink, ZCodeEntryLink } from './EnterButtons';
import { ConsoleDevToggle, ConsoleMuteButton, ConsoleOtaButton } from './ConsoleControls';
import { ThemeSwitcher } from './ThemeSwitcher';
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

  // 切换路由后收起手机菜单
  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

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
            <div className="font-bold text-xl lg:mr-8">
              {/* logo 与标题文字同包一个链接（Issue #179）：点击任意一处均可跳转官网，文字继承主题色无链接默认样式 */}
              <a href="https://www.donkeydrift.com" target="_blank" rel="noopener" className="flex items-center gap-3"><img src="/logo.png" alt="DonkeyDrift" className="w-8 h-8 border header-logo" />DonkeyDrift</a>
            </div>
            {/* 手机端：GitHub 图标 + 版本号紧跟标题右侧，菜单收起时也可见 */}
            <div className="ml-2 flex items-center gap-2 lg:hidden">
              <GitHubLink />
              <VersionBadge />
            </div>
            {/* 桌面导航（≥lg）；手机/竖屏平板收进汉堡菜单。
                前四项是流程页锚点（#178），CC 仍是独立路由；高级入口（Donkey /
                Drift Console / Kimi Code Web / DeepSeek Harness）融入导航行但弱化样式，
                见 EnterButtons.tsx（Issue #175） */}
            <nav className="hidden lg:flex items-center space-x-6 text-sm font-medium h-14">
              <DonkeyEntryLink />
              <DrifterConsoleEntryLink />
              {FLOW_NAV_ITEMS.map((item) => (
                <Link key={item.path} to={item.path} className={flowClass(item.section)}>
                  {t(item.labelKey)}
                </Link>
              ))}
              <Link
                to="/connector"
                className={`${entryLinkCls} ${isConnector ? 'text-cyan-400' : ''}`}
              >
                <Settings className="w-3.5 h-3.5 shrink-0" />
                {t('common.nav.carConnector')}
              </Link>
              <KimiCodeWebEntryLink />
              <ZCodeEntryLink />
              <DshEntryLink />
            </nav>
            <div className="ml-auto hidden lg:flex items-center gap-4">
              <VersionBadge />
              <GitHubLink />
              <ConsoleMuteButton />
              <ThemeSwitcher />
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
          {/* 手机端标题区第二行：静音 + 主题 + 语言 + OTA + DEV（与桌面顶栏顺序一致） */}
          <div className="flex items-center gap-3 pb-3 lg:hidden">
            <ConsoleMuteButton />
            <ThemeSwitcher />
            <LanguageSwitcher />
            <ConsoleOtaButton />
            <ConsoleDevToggle />
          </div>
        </div>
        {/* 手机菜单面板：导航项 + 高级入口（Donkey / Drifter Console / Kimi Code Web /
            DeepSeek Harness，弱化样式与桌面一致）；主题/语言/版本号已移至标题区 */}
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
              <Link
                to="/connector"
                onClick={() => setMobileMenuOpen(false)}
                className={`${entryLinkCls} ${isConnector ? 'text-cyan-400' : ''}`}
              >
                <Settings className="w-3.5 h-3.5 shrink-0" />
                {t('common.nav.carConnector')}
              </Link>
              <div className="mt-1 border-t border-zinc-800/60">
                <DonkeyEntryLink />
                <DrifterConsoleEntryLink />
                <KimiCodeWebEntryLink />
                <ZCodeEntryLink />
                <DshEntryLink />
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
