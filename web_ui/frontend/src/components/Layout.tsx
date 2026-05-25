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
            <div className="relative h-full flex items-center group">
              <span className="transition-colors hover:text-cyan-400 text-zinc-400 cursor-not-allowed">Pilot Arena</span>
              <div className="absolute top-full left-0 mt-3 px-2 py-1 bg-zinc-900 text-xs text-white rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-[100] shadow-xl border border-zinc-700">
                To be done
                <div className="absolute -top-[5px] left-3 w-2.5 h-2.5 bg-zinc-900 border-t border-l border-zinc-700 rotate-45"></div>
              </div>
            </div>
            <div className="relative h-full flex items-center group">
              <span className="transition-colors hover:text-cyan-400 text-zinc-400 cursor-not-allowed">Car Connector</span>
              <div className="absolute top-full left-0 mt-3 px-2 py-1 bg-zinc-900 text-xs text-white rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-[100] shadow-xl border border-zinc-700">
                To be done
                <div className="absolute -top-[5px] left-3 w-2.5 h-2.5 bg-zinc-900 border-t border-l border-zinc-700 rotate-45"></div>
              </div>
            </div>
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
