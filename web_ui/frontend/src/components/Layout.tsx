import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { HelpModal } from './HelpModal';

export const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const location = useLocation();
  const isActive = (path: string) => location.pathname === path;

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans">
      <header className="border-b border-zinc-800 bg-zinc-900/50 backdrop-blur supports-[backdrop-filter]:bg-zinc-900/50 sticky top-0 z-50">
        <div className="container mx-auto px-4 h-14 flex items-center">
          <div className="font-bold text-xl mr-8">Donkey Car</div>
          <nav className="flex items-center space-x-6 text-sm font-medium h-14">
            <Link 
              to="/" 
              className={`transition-colors hover:text-cyan-400 ${isActive('/') ? 'text-cyan-500' : 'text-zinc-400'}`}
            >
              Tub Manager
            </Link>
            <Link
              to="/trainer"
              className={`transition-colors hover:text-cyan-400 ${isActive('/trainer') ? 'text-cyan-500' : 'text-zinc-400'}`}
            >
              Trainer
            </Link>
            <Link
              to="/drive"
              className={`transition-colors hover:text-cyan-400 ${isActive('/drive') ? 'text-cyan-500' : 'text-zinc-400'}`}
            >
              Drive
            </Link>
            <Link
              to="/calibrate"
              className={`transition-colors hover:text-cyan-400 ${isActive('/calibrate') ? 'text-cyan-500' : 'text-zinc-400'}`}
            >
              Calibrate
            </Link>
            <Link
              to="/pilot"
              className={`transition-colors hover:text-cyan-400 ${isActive('/pilot') ? 'text-cyan-500' : 'text-zinc-400'}`}
            >
              Pilot Arena
            </Link>
            <Link
              to="/connector"
              className={`transition-colors hover:text-cyan-400 ${isActive('/connector') ? 'text-cyan-500' : 'text-zinc-400'}`}
            >
              Car Connector
            </Link>
          </nav>
        </div>
      </header>
      <main className="container mx-auto px-4 py-6 space-y-6">
        {children}
      </main>
      <footer className="border-t border-zinc-800 py-4 mt-8">
        <div className="container mx-auto px-4 text-center text-sm text-zinc-500">
          Donkey Car Web UI
        </div>
      </footer>
      <HelpModal />
    </div>
  );
};
