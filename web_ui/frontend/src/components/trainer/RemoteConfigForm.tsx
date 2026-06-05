import React from 'react';
import { useStore } from '../../store/useStore';

interface RemoteConfigFormProps {
  host: string;
  onHostChange: (v: string) => void;
  user: string;
  onUserChange: (v: string) => void;
  password: string;
  onPasswordChange: (v: string) => void;
  remoteDirBase: string;
  onRemoteDirBaseChange: (v: string) => void;
  modelName: string;
  onModelNameChange: (v: string) => void;
  pythonPath: string;
  onPythonPathChange: (v: string) => void;
}

export const RemoteConfigForm: React.FC<RemoteConfigFormProps> = ({
  host,
  onHostChange,
  user,
  onUserChange,
  password,
  onPasswordChange,
  remoteDirBase,
  onRemoteDirBaseChange,
  modelName,
  onModelNameChange,
  pythonPath,
  onPythonPathChange,
}) => {
  const { configPath } = useStore();

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-4">
      <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">Cloud Training</h3>

      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className="text-xs text-zinc-500">Host</label>
          <input
            type="text"
            value={host}
            onChange={(e) => onHostChange(e.target.value)}
            className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-zinc-500">User</label>
          <input
            type="text"
            value={user}
            onChange={(e) => onUserChange(e.target.value)}
            className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
          />
        </div>
      </div>

      <div className="space-y-1">
        <label className="text-xs text-zinc-500">Password</label>
        <input
          type="password"
          value={password}
          onChange={(e) => onPasswordChange(e.target.value)}
          className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
        />
      </div>

      <div className="space-y-1">
        <label className="text-xs text-zinc-500">Remote Dir Base</label>
        <input
          type="text"
          value={remoteDirBase}
          onChange={(e) => onRemoteDirBaseChange(e.target.value)}
          className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
        />
      </div>

      <div className="space-y-1">
        <label className="text-xs text-zinc-500">Model Name</label>
        <input
          type="text"
          value={modelName}
          onChange={(e) => onModelNameChange(e.target.value)}
          className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
        />
      </div>

      <div className="space-y-1">
        <label className="text-xs text-zinc-500">Python Path</label>
        <input
          type="text"
          value={pythonPath}
          onChange={(e) => onPythonPathChange(e.target.value)}
          className="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-cyan-600"
        />
      </div>

      <div className="text-xs text-zinc-600">Working dir: {configPath}</div>
    </div>
  );
};
