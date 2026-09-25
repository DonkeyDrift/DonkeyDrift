import React, { useCallback, useEffect, useState } from 'react';
import {
  ArrowUpCircle,
  Bot,
  CheckCircle2,
  Cloud,
  Download,
  MonitorSmartphone,
  RefreshCw,
  Rocket,
  Sparkles,
  Terminal,
  Zap,
} from 'lucide-react';
import { Card, CardContent, CardHeader } from './ui/Card';
import { SectionCardTitle } from './ui/SectionCardTitle';
import { Button } from './ui/Button';
import { useTranslation } from '@/i18n';
import {
  checkHarnessUpdates,
  downloadHarness,
  flashFirmware,
  getHarnessCatalog,
  getHarnessStatus,
  installHarness,
  installHarnessUpdate,
  type HarnessCatalog,
  type HarnessComponent,
  type HarnessInfo,
  type HarnessStatus,
  type HarnessUpdateItem,
} from '../services/api';

// Harness 品牌图标映射（lucide 通用图标，无品牌 logo 依赖）。
const HARNESS_ICONS: Record<string, React.ReactNode> = {
  codex: <Terminal className="h-4 w-4" />,
  claude: <Sparkles className="h-4 w-4" />,
  deepseek: <Cloud className="h-4 w-4" />,
  zcode: <Zap className="h-4 w-4" />,
};

// 进行中的任务集合：下载/安装/更新按各自 key（组件 harness/component、更新项 kind/id）
// 并发跟踪，互不打断；结果提示同样按 key 记录，避免新任务清空其它任务的提示。
type BusySet = ReadonlySet<string>;
type NoticeMap = Record<string, string>;

/**
 * Harness 选择与下载 + 一键更新板块（Issue #404，与 #403 的 AiSettingsPanel 并列）。
 * 数据源：GET /api/harness/catalog（目录+检测）、GET /api/harness/status（后台检查状态）、
 * POST /api/harness/check（一键更新检查）、POST /api/harness/download|install、
 * POST /api/harness/install-update、POST /api/harness/ota/flash。
 */
export const HarnessPanel: React.FC = () => {
  const { t } = useTranslation();
  const [catalog, setCatalog] = useState<HarnessCatalog | null>(null);
  const [status, setStatus] = useState<HarnessStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState<BusySet>(new Set());
  const [notices, setNotices] = useState<NoticeMap>({});

  // 任务开始：标记 busy 并清掉该任务上一次的结果提示（不影响其它任务）。
  const startTask = useCallback((key: string) => {
    setBusy((prev) => new Set(prev).add(key));
    setNotices((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const stopTask = useCallback((key: string) => {
    setBusy((prev) => {
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
  }, []);

  const setTaskNotice = useCallback((key: string, message: string) => {
    setNotices((prev) => ({ ...prev, [key]: message }));
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [cat, st] = await Promise.all([getHarnessCatalog(), getHarnessStatus()]);
      setCatalog(cat);
      setStatus(st);
    } catch {
      // 目录/状态读取失败时保留现有展示，静默跳过
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const runCheck = useCallback(async () => {
    setChecking(true);
    startTask('check');
    try {
      await checkHarnessUpdates();
      await refresh();
    } catch {
      setTaskNotice('check', t('harness.checking') + ' ' + t('harness.manualInstallHint'));
    } finally {
      setChecking(false);
      stopTask('check');
    }
  }, [refresh, startTask, stopTask, setTaskNotice, t]);

  const download = useCallback(
    async (harnessId: string, componentId: string) => {
      const key = harnessId + '/' + componentId;
      startTask(key);
      try {
        const result = await downloadHarness(harnessId, componentId);
        if (result.status === 'open_url' && result.url) {
          window.open(result.url, '_blank', 'noopener,noreferrer');
        }
        setTaskNotice(key, result.message);
      } catch {
        setTaskNotice(key, t('harness.manualInstallHint'));
      } finally {
        stopTask(key);
      }
    },
    [startTask, stopTask, setTaskNotice, t],
  );

  const install = useCallback(
    async (harnessId: string, componentId: string) => {
      const key = harnessId + '/' + componentId;
      startTask(key);
      try {
        const result = await installHarness(harnessId, componentId);
        if (result.status === 'open_url' && result.url) {
          window.open(result.url, '_blank', 'noopener,noreferrer');
        }
        setTaskNotice(key, result.message);
        await refresh();
      } catch {
        setTaskNotice(key, t('harness.manualInstallHint'));
      } finally {
        stopTask(key);
      }
    },
    [refresh, startTask, stopTask, setTaskNotice, t],
  );

  const applyUpdate = useCallback(
    async (item: HarnessUpdateItem) => {
      const key = item.kind + '/' + (item.id ?? item.component_id ?? '');
      startTask(key);
      try {
        if (item.kind === 'harness') {
          await installHarnessUpdate('harness', item.harness_id + '/' + item.component_id);
        } else if (item.kind === 'firmware') {
          const ip = item.vehicle_ip;
          if (!ip) {
            setTaskNotice(key, t('harness.firmware') + ': ' + t('harness.manualInstallHint'));
            return;
          }
          await flashFirmware(ip, item.asset ?? undefined);
        } else {
          await installHarnessUpdate(item.kind, item.id ?? '');
        }
        await refresh();
      } catch {
        setTaskNotice(key, t('harness.manualInstallHint'));
      } finally {
        stopTask(key);
      }
    },
    [refresh, startTask, stopTask, setTaskNotice, t],
  );

  const lastCheckText = status?.last_check_at
    ? t('harness.lastCheck') + ': ' + new Date(status.last_check_at).toLocaleString()
    : t('harness.neverChecked');

  return (
    <Card>
      <CardHeader>
        <SectionCardTitle
          icon={<Rocket className="h-5 w-5" />}
          title={t('harness.title')}
          subtitle={t('harness.subtitle')}
        />
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Harness 列表 */}
        <div className="space-y-3">
          {(catalog?.harnesses ?? []).map((h) => (
            <HarnessGroup
              key={h.id}
              harness={h}
              busy={busy}
              onDownload={download}
              onInstall={install}
            />
          ))}
        </div>

        {/* 一键更新区 */}
        <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="flex items-center gap-2 text-sm font-medium text-zinc-200">
              <Bot className="h-4 w-4" />
              {t('harness.oneClickTitle')}
            </h4>
            <Button onClick={runCheck} disabled={checking} variant="primary" size="sm">
              <RefreshCw className={checking ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
              {checking ? t('harness.checking') : t('harness.checkNow')}
            </Button>
          </div>
          <p className="mt-1 text-xs text-zinc-400">{lastCheckText}</p>

          {(status?.updates ?? []).length === 0 ? (
            <p className="mt-3 text-xs text-zinc-400" data-testid="harness-no-update">
              {t('harness.noUpdate')}
            </p>
          ) : (
            <ul className="mt-3 space-y-2">
              {(status?.updates ?? []).map((item, idx) => (
                <UpdateRow
                  key={item.kind + '-' + (item.id ?? item.component_id ?? idx)}
                  item={item}
                  busy={busy}
                  onApply={applyUpdate}
                />
              ))}
            </ul>
          )}
        </div>

        {Object.keys(notices).length > 0 && (
          <div className="space-y-1" data-testid="harness-notice">
            {Object.entries(notices).map(([key, message]) => (
              <p key={key} className="text-xs text-cyan-200">
                {message}
              </p>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
};

const HarnessGroup: React.FC<{
  harness: HarnessInfo;
  busy: BusySet;
  onDownload: (harnessId: string, componentId: string) => void;
  onInstall: (harnessId: string, componentId: string) => void;
}> = ({ harness, busy, onDownload, onInstall }) => {
  const { t } = useTranslation();
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-3">
      <div className="flex items-center gap-2">
        <span className="text-cyan-400">{HARNESS_ICONS[harness.id] ?? <Bot className="h-4 w-4" />}</span>
        <span className="text-sm font-medium text-zinc-100">{harness.name}</span>
        <span className="text-xs text-zinc-400">· {harness.vendor}</span>
        {harness.remote_default && (
          <span className="ml-auto truncate text-xs text-zinc-400" title={harness.remote_default}>
            {harness.remote_default}
          </span>
        )}
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        {harness.components.map((c) => (
          <ComponentRow
            key={c.id}
            harnessId={harness.id}
            component={c}
            busy={busy}
            onDownload={onDownload}
            onInstall={onInstall}
          />
        ))}
      </div>
    </div>
  );
};

const ComponentRow: React.FC<{
  harnessId: string;
  component: HarnessComponent;
  busy: BusySet;
  onDownload: (harnessId: string, componentId: string) => void;
  onInstall: (harnessId: string, componentId: string) => void;
}> = ({ harnessId, component, busy, onDownload, onInstall }) => {
  const { t } = useTranslation();
  const key = harnessId + '/' + component.id;
  const isBusy = busy.has(key);
  const kindLabel = component.kind === 'desktop' ? t('harness.desktop') : t('harness.cli');
  // 仅当最近一次检查确认有新版本时才显示「更新」；从未检查过（无记录）按无更新处理。
  const hasUpdate = component.installed && component.update_available === true;
  return (
    <div className="flex items-center justify-between gap-2 rounded-md bg-zinc-900 px-3 py-2">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          {component.kind === 'desktop' ? (
            <MonitorSmartphone className="h-3.5 w-3.5 text-zinc-500" />
          ) : (
            <Terminal className="h-3.5 w-3.5 text-zinc-500" />
          )}
          <span className="truncate text-sm text-zinc-200">{component.name}</span>
          <span className="shrink-0 rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400">
            {kindLabel}
          </span>
        </div>
        <p className="mt-0.5 text-xs text-zinc-500">
          {component.installed ? (
            hasUpdate ? (
              <span className="flex items-center gap-1 text-amber-400">
                <ArrowUpCircle className="h-3 w-3" />
                {t('harness.updateAvailable')}
                {component.latest_version
                  ? ' ' + (component.version ? component.version + ' → ' : '') + component.latest_version
                  : ''}
              </span>
            ) : (
              <span className="flex items-center gap-1 text-emerald-400">
                <CheckCircle2 className="h-3 w-3" />
                {t('harness.installed')}
                {component.version ? ' ' + component.version : ''}
              </span>
            )
          ) : (
            <span className="text-zinc-400">{t('harness.notInstalled')}</span>
          )}
        </p>
      </div>
      {component.installed ? (
        hasUpdate && (
          <Button
            onClick={() => onInstall(harnessId, component.id)}
            disabled={isBusy}
            variant="secondary"
            size="sm"
          >
            <Download className="h-3.5 w-3.5" />
            {isBusy ? t('harness.installing') : t('harness.update')}
          </Button>
        )
      ) : (
        <Button
          onClick={() => onDownload(harnessId, component.id)}
          disabled={isBusy}
          variant="primary"
          size="sm"
        >
          <Download className="h-3.5 w-3.5" />
          {isBusy ? t('harness.downloading') : t('harness.download')}
        </Button>
      )}
    </div>
  );
};

const UpdateRow: React.FC<{
  item: HarnessUpdateItem;
  busy: BusySet;
  onApply: (item: HarnessUpdateItem) => void;
}> = ({ item, busy, onApply }) => {
  const { t } = useTranslation();
  const key = item.kind + '/' + (item.id ?? item.component_id ?? '');
  const isBusy = busy.has(key);
  const kindLabel =
    item.kind === 'harness'
      ? t('harness.harnessItem')
      : item.kind === 'project'
        ? t('harness.project')
        : item.kind === 'component'
          ? t('harness.component')
          : t('harness.firmware');
  const canApply = item.kind !== 'harness' || item.component_id;

  return (
    <li className="flex items-center justify-between gap-2 rounded-md bg-zinc-900 px-3 py-2">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400">{kindLabel}</span>
          <span className="truncate text-sm text-zinc-200">{item.name}</span>
        </div>
        <p className="mt-0.5 text-xs text-zinc-400">
          {item.installed_version ? item.installed_version + ' → ' : ''}
          {item.latest_version ?? t('harness.notInstalled')}
          {!item.updateable && <span className="ml-2 text-emerald-400">{t('harness.upToDate')}</span>}
          {item.note && <span className="ml-2 text-zinc-500">{item.note}</span>}
        </p>
      </div>
      {item.updateable && canApply && (
        <Button
          onClick={() => onApply(item)}
          disabled={isBusy}
          variant="primary"
          size="sm"
        >
          {isBusy
            ? t('harness.installing')
            : item.kind === 'firmware'
              ? t('harness.flashFirmware')
              : t('harness.update')}
        </Button>
      )}
    </li>
  );
};
