import React, { useState } from 'react';
import type { AxiosError } from 'axios';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Button } from './ui/Button';
import { Input } from './ui/Input';
import { useStore } from '../store/useStore';
import { loadTub } from '../services/api';
import { Database, FolderOpen, Search } from 'lucide-react';
import { FileBrowserModal } from './FileBrowserModal';

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
  const [isBrowserOpen, setIsBrowserOpen] = useState(false);

  // Sync local path state with store tubPath (e.g. when auto-loaded by ConfigLoader)
  React.useEffect(() => {
    setPath(tubPath);
  }, [tubPath]);

  const handleManualLoad = async () => {
    if (!path.trim()) return;
    setLoading(true);
    try {
      const data = await loadTub(path);
      setTub(data.path, data.records || [], data.fields || [], data.total_physical_records, data.deleted_indexes);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load tub'));
    } finally {
      setLoading(false);
    }
  };

  const handleBrowserSelect = async (selectedPath: string) => {
    setPath(selectedPath);
    setIsBrowserOpen(false);
    
    setLoading(true);
    try {
      const data = await loadTub(selectedPath);
      setTub(data.path, data.records || [], data.fields || [], data.total_physical_records, data.deleted_indexes);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load tub from selected directory'));
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
          <div className="flex justify-end gap-2">
            <Button 
              variant="secondary"
              onClick={() => setIsBrowserOpen(true)}
              disabled={!config}
              className="min-w-[100px]"
              aria-label="Browse tub directory"
            >
              <Search className="w-4 h-4" />
              Browse
            </Button>
            <Button 
              onClick={handleManualLoad}
              disabled={!config}
              className="min-w-[100px]"
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
      
      <FileBrowserModal 
        isOpen={isBrowserOpen}
        onClose={() => setIsBrowserOpen(false)}
        onSelect={handleBrowserSelect}
        initialPath={path || undefined}
        title="Select Tub Directory"
      />
    </Card>
  );
};
