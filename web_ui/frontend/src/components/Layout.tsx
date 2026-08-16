import React, { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Menu, X } from 'lucide-react';
import { FabActions } from './FabActions';
import { LanguageSwitcher } from './LanguageSwitcher';
import { GitHubLink } from './GitHubLink';
import { VersionBadge } from './VersionBadge';
import { EnterButtons } from './EnterButtons';
import { ThemeSwitcher } from './ThemeSwitcher';
import { useTranslation } from '@/i18n';

export const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { t } = useTranslation();
  const location = useLocation();
  const isActive = (path: string) => location.pathname === path;
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // 切换路由后收起手机菜单
  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

  const navItems = [
    { path: '/drive', labelKey: 'common.nav.drive' },
    { path: '/', labelKey: 'common.nav.tubManager' },
    { path: '/trainer', labelKey: 'common.nav.trainer' },
    { path: '/pilot', labelKey: 'common.nav.pilotArena' },
    { path: '/connector', labelKey: 'common.nav.carConnector' },
  ];

  const linkClass = (path: string) =>
    `transition-colors hover:text-cyan-400 whitespace-nowrap ${isActive(path) ? 'text-cyan-500' : 'text-zinc-400'}`;

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans">
      <header className="border-b border-zinc-800 bg-zinc-900/50 backdrop-blur supports-[backdrop-filter]:bg-zinc-900/50 sticky top-0 z-50">
        <div className="container mx-auto px-4">
          <div className="h-14 flex items-center">
            {/* 标题左侧 logo：样式对齐 Donkey 启动页（8090）headerLogo —— 32×32、rounded-lg(8px)、1px #2b3441 边框、与标题 gap 12px */}
            <div className="font-bold text-xl lg:mr-8 flex items-center gap-3">
              <a href="https://www.donkeydrift.com" target="_blank" rel="noopener" className="flex items-center"><img src="/logo.png" alt="DonkeyDrifter" className="w-8 h-8 rounded-lg border border-[#2b3441]" /></a>
              DonkeyDrifter
            </div>
            {/* 手机端：GitHub 图标 + 版本号紧跟标题右侧，菜单收起时也可见 */}
            <div className="ml-2 flex items-center gap-2 lg:hidden">
              <GitHubLink />
              <VersionBadge />
            </div>
            {/* 桌面导航（≥lg）；手机/竖屏平板收进汉堡菜单 */}
            <nav className="hidden lg:flex items-center space-x-6 text-sm font-medium h-14">
              {navItems.map((item) => (
                <Link key={item.path} to={item.path} className={linkClass(item.path)}>
                  {t(item.labelKey)}
                </Link>
              ))}
            </nav>
            <div className="ml-auto hidden lg:flex items-center gap-4">
              <VersionBadge />
              <GitHubLink />
              <EnterButtons />
              <ThemeSwitcher />
              <LanguageSwitcher />
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
          {/* 手机端标题区第二行：进入按钮（DrifterConsole 在左，Kimi Code Web 在右） */}
          <div className="flex items-center pb-2 lg:hidden">
            <EnterButtons consoleFirst />
          </div>
          {/* 手机端标题区第三行：左边主题切换，右边语言切换 */}
          <div className="flex items-center gap-3 pb-3 lg:hidden">
            <ThemeSwitcher />
            <LanguageSwitcher />
          </div>
        </div>
        {/* 手机菜单面板：仅导航项（进入按钮/主题/语言/版本号已移至标题区） */}
        {mobileMenuOpen && (
          <div className="lg:hidden border-t border-zinc-800 bg-zinc-900">
            <nav className="container mx-auto px-4 py-2 flex flex-col text-sm font-medium">
              {navItems.map((item) => (
                <Link key={item.path} to={item.path} className={`py-2.5 ${linkClass(item.path)}`}>
                  {t(item.labelKey)}
                </Link>
              ))}
            </nav>
          </div>
        )}
      </header>
      <main className="container mx-auto px-4 py-6 space-y-6">
        {children}
      </main>
      <FabActions />
    </div>
  );
};
