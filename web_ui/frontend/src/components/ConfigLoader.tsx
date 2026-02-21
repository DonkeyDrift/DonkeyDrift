import React, { useState } from 'react';
import type { AxiosError } from 'axios';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Button } from './ui/Button';
import { Input } from './ui/Input';
import { useStore } from '../store/useStore';
import { loadConfig } from '../services/api';
import { FolderCog } from 'lucide-react';

const getErrorMessage = (error: unknown, fallback: string) => {
  if (error && typeof error === 'object' && 'response' in error) {
    const response = (error as AxiosError<{ detail?: string }>).response;
    const detail = response?.data?.detail;
    if (detail) return detail;
  }
  return fallback;
};

export const ConfigLoader: React.FC = () => {
  const { configPath, setConfig, setError, setLoading } = useStore();
  const [path, setPath] = useState(configPath);

  const handleLoad = async () => {
    setLoading(true);
    try {
      const data = await loadConfig(path);
      setConfig(data.config, path);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load config'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FolderCog className="w-5 h-5" />
          Config Loader
        </CardTitle>
        <p className="text-sm text-zinc-400">Load config from car directory, typically ~/mycar</p>
      </CardHeader>
      <CardContent>
        <div className="flex gap-4 items-end">
          <div className="flex-1 space-y-2">
            <Input 
              value={path} 
              onChange={(e) => setPath(e.target.value)} 
              placeholder="/home/dkc/projects/mycar"
            />
          </div>
          <Button onClick={handleLoad}>Load config</Button>
        </div>
      </CardContent>
    </Card>
  );
};
