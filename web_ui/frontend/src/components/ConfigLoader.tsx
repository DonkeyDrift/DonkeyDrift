import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Button } from './ui/Button';
import { Input } from './ui/Input';
import { useStore } from '../store/useStore';
import { loadConfig, loadTub, getApiErrorMessage } from '../services/api';
import { FolderCog, FolderOpen, Search } from 'lucide-react';
import { FileBrowserModal } from './FileBrowserModal';

export const ConfigLoader: React.FC = () => {
  const { configPath, setConfig, setError, setLoading, config, setTub } = useStore();
  const [path, setPath] = useState(configPath);
  const [isBrowserOpen, setIsBrowserOpen] = useState(false);

  // Sync local path state with store configPath
  useEffect(() => {
    setPath(configPath);
  }, [configPath]);

  const autoLoadTub = useCallback(async (carPath: string) => {
    try {
      // Normalize path and append /data
      const tubPath = carPath.endsWith('/') || carPath.endsWith('\\') 
        ? `${carPath}data` 
        : `${carPath}/data`;
      
      const data = await loadTub(tubPath);
      setTub(data.path, data.records || [], data.fields || [], data.total_physical_records, data.deleted_indexes);
    } catch {
      console.warn('Auto-loading tub from ./data failed, user might need to select manually.');
    }
  }, [setTub]);

  const handleManualLoad = useCallback(async () => {
    if (!path.trim()) return;
    setLoading(true);
    try {
      const data = await loadConfig(path);
      setConfig(data.config, path);
      
      const currentTubPath = useStore.getState().tubPath;
      if (currentTubPath && currentTubPath !== '/home/dkc/projects/mycar/data'
          && currentTubPath !== path + '/data'
          && currentTubPath !== path.replace(/\/$/, '') + '/data') {
        try {
          const tubData = await loadTub(currentTubPath);
          setTub(tubData.path, tubData.records || [], tubData.fields || [], tubData.total_physical_records, tubData.deleted_indexes);
        } catch (err) {
          console.warn('Failed to load persisted tub path, falling back to auto-load', err);
          await autoLoadTub(path);
        }
      } else {
        await autoLoadTub(path);
      }
    } catch (err: unknown) {
      const message = getApiErrorMessage(err, 'Failed to load config');
      if (message !== 'Directory not found' && message !== 'config.py not found in directory') {
        setError(message);
      }
    } finally {
      setLoading(false);
    }
  }, [path, autoLoadTub, setConfig, setError, setLoading, setTub]);

  const handleBrowserSelect = async (selectedPath: string) => {
    setPath(selectedPath);
    setIsBrowserOpen(false);
    
    // Auto trigger load
    setLoading(true);
    try {
      const data = await loadConfig(selectedPath);
      setConfig(data.config, selectedPath);
      await autoLoadTub(selectedPath);
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, 'Failed to load config from selected directory'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!config && configPath) {
      // 页面刚加载时服务器可能尚未就绪，先清除旧错误状态
      setError(null);
      // 延迟 500ms 再加载，给后端启动留出时间
      const timer = setTimeout(() => handleManualLoad(), 500);
      return () => clearTimeout(timer);
    }
  }, [config, configPath, handleManualLoad, setError]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FolderCog className="w-5 h-5" />
          Config Loader
        </CardTitle>
        <p className="text-sm text-zinc-400">Select car directory (created via donkey createcar)</p>
        <p className="text-xs text-zinc-600">API: {window.location.origin}/api</p>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-3">
          <Input
            placeholder="Config path, e.g. /home/dkc/projects/mycar"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            aria-label="Config path input field"
          />
          <div className="flex justify-end gap-2">
            <Button 
              variant="secondary"
              onClick={() => setIsBrowserOpen(true)}
              className="min-w-[100px]"
              aria-label="Browse configuration directory"
            >
              <Search className="w-4 h-4" />
              Browse
            </Button>
            <Button 
              onClick={handleManualLoad}
              className="min-w-[100px]"
              aria-label="Load configuration"
            >
              <FolderOpen className="w-4 h-4" />
              Load
            </Button>
          </div>
        </div>
        {config && (
          <p className="mt-3 text-xs text-emerald-400">
            Config loaded: {configPath}
          </p>
        )}
        {!config && (
          <p className="mt-3 text-xs text-zinc-400">
            No config loaded
          </p>
        )}
      </CardContent>
      
      <FileBrowserModal 
        isOpen={isBrowserOpen}
        onClose={() => setIsBrowserOpen(false)}
        onSelect={handleBrowserSelect}
        initialPath={path || undefined}
        title="Select Car Directory"
      />
    </Card>
  );
};
