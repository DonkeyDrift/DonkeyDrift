import React from 'react';
import { ConfigLoader } from './ConfigLoader';
import { TubLoader } from './TubLoader';
import { SimulatorConfig } from './SimulatorConfig';
import { FolderOpen, Plug } from 'lucide-react';

import { useStore } from '../store/useStore';
import { useTranslation } from '@/i18n';

export const SidePanel: React.FC = () => {
  const { t } = useTranslation();
  const { activeDrawer, setActiveDrawer } = useStore();
  const [hovered, setHovered] = React.useState<'loaders' | 'connectors' | null>(null);

  const isLoadersOpen = activeDrawer === 'loaders';
  const isConnectorsOpen = activeDrawer === 'connectors';

  const toggleLoaders = () => setActiveDrawer(isLoadersOpen ? null : 'loaders');
  const toggleConnectors = () => setActiveDrawer(isConnectorsOpen ? null : 'connectors');

  const anyOpen = isLoadersOpen || isConnectorsOpen;

  return (
    <>
      {/* Shared Drawer Container — width only changes when opening/closing, not when switching tabs */}
      <div
        className={`fixed left-0 top-16 h-[calc(100vh-4rem)] z-40 transition-all duration-300 ease-in-out ${
          anyOpen ? 'w-96' : 'w-0'
        }`}
      >
        {/* Floating Trigger Buttons — outside overflow-hidden content */}
        <div className="absolute left-full top-2 flex flex-col gap-1 items-start">
          {/* Loaders Button */}
          <button
            onClick={toggleLoaders}
            onMouseEnter={() => setHovered('loaders')}
            onMouseLeave={() => setHovered(null)}
            className={`border p-2 rounded-r-md transition-all duration-300 shadow-lg flex items-center ${
              isLoadersOpen
                ? 'bg-zinc-900 text-cyan-400 border-cyan-800/60'
                : hovered === 'loaders'
                  ? 'bg-zinc-800 text-white border-zinc-700'
                  : 'bg-zinc-900 text-zinc-400 border-zinc-800'
            } ${anyOpen ? 'border-l' : 'border-l-0'}`}
          >
            <FolderOpen className={`w-5 h-5 shrink-0 transition-colors duration-300 ${isLoadersOpen ? 'text-cyan-400' : hovered === 'loaders' ? 'text-white' : 'text-zinc-400'}`} />
            <span className={`text-xs font-medium whitespace-nowrap overflow-hidden transition-all duration-300 ${anyOpen || hovered === 'loaders' ? 'max-w-[100px] opacity-100 ml-2' : 'max-w-0 opacity-0 ml-0'}`}>
              {t('common.sidePanel.loaders')}
            </span>
          </button>

          {/* Connectors Button */}
          <button
            onClick={toggleConnectors}
            onMouseEnter={() => setHovered('connectors')}
            onMouseLeave={() => setHovered(null)}
            className={`border p-2 rounded-r-md transition-all duration-300 shadow-lg flex items-center ${
              isConnectorsOpen
                ? 'bg-zinc-900 text-cyan-400 border-cyan-800/60'
                : hovered === 'connectors'
                  ? 'bg-zinc-800 text-white border-zinc-700'
                  : 'bg-zinc-900 text-zinc-400 border-zinc-800'
            } ${anyOpen ? 'border-l' : 'border-l-0'}`}
          >
            <Plug className={`w-5 h-5 shrink-0 transition-colors duration-300 ${isConnectorsOpen ? 'text-cyan-400' : hovered === 'connectors' ? 'text-white' : 'text-zinc-400'}`} />
            <span className={`text-xs font-medium whitespace-nowrap overflow-hidden transition-all duration-300 ${anyOpen || hovered === 'connectors' ? 'max-w-[100px] opacity-100 ml-2' : 'max-w-0 opacity-0 ml-0'}`}>
              {t('common.sidePanel.connectors')}
            </span>
          </button>
        </div>

        {/* Panel Content — inside overflow-hidden area */}
        <div className="h-full bg-zinc-900 border-r border-zinc-800 shadow-2xl overflow-y-auto overflow-x-hidden">
          <div className={`p-6 space-y-6 transition-opacity duration-300 ${anyOpen ? 'opacity-100' : 'opacity-0'}`}>
            {isLoadersOpen && (
              <>
                <div className="flex items-center gap-2 mb-2 text-zinc-100 font-bold text-lg border-b border-zinc-800 pb-4">
                  <FolderOpen className="w-5 h-5 text-cyan-500" />
                  {t('common.sidePanel.loaders')}
                </div>
                <div className="space-y-6">
                  <ConfigLoader />
                  <TubLoader />
                </div>
              </>
            )}

            {isConnectorsOpen && (
              <>
                <div className="flex items-center gap-2 mb-2 text-zinc-100 font-bold text-lg border-b border-zinc-800 pb-4">
                  <Plug className="w-5 h-5 text-cyan-500" />
                  {t('common.sidePanel.connectors')}
                </div>
                <div className="space-y-6">
                  <SimulatorConfig />
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Shared Backdrop */}
      {anyOpen && (
        <div
          className="fixed inset-0 bg-black/20 z-30 backdrop-blur-[1px]"
          onClick={() => setActiveDrawer(null)}
        />
      )}
    </>
  );
};
