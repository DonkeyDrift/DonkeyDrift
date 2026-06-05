import React, { useState, useEffect } from 'react';
import { browseDirectory, getApiErrorMessage } from '../services/api';
import { Folder, ArrowLeft, X, FolderOpen } from 'lucide-react';
import { Button } from './ui/Button';

interface FileBrowserModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (path: string) => void;
  initialPath?: string;
  title?: string;
}

export const FileBrowserModal: React.FC<FileBrowserModalProps> = ({
  isOpen,
  onClose,
  onSelect,
  initialPath,
  title = "Select Directory"
}) => {
  const [currentPath, setCurrentPath] = useState<string>(initialPath || '');
  const [parentPath, setParentPath] = useState<string | null>(null);
  const [directories, setDirectories] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDirectories = async (path?: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await browseDirectory(path);
      setCurrentPath(data.current);
      setParentPath(data.parent);
      setDirectories(data.directories);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Failed to load directories'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      loadDirectories(initialPath);
    }
  }, [isOpen, initialPath]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/60 z-[100] flex items-center justify-center p-4">
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg shadow-xl w-full max-w-lg flex flex-col overflow-hidden max-h-[90vh] h-[600px]">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-zinc-800 bg-zinc-900/50 shrink-0">
          <h2 className="text-lg font-semibold text-zinc-100 flex items-center gap-2">
            <FolderOpen className="w-5 h-5 text-cyan-500" />
            {title}
          </h2>
          <button
            onClick={onClose}
            className="p-1 hover:bg-zinc-800 rounded text-zinc-400 hover:text-zinc-100 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Current Path */}
        <div className="p-3 bg-zinc-950 border-b border-zinc-800 text-sm font-mono text-cyan-400 break-all shrink-0">
          {currentPath || 'Loading...'}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-2 min-h-0">
          {loading ? (
            <div className="flex justify-center items-center h-full text-zinc-500">
              Loading...
            </div>
          ) : error ? (
            <div className="text-red-400 p-4 text-center">
              {error}
              <div className="mt-4">
                <Button variant="secondary" size="sm" onClick={() => loadDirectories(parentPath || undefined)}>
                  Go Back
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-1">
              {parentPath && (
                <button
                  onClick={() => loadDirectories(parentPath)}
                  className="w-full flex items-center gap-3 p-2 hover:bg-zinc-800 rounded text-left text-zinc-300 transition-colors"
                >
                  <ArrowLeft className="w-4 h-4 text-zinc-500" />
                  <span>..</span>
                </button>
              )}
              {directories.length === 0 && (
                <div className="p-4 text-center text-zinc-500 text-sm">
                  No directories found
                </div>
              )}
              {directories.map(dir => (
                <button
                  key={dir}
                  onClick={() => loadDirectories(`${currentPath}/${dir}`.replace('//', '/'))}
                  className="w-full flex items-center gap-3 p-2 hover:bg-zinc-800 rounded text-left text-zinc-300 transition-colors group"
                >
                  <Folder className="w-4 h-4 text-cyan-600 group-hover:text-cyan-400" />
                  <span>{dir}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-zinc-800 bg-zinc-900/50 flex justify-end gap-3 shrink-0">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button 
            onClick={() => onSelect(currentPath)}
            disabled={loading || !!error || !currentPath}
          >
            Select Current Directory
          </Button>
        </div>
      </div>
    </div>
  );
};
