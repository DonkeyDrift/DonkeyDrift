import React from 'react';

interface ModeTabsProps {
  mode: 'local' | 'online';
  onChange: (mode: 'local' | 'online') => void;
}

export const ModeTabs: React.FC<ModeTabsProps> = ({ mode, onChange }) => {
  return (
    <div className="flex bg-zinc-900 rounded-lg p-1 border border-zinc-800">
      <button
        onClick={() => onChange('local')}
        className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
          mode === 'local'
            ? 'bg-cyan-600 text-white'
            : 'text-zinc-400 hover:text-zinc-200'
        }`}
      >
        Local
      </button>
      <button
        onClick={() => onChange('online')}
        className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
          mode === 'online'
            ? 'bg-cyan-600 text-white'
            : 'text-zinc-400 hover:text-zinc-200'
        }`}
      >
        Cloud
      </button>
    </div>
  );
};
