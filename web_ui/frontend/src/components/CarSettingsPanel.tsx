import React, { useCallback, useEffect, useRef, useState } from 'react';
import { RefreshCw, Wifi, Wrench } from 'lucide-react';
import { Card, CardHeader, CardContent } from './ui/Card';
import { SectionCardTitle } from './ui/SectionCardTitle';
import { Button } from './ui/Button';
import { discoverConnectorConsoles } from '../services/api';
import { useTranslation } from '@/i18n';

/**
 * 车辆设置（Issue #234 后续）：顶部「连接 + 配网」融合成一个板块——设备发现/选择
 * （连接）+ STA/AP 配网按钮；配网按钮经 postMessage 打开车端 DC 的配网弹窗（弹窗
 * 仍渲染在 iframe 内，1:1 车端 UI）。下方 iframe 用 `?embedded=1&settings=1` 只呈现
 * 车端 DC 的「调校」视图（漂移 / Judge / 摇杆校准），不再显示配网 / OTA / 开发模式
 * / 状态卡；DonkeyDrifter 的 /console 入口保持不变。
 */
export const CarSettingsPanel: React.FC = () => {
  const { t } = useTranslation();
  const [devices, setDevices] = useState<{ ip: string; port: number; reachable: boolean }[]>([]);
  const [scanning, setScanning] = useState(false);
  const [selectedIp, setSelectedIp] = useState('');
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const openWifiSta = useCallback(() => {
    iframeRef.current?.contentWindow?.postMessage({ type: 'dd-open-wifi-sta' }, '*');
  }, []);

  const openWifiAp = useCallback(() => {
    iframeRef.current?.contentWindow?.postMessage({ type: 'dd-open-wifi-ap' }, '*');
  }, []);

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
          <span className="mx-1 h-5 w-px bg-zinc-700" aria-hidden="true" />
          <Button onClick={openWifiSta} disabled={!selectedIp} variant="secondary" size="sm">
            <Wifi className="h-4 w-4" />
            {t('connector.wifiStaButton')}
          </Button>
          <Button onClick={openWifiAp} disabled={!selectedIp} variant="secondary" size="sm">
            {t('connector.wifiApButton')}
          </Button>
        </div>

        {selectedIp ? (
          <div className="min-h-[60vh]">
            <iframe
              ref={iframeRef}
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
