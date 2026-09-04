import React, { useCallback, useEffect, useState } from 'react';
import { DatabaseBackup } from 'lucide-react';
import { Card, CardContent, CardHeader } from './ui/Card';
import { SectionCardTitle } from './ui/SectionCardTitle';
import { getConnectorConfig, setConnectorAutoSync, checkConnectorStatus } from '../services/api';
import { useTranslation } from '@/i18n';

/**
 * 自动同步 Tub 数据（Issue #167 精简风格的精简板块）：
 * 一个开关 + 最近一次同步时间/结果。开关只切 auto_sync；
 * 自动同步在连接测试成功后由后端自动增量拉取（--update），同一连接防抖不重复触发。
 */
export const AutoSyncPanel: React.FC = () => {
  const { t } = useTranslation();
  const [enabled, setEnabled] = useState(false);
  const [lastSync, setLastSync] = useState<{ at: string | null; result: string | null }>({ at: null, result: null });
  const [toggling, setToggling] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const { config } = await getConnectorConfig();
      setEnabled(!!config.auto_sync);
      setLastSync({ at: config.last_sync_at ?? null, result: config.last_sync_result ?? null });
    } catch {
      // 配置读取失败时保留当前展示，静默跳过
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggle = useCallback(async () => {
    setToggling(true);
    try {
      const result = await setConnectorAutoSync(!enabled);
      setEnabled(result.auto_sync.enabled);
      setLastSync(result.last_sync);
    } catch {
      // 设置失败时保持原状态，静默跳过
    } finally {
      setToggling(false);
    }
  }, [enabled]);

  // 开关打开时轮询状态：后端会在连接成功后自动触发同步，把 last_sync 带回来
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const status = await checkConnectorStatus();
        if (!cancelled) setLastSync(status.last_sync);
      } catch {
        // 状态读取失败时静默跳过
      }
    };
    void poll();
    const timer = window.setInterval(poll, 10000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [enabled]);

  return (
    <Card>
      <CardHeader>
        <SectionCardTitle
          icon={<DatabaseBackup className="h-5 w-5" />}
          title={t('connector.autoSyncTitle')}
          subtitle={t('connector.autoSyncSubtitle')}
        />
      </CardHeader>
      <CardContent>
        <label className="flex cursor-pointer items-center justify-between gap-4">
          <span className="text-sm text-zinc-200">{t('connector.autoSyncToggle')}</span>
          <input
            type="checkbox"
            role="switch"
            aria-checked={enabled}
            aria-label={t('connector.autoSyncToggle')}
            className="h-5 w-9 cursor-pointer appearance-none rounded-full bg-zinc-700 transition-colors checked:bg-cyan-600 relative after:absolute after:top-0.5 after:left-0.5 after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-transform checked:after:translate-x-4"
            checked={enabled}
            disabled={toggling}
            onChange={() => void toggle()}
          />
        </label>
        <p className="mt-3 text-xs text-zinc-500" data-testid="auto-sync-last">
          {lastSync.at
            ? `${t('connector.autoSyncLast')}: ${new Date(lastSync.at).toLocaleString()} — ${lastSync.result ?? ''}`
            : t('connector.autoSyncNever')}
        </p>
      </CardContent>
    </Card>
  );
};
