import React, { useState } from 'react';
import type { AxiosError } from 'axios';
import { Card, CardContent, CardHeader } from './ui/Card';
import { SectionCardTitle } from './ui/SectionCardTitle';
import { Button } from './ui/Button';
import { Input } from './ui/Input';
import { useStore } from '../store/useStore';
import { loadTub, listChildTubs, type ChildTubInfo } from '../services/api';
import { useTranslation } from '@/i18n';
import { Database, FolderOpen, Loader2, Search } from 'lucide-react';
import { FileBrowserModal } from './FileBrowserModal';

const getErrorMessage = (error: unknown, fallback: string) => {
  if (error && typeof error === 'object' && 'response' in error) {
    const response = (error as AxiosError<{ detail?: string }>).response;
    const detail = response?.data?.detail;
    if (detail) return detail;
  }
  return fallback;
};

const formatDateTime = (ms: number | null) => {
  if (ms === null || ms === undefined) return null;
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return null;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
};

export const TubLoader: React.FC = () => {
  const { t } = useTranslation();
  const { tubPath, setTub, setError, setLoading, config, totalRecords, fields } = useStore();
  const [path, setPath] = useState(tubPath);
  const [isBrowserOpen, setIsBrowserOpen] = useState(false);
  // 加载失败后探测到的子 tub 列表（如项目根/data 是全删 tub，真实录制在子目录）
  const [childTubs, setChildTubs] = useState<ChildTubInfo[]>([]);
  const [childLoadingPath, setChildLoadingPath] = useState<string | null>(null);

  // Sync local path state with store tubPath (e.g. when auto-loaded by ConfigLoader)
  React.useEffect(() => {
    setPath(tubPath);
  }, [tubPath]);

  // 手动输入/浏览加载失败后：尝试发现该目录下的子 tub，供点击直接加载
  const probeChildTubs = async (dirPath: string) => {
    try {
      const data = await listChildTubs(dirPath);
      setChildTubs(data.child_tubs || []);
    } catch {
      setChildTubs([]);
    }
  };

  const handleManualLoad = async () => {
    if (!path.trim()) return;
    setLoading(true);
    setChildTubs([]);
    try {
      const data = await loadTub(path);
      setTub(data.path, data.records || [], data.fields || [], data.total_physical_records, data.deleted_indexes);
    } catch (err: unknown) {
      setError(getErrorMessage(err, t('tub.loadFailed')));
      await probeChildTubs(path);
    } finally {
      setLoading(false);
    }
  };

  const handleBrowserSelect = async (selectedPath: string) => {
    setPath(selectedPath);
    setIsBrowserOpen(false);
    setChildTubs([]);

    setLoading(true);
    try {
      const data = await loadTub(selectedPath);
      setTub(data.path, data.records || [], data.fields || [], data.total_physical_records, data.deleted_indexes);
    } catch (err: unknown) {
      setError(getErrorMessage(err, t('tub.loadFailedFromDir')));
      await probeChildTubs(selectedPath);
    } finally {
      setLoading(false);
    }
  };

  // 子 tub 条目点击：按 browser-select 同款流程加载该子 tub
  const handleLoadChildTub = async (child: ChildTubInfo) => {
    setChildLoadingPath(child.path);
    setLoading(true);
    try {
      const data = await loadTub(child.path);
      setTub(data.path, data.records || [], data.fields || [], data.total_physical_records, data.deleted_indexes);
      setChildTubs([]);
    } catch (err: unknown) {
      setError(getErrorMessage(err, t('tub.loadFailedFromDir')));
    } finally {
      setLoading(false);
      setChildLoadingPath(null);
    }
  };

  return (
    <Card>
      <CardHeader>
        <SectionCardTitle
          icon={<Database className="w-5 h-5" />}
          title={t('tub.loaderTitle')}
          subtitle={t('tub.loaderHoverSubtitle')}
        />
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-3">
          <Input
            placeholder={t('tub.pathPlaceholder')}
            value={path}
            onChange={(e) => {
              setPath(e.target.value);
              setChildTubs([]);
            }}
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
        {childTubs.length > 0 && (
          <div className="mt-2 flex flex-col gap-1.5">
            <p className="text-xs text-zinc-400">{t('tub.childTubsFound')}</p>
            <div className="rounded-lg border border-zinc-800 divide-y divide-zinc-800">
              {childTubs.map((child) => {
                const isLoading = childLoadingPath === child.path;
                return (
                  <button
                    key={child.path}
                    type="button"
                    onClick={() => void handleLoadChildTub(child)}
                    disabled={isLoading}
                    className="w-full text-left px-3 py-2 flex items-center justify-between gap-2 transition-colors hover:bg-zinc-800/60"
                  >
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate">{child.name}</div>
                      <div className="text-xs text-zinc-500">
                        {t('tub.childTubFrames', { count: child.record_count })}
                        {formatDateTime(child.last_modified_ms)
                          ? ` · ${formatDateTime(child.last_modified_ms)}`
                          : ''}
                      </div>
                    </div>
                    {isLoading && (
                      <Loader2 className="w-4 h-4 animate-spin text-cyan-400 shrink-0" />
                    )}
                  </button>
                );
              })}
            </div>
          </div>
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
