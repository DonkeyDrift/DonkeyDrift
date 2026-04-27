import React, { useState, useEffect, useCallback } from 'react';
import type { AxiosError } from 'axios';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Button } from './ui/Button';
import { Input } from './ui/Input';
import { useStore } from '../store/useStore';
import { loadConfig, selectDirectory, loadTub } from '../services/api';
import { FolderCog, FolderOpen } from 'lucide-react';

const getErrorMessage = (error: unknown, fallback: string) => {
  if (error && typeof error === 'object' && 'response' in error) {
    const response = (error as AxiosError<{ detail?: string }>).response;
    const detail = response?.data?.detail;
    if (detail) return detail;
  }
  return fallback;
};

export const ConfigLoader: React.FC = () => {
  const { configPath, setConfig, setError, setLoading, config, setTub } = useStore();
  const [path, setPath] = useState(configPath);

  const autoLoadTub = async (carPath: string) => {
    try {
      // Normalize path and append /data
      const tubPath = carPath.endsWith('/') || carPath.endsWith('\\') 
        ? `${carPath}data` 
        : `${carPath}/data`;
      
      const data = await loadTub(tubPath);
      setTub(data.path, data.records || [], data.fields || []);
    } catch (err: unknown) {
      console.warn('Auto-loading tub from ./data failed, user might need to select manually.');
    }
  };

  const handleLoad = useCallback(async () => {
    setLoading(true);
    try {
      // First open directory picker
      const selectData = await selectDirectory();
      
      if (selectData.path) {
        setPath(selectData.path);
        // Then load config from selected path
        const data = await loadConfig(selectData.path);
        setConfig(data.config, selectData.path);
        
        // Auto load tub from ./data
        await autoLoadTub(selectData.path);
      }
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to select or load config'));
    } finally {
      setLoading(false);
    }
  }, [setConfig, setError, setLoading, setTub]);

  const handleManualLoad = async () => {
    setLoading(true);
    try {
      const data = await loadConfig(path);
      setConfig(data.config, path);
      await autoLoadTub(path);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load config'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!config && configPath) {
      handleManualLoad();
    }
  }, [config, configPath]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FolderCog className="w-5 h-5" />
          Config Loader
        </CardTitle>
        <p className="text-sm text-zinc-400">Select car directory, typically ~/mycar</p>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-3">
          <Input
            placeholder="Config path, e.g. /home/dkc/projects/mycar"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            aria-label="Config path input field"
          />
          <div className="flex justify-end">
            <Button 
              onClick={handleLoad}
              className="w-[30%] min-w-[100px]"
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
    </Card>
  );
};
