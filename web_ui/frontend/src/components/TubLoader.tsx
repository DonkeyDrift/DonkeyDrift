import React, { useState } from 'react';
import type { AxiosError } from 'axios';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Button } from './ui/Button';
import { Input } from './ui/Input';
import { useStore } from '../store/useStore';
import { loadTub } from '../services/api';
import { useTranslation } from '@/i18n';
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
  const { t } = useTranslation();
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
      setError(getErrorMessage(err, t('tub.loadFailed')));
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
      setError(getErrorMessage(err, t('tub.loadFailedFromDir')));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Database className="w-5 h-5" />
          {t('tub.loaderTitle')}
        </CardTitle>
        <p className="text-sm text-zinc-400">{t('tub.loaderSubtitle')}</p>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-3">
          <Input
            placeholder={t('tub.pathPlaceholder')}
            value={path}
            onChange={(e) => setPath(e.target.value)}
            aria-label={t('tub.pathInputAria')}
          />
          <div className="flex justify-end gap-2">
            <Button 
              variant="secondary"
              onClick={() => setIsBrowserOpen(true)}
              disabled={!config}
              className="min-w-[100px]"
              aria-label={t('tub.browseAria')}
            >
              <Search className="w-4 h-4" />
              {t('tub.browse')}
            </Button>
            <Button 
              onClick={handleManualLoad}
              disabled={!config}
              className="min-w-[100px]"
              aria-label={t('tub.loadAria')}
            >
              <FolderOpen className="w-4 h-4" />
              {t('tub.load')}
            </Button>
          </div>
        </div>
        {!config && (
          <p className="text-xs text-yellow-500 mt-2">
            {t('tub.loadConfigFirst')}
          </p>
        )}
        {config && totalRecords > 0 && (
          <p className="text-xs text-emerald-400 mt-2">
            {t('tub.loadSuccess', { records: totalRecords, fields: fields.length })}
          </p>
        )}
        {config && totalRecords === 0 && (
          <p className="text-xs text-zinc-400 mt-2">
            {t('tub.noTubLoaded')}
          </p>
        )}
      </CardContent>
      
      <FileBrowserModal 
        isOpen={isBrowserOpen}
        onClose={() => setIsBrowserOpen(false)}
        onSelect={handleBrowserSelect}
        initialPath={path || undefined}
        title={t('tub.selectTubDir')}
      />
    </Card>
  );
};
