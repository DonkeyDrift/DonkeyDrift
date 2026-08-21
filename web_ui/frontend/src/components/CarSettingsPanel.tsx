import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Wrench } from 'lucide-react';
import { Card, CardHeader, CardContent } from './ui/Card';
import { SectionCardTitle } from './ui/SectionCardTitle';
import { Button } from './ui/Button';
import { discoverConnectorConsoles } from '../services/api';
import { useTranslation } from '@/i18n';

/**
 * 车辆设置（Issue #234 后续）：把车端 Drifter Console 里的设置类功能（Wi-Fi 配网、
 * OTA、开发模式、漂移设置、Judge、摇杆校准等）用 iframe 1:1 嵌入 Car Connector 页面。
 * 与 /console 的 Drifter Console 一样，加载车端根路径，但用 `?embedded=1&settings=1`
 * 只呈现车端 DC 的「设置」视图（配网 / OTA / 开发模式 / 漂移 / Judge / 摇杆校准），
 * 不显示 Mode/Park/Drift/电池等状态卡；设置 UI 与车端 Web Console 完全一致，
 * DonkeyDrifter 的 /console 入口保持不变。
 */
export const CarSettingsPanel: React.FC = () => {
  const { t } = useTranslation();
  const [devices, setDevices] = useState<{ ip: string; port: number; reachable: boolean }[]>([]);
  const [scanning, setScanning] = useState(false);
  const [selectedIp, setSelectedIp] = useState('');

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

  return (
    <Card>
      <CardHeader>
        <SectionCardTitle
          icon={<Wrench className="w-5 h-5" />}
          title={t('connector.carSettingsTitle')}
          subtitle={t('connector.carSettingsSubtitle')}
        />
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="cc-car-settings-select" className="sr-only">
            {t('console.selectDevice')}
          </label>
          <select
            id="cc-car-settings-select"
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
        </div>

        {selectedIp ? (
          <div className="min-h-[60vh]">
            <iframe
              src={`http://${selectedIp}/?embedded=1&settings=1`}
              title={t('connector.carSettingsTitle')}
              className="h-[60vh] w-full rounded-md border-0 bg-zinc-950"
            />
          </div>
        ) : (
          <div className="flex h-40 items-center justify-center rounded-md bg-zinc-900/30 text-sm text-zinc-500">
            {t('console.noDevice')}
          </div>
        )}
      </CardContent>
    </Card>
  );
};
