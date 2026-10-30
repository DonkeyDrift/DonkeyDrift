import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader } from './ui/Card';
import { SectionCardTitle } from './ui/SectionCardTitle';
import { Button } from './ui/Button';
import { Input } from './ui/Input';
import { useStore } from '../store/useStore';
import { loadConfig, getApiErrorMessage } from '../services/api';
import { autoLoadTubFor } from '../hooks/useConfigAutoLoad';
import { FolderCog, FolderOpen, Search } from 'lucide-react';
import { FileBrowserModal } from './FileBrowserModal';
import { useTranslation } from '@/i18n';

export const ConfigLoader: React.FC = () => {
  const { t } = useTranslation();
  const { configPath, setConfig, setError, setLoading, config } = useStore();
  const [path, setPath] = useState(configPath);
  const [isBrowserOpen, setIsBrowserOpen] = useState(false);

  // Sync local path state with store configPath
  useEffect(() => {
    setPath(configPath);
  }, [configPath]);

  const handleManualLoad = useCallback(async () => {
    if (!path.trim()) return;
    setLoading(true);
    try {
      const data = await loadConfig(path);
      setConfig(data.config, path);
      await autoLoadTubFor(path);
    } catch (err: unknown) {
      // 任何加载失败（包括目录不存在、缺少 config.py）都要反馈给用户，
      // 否则路径错误时界面毫无提示，只剩控制台里的 404。
      setError(getApiErrorMessage(err, t('common.configLoader.failedToLoad')));
    } finally {
      setLoading(false);
    }
  }, [path, setConfig, setError, setLoading, t]);

  const handleBrowserSelect = async (selectedPath: string) => {
    setPath(selectedPath);
    setIsBrowserOpen(false);
    
    // Auto trigger load
    setLoading(true);
    try {
      const data = await loadConfig(selectedPath);
      setConfig(data.config, selectedPath);
      await autoLoadTubFor(selectedPath);
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, t('common.configLoader.failedToLoadFromDir')));
    } finally {
      setLoading(false);
    }
  };

  // 自动加载逻辑已上移至 App 级 useConfigAutoLoad(见 hooks/):
  // 修复「刷新后直接打开连接器便签页时 ConfigLoader 未挂载、配置显示未配置」——
  // 自动恢复持久化 configPath / 自动发现 mycar 现在随应用常驻,不再依赖抽屉挂载。

  return (
    <Card>
      <CardHeader>
        <SectionCardTitle
          icon={<FolderCog className="w-5 h-5" />}
          title={t('common.configLoader.title')}
          subtitle={t('common.configLoader.hoverSubtitle')}
        />
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
