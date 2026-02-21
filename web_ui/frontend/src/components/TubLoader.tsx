import React, { useState } from 'react';
import type { AxiosError } from 'axios';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Button } from './ui/Button';
import { Input } from './ui/Input';
import { useStore } from '../store/useStore';
import { loadTub } from '../services/api';
import { Database } from 'lucide-react';

const getErrorMessage = (error: unknown, fallback: string) => {
  if (error && typeof error === 'object' && 'response' in error) {
    const response = (error as AxiosError<{ detail?: string }>).response;
    const detail = response?.data?.detail;
    if (detail) return detail;
  }
  return fallback;
};

export const TubLoader: React.FC = () => {
  const { tubPath, setTub, setError, setLoading, config } = useStore();
  const [path, setPath] = useState(tubPath);

  const handleLoad = async () => {
    setLoading(true);
    try {
      const data = await loadTub(path);
      setTub(data.path, data.records || [], data.fields || []);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load tub'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Database className="w-5 h-5" />
          Tub Loader
        </CardTitle>
        <p className="text-sm text-zinc-400">Load tub from within the car directory, typically ./data</p>
      </CardHeader>
      <CardContent>
        <div className="flex gap-4 items-end">
          <div className="flex-1 space-y-2">
            <Input 
              value={path} 
              onChange={(e) => setPath(e.target.value)} 
              placeholder="/home/dkc/projects/mycar/data"
            />
          </div>
          <Button onClick={handleLoad} disabled={!config}>Load tub</Button>
        </div>
        {!config && <p className="text-xs text-yellow-500 mt-2">Please load config first</p>}
      </CardContent>
    </Card>
  );
};
