import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { FabActions } from './FabActions';
import { LanguageSwitcher } from './LanguageSwitcher';
import { GitHubLink } from './GitHubLink';
import { useTranslation } from '@/i18n';

export const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { t } = useTranslation();
  const location = useLocation();
  const isActive = (path: string) => location.pathname === path;

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans">
      <header className="border-b border-zinc-800 bg-zinc-900/50 backdrop-blur supports-[backdrop-filter]:bg-zinc-900/50 sticky top-0 z-50">
        <div className="container mx-auto px-4 h-14 flex items-center">
          <div className="font-bold text-xl mr-8">DonkeyDrifter</div>
          <nav className="flex items-center space-x-6 text-sm font-medium h-14">
            <Link 
              to="/" 
              className={`transition-colors hover:text-cyan-400 ${isActive('/') ? 'text-cyan-500' : 'text-zinc-400'}`}
            >
              {t('common.nav.tubManager')}
            </Link>
            <Link
              to="/trainer"
              className={`transition-colors hover:text-cyan-400 ${isActive('/trainer') ? 'text-cyan-500' : 'text-zinc-400'}`}
            >
              {t('common.nav.trainer')}
            </Link>
            <Link
              to="/drive"
              className={`transition-colors hover:text-cyan-400 ${isActive('/drive') ? 'text-cyan-500' : 'text-zinc-400'}`}
            >
              {t('common.nav.drive')}
            </Link>
            <Link
              to="/pilot"
              className={`transition-colors hover:text-cyan-400 ${isActive('/pilot') ? 'text-cyan-500' : 'text-zinc-400'}`}
            >
              {t('common.nav.pilotArena')}
            </Link>
            <Link
              to="/connector"
              className={`transition-colors hover:text-cyan-400 ${isActive('/connector') ? 'text-cyan-500' : 'text-zinc-400'}`}
            >
              {t('common.nav.carConnector')}
            </Link>
          </nav>
          <div className="ml-auto flex items-center gap-4">
            <GitHubLink />
            <LanguageSwitcher />
          </div>
        </div>
      </header>
      <main className="container mx-auto px-4 py-6 space-y-6">
        {children}
      </main>
      <FabActions />
    </div>
  );
};
