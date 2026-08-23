import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Gamepad2, RefreshCw } from 'lucide-react';
import { Button } from './ui/Button';
import { discoverConnectorConsoles } from '../services/api';
import { useTranslation } from '@/i18n';

/**
 * 车辆设置（Issue #234 后续）：设备发现/选择（连接）+ 内嵌车端 DC 的设置视图。
 * iframe 用 `?embedded=1&settings=1` 同屏呈现车端 1:1 的「RC Channels（置顶常开）/
 * 漂移设置 / Judge 设置（子 iframe 默认展开）」板块——v1.8.64 起不再带 `&wifi=1`，
 * AP 名称配置 / STA Wi-Fi 配置配网板块不在该视图出现（配网仍走车端独立 DC 页的
 * Network ⚙ 入口）；DEV / OTA 不在该视图内。DonkeyDrifter 的 /console 入口保持不变。
 * 外层不再套 Card 与「车辆设置」标题（CC 页整页即是车辆设置，避免与内嵌视图里的
 * 车端「车辆设置」标题重复）——直接渲染选择工具行 + 内嵌视图。
 * 「手柄校准」按钮在本工具行（重新扫描右侧）：点击 postMessage(dd-open-joystick-cal)
 * 到内嵌 iframe，由车端页面打开校准弹窗（沿用 DrifterConsolePage 静音同步同款通道），
 * 因此内嵌视图里的「车辆设置」标题与「调校」行已被车端整行隐藏。
 */
export const CarSettingsPanel: React.FC = () => {
  const { t } = useTranslation();
  const [devices, setDevices] = useState<{ ip: string; port: number; reachable: boolean }[]>([]);
  const [scanning, setScanning] = useState(false);
  const [selectedIp, setSelectedIp] = useState('');
  const iframeRef = useRef<HTMLIFrameElement>(null);

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

  const openJoystickCal = useCallback(() => {
    if (!selectedIp) return;
    iframeRef.current?.contentWindow?.postMessage(
      { type: 'dd-open-joystick-cal' },
      `http://${selectedIp}`,
    );
  }, [selectedIp]);

  return (
    <div className="space-y-3">
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
          {devices.length === 0 && (
            <option value="">{scanning ? t('console.scanning') : t('console.noDevice')}</option>
          )}
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
        <Button
          onClick={openJoystickCal}
          disabled={!selectedIp}
          variant="secondary"
          size="sm"
          title={t('connector.joystickCalHint')}
        >
          <Gamepad2 className="h-4 w-4" />
          {t('connector.joystickCal')}
        </Button>
      </div>

      {selectedIp ? (
        <div className="min-h-[70vh]">
          <iframe
            ref={iframeRef}
            src={`http://${selectedIp}/?embedded=1&settings=1`}
            title={t('connector.carSettingsTitle')}
            className="h-[80vh] min-h-[560px] w-full rounded-md border-0 bg-zinc-950"
          />
        </div>
      ) : (
        <div className="flex h-40 items-center justify-center rounded-md bg-zinc-900/30 text-sm text-zinc-500">
          {scanning ? t('console.scanning') : t('console.noDevice')}
        </div>
      )}
    </div>
  );
};
