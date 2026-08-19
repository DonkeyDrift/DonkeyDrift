import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, SquareTerminal } from 'lucide-react';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { discoverConnectorConsoles } from '../services/api';
import { consoleGetText } from '../services/console';
import { useTranslation } from '@/i18n';

/**
 * Drifter Console（Issue #234）：先把车端原版 Drifter Console 的 UI 1:1 原样呈现到这里，
 * 后续再按需在 DD 侧改造。此处直接 iframe 加载车端根路径 `http://<ip>/`，
 * 排版与显示功能与车端 Web Console 完全一致，仅保留一条最小的“发现/手动连接”工具条。
 */
export const DrifterConsolePage: React.FC = () => {
  const { t } = useTranslation();
  const [devices, setDevices] = useState<{ ip: string; port: number; reachable: boolean }[]>([]);
  const [scanning, setScanning] = useState(false);
  const [selectedIp, setSelectedIp] = useState('');
  const [manualIp, setManualIp] = useState('');
  const [version, setVersion] = useState('');

  const discover = useCallback(async () => {
    setScanning(true);
    try {
      const result = await discoverConnectorConsoles();
      const found = result.found || [];
      setDevices(found);
      setSelectedIp((prev) => prev || (found.length > 0 ? found[0].ip : ''));
    } catch {
      // 扫描失败时保留现有选择，静默跳过
    } finally {
      setScanning(false);
    }
  }, []);

  useEffect(() => {
    void discover();
  }, [discover]);

  const connectManual = useCallback(() => {
    const ip = manualIp.trim();
    if (!ip) return;
    setSelectedIp(ip);
  }, [manualIp]);

  // 车端固件版本从 /api/status 的 version= 字段读取，显示在工具条“连接”按钮右侧。
  useEffect(() => {
    if (!selectedIp) {
      setVersion('');
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const text = await consoleGetText(selectedIp, 'api/status');
        const m = text.match(/version=(\S+)/);
        if (!cancelled) setVersion(m ? `v${m[1].replace(/^V/i, '')}` : '');
      } catch {
        if (!cancelled) setVersion('');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedIp]);

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      {/* 极简工具条：选择车端 / 重扫 / 手动 IP。只负责“连到哪台车”，不喧宾夺主。 */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-zinc-800 bg-zinc-900/50 px-4 py-2">
        <SquareTerminal className="h-4 w-4 shrink-0 text-cyan-400" />
        <label htmlFor="console-device-select" className="sr-only">
          {t('console.selectDevice')}
        </label>
        <select
          id="console-device-select"
          className="h-9 min-w-[160px] flex-1 rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-cyan-500 sm:flex-none"
          value={selectedIp}
          onChange={(e) => setSelectedIp(e.target.value)}
        >
          {devices.length === 0 && <option value="">{t('console.noDevice')}</option>}
          {devices.map((d) => (
            <option key={d.ip} value={d.ip}>
              {d.ip}
            </option>
          ))}
        </select>
        <Button onClick={discover} disabled={scanning} variant="secondary" size="sm">
          <RefreshCw className={`h-4 w-4 ${scanning ? 'animate-spin' : ''}`} />
          {scanning ? t('console.scanning') : t('console.rescan')}
        </Button>
        <Input
          value={manualIp}
          onChange={(e) => setManualIp(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') connectManual();
          }}
          placeholder="192.168.x.x"
          className="h-9 w-36 sm:w-40"
        />
        <Button onClick={connectManual} variant="secondary" size="sm">
          {t('console.connect')}
        </Button>
        {version && (
          <span className="ml-1 whitespace-nowrap font-mono text-xs text-zinc-400">{version}</span>
        )}
      </div>

      {selectedIp ? (
        <div className="min-h-0 flex-1">
          <iframe
            src={`http://${selectedIp}/?embedded=1`}
            title="Drifter Console"
            className="h-full w-full border-0 bg-zinc-950"
          />
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center bg-zinc-900/30 px-6 text-center text-sm text-zinc-500">
          {t('console.noDevice')}
        </div>
      )}
    </div>
  );
};
