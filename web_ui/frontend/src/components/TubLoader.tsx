import React, { useState } from 'react';
import type { AxiosError } from 'axios';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Button } from './ui/Button';
import { Input } from './ui/Input';
import { useStore } from '../store/useStore';
import { loadTub, selectDirectory } from '../services/api';
import { Database, FolderOpen } from 'lucide-react';

const getErrorMessage = (error: unknown, fallback: string) => {
  if (error && typeof error === 'object' && 'response' in error) {
    const response = (error as AxiosError<{ detail?: string }>).response;
    const detail = response?.data?.detail;
    if (detail) return detail;
  }
  return fallback;
};

export const TubLoader: React.FC = () => {
  const { tubPath, setTub, setError, setLoading, config, totalRecords, fields } = useStore();
  const [path, setPath] = useState(tubPath);

  const handleLoad = async () => {
    setLoading(true);
    try {
      // First open directory picker
      const selectData = await selectDirectory();
      
      if (selectData.path) {
        setPath(selectData.path);
        // Then load tub from selected path
        const data = await loadTub(selectData.path);
        setTub(data.path, data.records || [], data.fields || []);
      }
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to select or load tub'));
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
        <p className="text-sm text-zinc-400">Select tub directory, typically ./data</p>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-3">
          <Input
            placeholder="Tub path, e.g. /home/dkc/projects/mycar/data"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            aria-label="Tub path input field"
          />
          <div className="flex justify-end">
            <Button 
              onClick={handleLoad}
              disabled={!config}
              className="w-[30%] min-w-[100px]"
              aria-label="Load tub"
            >
              <FolderOpen className="w-4 h-4" />
              Load
            </Button>
          </div>
        </div>
        {!config && (
          <p className="text-xs text-yellow-500 mt-2">
            Please load config first
          </p>
        )}
        {config && totalRecords > 0 && (
          <p className="text-xs text-emerald-400 mt-2">
            Success: Loaded {totalRecords} records and {fields.length} fields
          </p>
        )}
        {config && totalRecords === 0 && (
          <p className="text-xs text-zinc-400 mt-2">
            No tub loaded
          </p>
        )}
      </CardContent>
    </Card>
  );
};
