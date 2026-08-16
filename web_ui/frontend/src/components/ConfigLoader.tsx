import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Button } from './ui/Button';
import { Input } from './ui/Input';
import { useStore } from '../store/useStore';
import { loadConfig, loadTub, getApiErrorMessage, discoverProjects } from '../services/api';
import { FolderCog, FolderOpen, Search } from 'lucide-react';
import { FileBrowserModal } from './FileBrowserModal';
import { useTranslation } from '@/i18n';

export const ConfigLoader: React.FC = () => {
  const { t } = useTranslation();
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
      // 任何加载失败（包括目录不存在、缺少 config.py）都要反馈给用户，
      // 否则路径错误时界面毫无提示，只剩控制台里的 404。
      setError(getApiErrorMessage(err, t('common.configLoader.failedToLoad')));
    } finally {
      setLoading(false);
    }
  }, [path, autoLoadTub, setConfig, setError, setLoading, setTub, t]);

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
      setError(getApiErrorMessage(err, t('common.configLoader.failedToLoadFromDir')));
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

  // 没有 remembered configPath 时，若环境中只有一个 mycar 项目则自动
  // browse 并加载（issue #129）；多个项目或扫描失败时回退手动 Browse。
  const autoDiscoverTried = useRef(false);
  useEffect(() => {
    if (config || configPath || autoDiscoverTried.current) return;
    autoDiscoverTried.current = true;
    let cancelled = false;
    (async () => {
      try {
        const data = await discoverProjects();
        if (!cancelled && data.count === 1 && data.projects[0]) {
          await handleBrowserSelect(data.projects[0]);
        }
      } catch {
        // 自动发现失败时保持现状，用户手动 Browse 选择
      }
    })();
    return () => { cancelled = true; };
  }, [config, configPath, handleBrowserSelect]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FolderCog className="w-5 h-5" />
          {t('common.configLoader.title')}
        </CardTitle>
        <p className="text-sm text-zinc-400">{t('common.configLoader.description')}</p>
        <p className="text-xs text-zinc-600">{t('common.configLoader.apiLabel', { origin: window.location.origin })}</p>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-3">
          <Input
            placeholder={t('common.configLoader.pathPlaceholder')}
            value={path}
            onChange={(e) => setPath(e.target.value)}
            aria-label={t('common.configLoader.pathInputAria')}
          />
          <div className="flex justify-end gap-2">
            <Button 
              variant="secondary"
              onClick={() => setIsBrowserOpen(true)}
              className="min-w-[100px]"
              aria-label={t('common.configLoader.browseAria')}
            >
              <Search className="w-4 h-4" />
              {t('common.configLoader.browse')}
            </Button>
            <Button 
              onClick={handleManualLoad}
              className="min-w-[100px]"
              aria-label={t('common.configLoader.loadAria')}
            >
              <FolderOpen className="w-4 h-4" />
              {t('common.configLoader.load')}
            </Button>
          </div>
        </div>
        {config && (
          <p className="mt-3 text-xs text-emerald-400">
            {t('common.configLoader.configLoaded', { path: configPath })}
          </p>
        )}
        {!config && (
          <p className="mt-3 text-xs text-zinc-400">
            {t('common.configLoader.noConfig')}
          </p>
        )}
      </CardContent>
      
      <FileBrowserModal 
        isOpen={isBrowserOpen}
        onClose={() => setIsBrowserOpen(false)}
        onSelect={handleBrowserSelect}
        initialPath={path || undefined}
        title={t('common.configLoader.selectCarDirectory')}
      />
    </Card>
  );
};
