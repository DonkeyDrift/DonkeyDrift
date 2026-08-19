import React, { useCallback, useEffect, useRef, useState } from 'react';
import { RefreshCw, SquareTerminal } from 'lucide-react';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { discoverConnectorConsoles } from '../services/api';
import {
  consoleGetJson,
  consoleGetText,
  consolePostForm,
  consolePostText,
  type ConsoleDevice,
  type ConsoleTelemetry,
} from '../services/console';
import { useTranslation } from '@/i18n';

type LogEntry = { seq: number; t: string; src: string; line: string };

/** 解析车端 /api/status 的 key=value 纯文本（与 DC parseStatusPairs 对齐）。 */
const parseStatusPairs = (text: string): [string, string][] => {
  const pairs: [string, string][] = [];
  for (const line of text.split('\n')) {
    const idx = line.indexOf('=');
    if (idx <= 0) continue;
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim();
    if (!key) continue;
    pairs.push([key, value]);
  }
  return pairs;
};

const MODE_KEYS = ['console.modeManual', 'console.modeAssist', 'console.modeAuto'] as const;

const Stat: React.FC<{ label: string; value: React.ReactNode; accent?: string }> = ({
  label,
  value,
  accent,
}) => (
  <div className="rounded-md border border-zinc-800 bg-zinc-950/50 px-3 py-2">
    <div className="text-[11px] text-zinc-500">{label}</div>
    <div className={`mt-0.5 font-mono text-sm ${accent ?? 'text-zinc-100'}`}>{value}</div>
  </div>
);

export const DrifterConsolePage: React.FC = () => {
  const { t } = useTranslation();
  const [devices, setDevices] = useState<ConsoleDevice[]>([]);
  const [scanning, setScanning] = useState(false);
  const [selectedIp, setSelectedIp] = useState('');
  const [manualIp, setManualIp] = useState('');
  const [connected, setConnected] = useState(false);
  const [statusPairs, setStatusPairs] = useState<[string, string][]>([]);
  const [telemetry, setTelemetry] = useState<ConsoleTelemetry | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [cmd, setCmd] = useState('');
  const [cmdTarget, setCmdTarget] = useState<'web' | 'serial'>('web');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');

  const [wifi, setWifi] = useState<{
    ssid?: string;
    connected?: boolean;
    sta_ip?: string;
    password_set?: boolean;
    password_len?: number;
  } | null>(null);
  const [wifiNetworks, setWifiNetworks] = useState<
    { ssid: string; rssi: number; channel: number; secure: boolean }[]
  >([]);
  const [wifiSsid, setWifiSsid] = useState('');
  const [wifiPassword, setWifiPassword] = useState('');
  const [wifiScanning, setWifiScanning] = useState(false);
  const [wifiConnecting, setWifiConnecting] = useState(false);
  const [wifiNotice, setWifiNotice] = useState('');
  const [devMode, setDevMode] = useState<boolean | null>(null);
  const [muted, setMuted] = useState<boolean | null>(null);
  const [otaFile, setOtaFile] = useState<File | null>(null);
  const [otaUploading, setOtaUploading] = useState(false);
  const [otaMessage, setOtaMessage] = useState('');

  const lastDataSeqRef = useRef(0);
  const lastLogSeqRef = useRef(0);

  const discover = useCallback(async () => {
    setScanning(true);
    try {
      const result = await discoverConnectorConsoles();
      const found = result.found || [];
      setDevices(found);
      setSelectedIp((prev) => prev || (found.length > 0 ? found[0].ip : ''));
      setError('');
    } catch {
      setError(t('console.noDevice'));
    } finally {
      setScanning(false);
    }
  }, [t]);

  const fetchStatus = useCallback(async (ip: string) => {
    try {
      const text = await consoleGetText(ip, 'api/status');
      setStatusPairs(parseStatusPairs(text));
      setConnected(true);
      setError('');
    } catch {
      setConnected(false);
    }
  }, []);

  const fetchTelemetry = useCallback(async (ip: string) => {
    try {
      const data = await consoleGetJson<{ latest?: ConsoleTelemetry }>(
        ip,
        `api/data?since=${lastDataSeqRef.current}`,
      );
      if (data.latest) {
        lastDataSeqRef.current = Math.max(lastDataSeqRef.current, Number(data.latest.seq || 0));
        setTelemetry(data.latest);
      }
    } catch {
      // 遥测轮询是高频操作，单次失败静默跳过，避免抖动连接状态
    }
  }, []);

  const fetchLog = useCallback(async (ip: string) => {
    try {
      const data = await consoleGetJson<{ entries: LogEntry[] }>(
        ip,
        `api/log?since=${lastLogSeqRef.current}`,
      );
      const entries = data.entries || [];
      if (entries.length === 0) return;
      const appended = entries.map((e) => `[${e.t}][${e.src}] ${e.line}`);
      for (const e of entries) {
        lastLogSeqRef.current = Math.max(lastLogSeqRef.current, Number(e.seq || 0));
      }
      setLogs((prev) => [...prev, ...appended].slice(-500));
    } catch {
      // 日志轮询失败静默跳过
    }
  }, []);

  const loadSystemState = useCallback(async (ip: string) => {
    try {
      const data = await consoleGetJson<{ enabled?: boolean }>(ip, 'api/devmode');
      setDevMode(!!data.enabled);
    } catch {
      setDevMode(null);
    }
    try {
      const data = await consoleGetJson<{ muted?: number | boolean }>(ip, 'api/mute');
      setMuted(data.muted === 1 || data.muted === true);
    } catch {
      setMuted(null);
    }
  }, []);

  const loadWifiSta = useCallback(async (ip: string) => {
    try {
      const data = await consoleGetJson<{
        ssid?: string;
        connected?: boolean;
        sta_ip?: string;
        password_set?: boolean;
        password_len?: number;
      }>(ip, 'api/wifi-sta');
      setWifi(data);
      setWifiSsid((prev) => prev || data.ssid || '');
    } catch {
      setWifi(null);
    }
  }, []);

  // 选择车端后持续轮询状态/遥测/日志，并加载一次系统/网络状态
  useEffect(() => {
    if (!selectedIp) return;
    void loadSystemState(selectedIp);
    void loadWifiSta(selectedIp);
    let cancelled = false;
    const runStatus = () => { if (!cancelled) void fetchStatus(selectedIp); };
    const runTelemetry = () => { if (!cancelled) void fetchTelemetry(selectedIp); };
    const runLog = () => { if (!cancelled) void fetchLog(selectedIp); };
    runStatus();
    runTelemetry();
    runLog();
    const timers = [
      window.setInterval(runStatus, 3000),
      window.setInterval(runTelemetry, 500),
      window.setInterval(runLog, 1000),
    ];
    return () => {
      cancelled = true;
      timers.forEach((id) => window.clearInterval(id));
    };
  }, [selectedIp, fetchStatus, fetchTelemetry, fetchLog, loadSystemState, loadWifiSta]);

  // 进入页面先扫描一次车端
  useEffect(() => {
    void discover();
  }, [discover]);

  const connectManual = useCallback(() => {
    const ip = manualIp.trim();
    if (!ip) return;
    setSelectedIp(ip);
  }, [manualIp]);

  const sendCommand = useCallback(async () => {
    const value = cmd.trim();
    if (!value || !selectedIp) return;
    setSending(true);
    try {
      await consolePostText(selectedIp, `api/cmd?target=${encodeURIComponent(cmdTarget)}`, value);
      setCmd('');
      window.setTimeout(() => {
        void fetchStatus(selectedIp);
        void fetchLog(selectedIp);
      }, 200);
    } catch (e) {
      setError(t('console.sendFailed', { message: e instanceof Error ? e.message : String(e) }));
    } finally {
      setSending(false);
    }
  }, [cmd, cmdTarget, selectedIp, fetchStatus, fetchLog, t]);

  const scanWifi = useCallback(async () => {
    if (!selectedIp || wifiScanning) return;
    setWifiScanning(true);
    setWifiNotice('');
    try {
      const data = await consoleGetJson<{
        networks?: { ssid: string; rssi: number; channel: number; secure: boolean }[];
        scanning?: boolean;
      }>(selectedIp, 'api/wifi-sta/scan');
      const nets = (data.networks || []).sort((a, b) => (b.rssi || -999) - (a.rssi || -999));
      setWifiNetworks(nets);
      if (nets.length === 0) setWifiNotice(t('console.wifiNoNetworks'));
    } catch {
      setWifiNotice(t('console.wifiNoNetworks'));
    } finally {
      setWifiScanning(false);
    }
  }, [selectedIp, wifiScanning, t]);

  const connectWifi = useCallback(async () => {
    const ssid = wifiSsid.trim();
    if (!ssid || !selectedIp) return;
    setWifiConnecting(true);
    setWifiNotice('');
    try {
      const form = new URLSearchParams();
      form.set('ssid', ssid);
      form.set('source', 'web');
      form.set('password', wifiPassword);
      await consolePostForm(selectedIp, 'api/wifi-sta', form);
      setWifiPassword('');
      await loadWifiSta(selectedIp);
      void fetchStatus(selectedIp);
    } catch (e) {
      setWifiNotice(e instanceof Error ? e.message : String(e));
    } finally {
      setWifiConnecting(false);
    }
  }, [selectedIp, wifiSsid, wifiPassword, loadWifiSta, fetchStatus]);

  const toggleDevMode = useCallback(async () => {
    if (!selectedIp || devMode === null) return;
    try {
      await consolePostText(selectedIp, 'api/devmode', devMode ? '0' : '1');
      setDevMode(!devMode);
      void fetchStatus(selectedIp);
    } catch {
      // 失败时下一轮 loadSystemState 会校正状态
    }
  }, [selectedIp, devMode, fetchStatus]);

  const toggleMute = useCallback(async () => {
    if (!selectedIp || muted === null) return;
    try {
      await consolePostForm(selectedIp, 'api/mute', new URLSearchParams({ muted: muted ? '0' : '1' }));
      setMuted(!muted);
    } catch {
      // 失败时下一轮 loadSystemState 会校正状态
    }
  }, [selectedIp, muted]);

  const uploadOta = useCallback(async () => {
    if (!selectedIp || !otaFile) {
      setOtaMessage(t('console.otaNoFile'));
      return;
    }
    setOtaUploading(true);
    setOtaMessage('');
    try {
      const form = new FormData();
      form.append('update', otaFile);
      const text = await consolePostForm(selectedIp, 'update', form);
      setOtaMessage(text || t('console.otaSuccess'));
    } catch (e) {
      setOtaMessage(t('console.otaFailed', { message: e instanceof Error ? e.message : String(e) }));
    } finally {
      setOtaUploading(false);
    }
  }, [selectedIp, otaFile, t]);

  const modeLabel = (mode?: number) => {
    if (mode === undefined) return '--';
    const key = MODE_KEYS[mode] ?? 'console.modeUnknown';
    return t(key);
  };

  const driftModeLabel = (dtm?: number) => {
    if (dtm === 2) return t('console.driftModeSpin');
    if (dtm === 1) return t('console.driftModePulse');
    return t('console.driftModePass');
  };

  const driftValue = (telemetry: ConsoleTelemetry | null) => {
    if (!telemetry) return '--';
    if (!telemetry.de) return t('console.valueOff');
    return telemetry.da ? t('console.valueActive') : t('console.valueArmed');
  };

  const fmt = (v: unknown, digits = 0) =>
    v === undefined || v === null || Number.isNaN(Number(v)) ? '--' : Number(v).toFixed(digits);

  return (
    <div className="space-y-6">
      {/* 顶部：设备选择 + 连接控制 */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <SquareTerminal className="w-4 h-4 text-cyan-400" />
            <CardTitle>{t('console.title')}</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[220px] flex-1">
              <label className="block text-xs text-zinc-400 mb-1">{t('console.selectDevice')}</label>
              <select
                className="w-full h-10 rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-cyan-500"
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
            </div>
            <Button onClick={discover} disabled={scanning} variant="secondary" size="sm">
              <RefreshCw className={`w-4 h-4 ${scanning ? 'animate-spin' : ''}`} />
              {scanning ? t('console.scanning') : t('console.rescan')}
            </Button>
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs text-zinc-400 mb-1">{t('console.manualIp')}</label>
              <div className="flex gap-2">
                <Input
                  value={manualIp}
                  onChange={(e) => setManualIp(e.target.value)}
                  placeholder="192.168.x.x"
                />
                <Button onClick={connectManual} variant="secondary" size="sm">
                  {t('console.connect')}
                </Button>
              </div>
            </div>
          </div>
          <div className={`text-xs font-medium ${connected ? 'text-green-400' : 'text-zinc-500'}`}>
            {connected ? t('console.connected') : t('console.disconnected')}
          </div>
          {error && <div className="text-xs text-red-400 break-all">{error}</div>}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* 状态 */}
        <Card>
          <CardHeader>
            <CardTitle>{t('console.statusTitle')}</CardTitle>
          </CardHeader>
          <CardContent>
            {statusPairs.length === 0 ? (
              <div className="text-sm text-zinc-500">{t('console.disconnected')}</div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
                {statusPairs.map(([k, v]) => (
                  <div key={k} className="flex items-baseline justify-between border-b border-zinc-800/60 py-1">
                    <span className="text-xs text-zinc-400">{k}</span>
                    <span className="font-mono text-sm text-zinc-100 break-all text-right">{v}</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* 遥测 */}
        <Card>
          <CardHeader>
            <CardTitle>{t('console.telemetryTitle')}</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <Stat label={t('console.mode')} value={modeLabel(telemetry?.mode)} />
            <Stat
              label={t('console.park')}
              value={telemetry?.park ? t('console.valueLocked') : t('console.valueUnlocked')}
              accent={telemetry?.park ? 'text-amber-400' : 'text-green-400'}
            />
            <Stat label={t('console.drift')} value={driftValue(telemetry)} />
            <Stat label={t('console.voltage')} value={`${fmt(telemetry?.vol, 2)} V`} />
            <Stat label={t('console.throttle')} value={fmt(telemetry?.thr)} />
            <Stat label={t('console.steering')} value={fmt(telemetry?.str)} />
            <Stat label={t('console.gyroZ')} value={fmt(telemetry?.gz, 3)} />
            <Stat label={t('console.servoDuty')} value={fmt(telemetry?.sd)} />
            <Stat label={t('console.escDuty')} value={fmt(telemetry?.ed)} />
            <Stat label={t('console.servoMid')} value={fmt(telemetry?.sm)} />
            <Stat label={t('console.motorMid')} value={fmt(telemetry?.mm)} />
            <Stat label={t('console.driftComp')} value={fmt(telemetry?.dc, 2)} />
            <Stat label={t('console.driftYawErr')} value={fmt(telemetry?.dye, 2)} />
            <Stat label={t('console.driftThrottleMode')} value={driftModeLabel(telemetry?.dtm)} />
            <div className="col-span-2 sm:col-span-3 rounded-md border border-zinc-800 bg-zinc-950/50 px-3 py-2">
              <div className="text-[11px] text-zinc-500 mb-1">{t('console.channels')}</div>
              <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 font-mono text-xs text-zinc-100">
                {[1, 2, 3, 4, 5, 6].map((n) => (
                  <div key={n}>
                    <span className="text-zinc-500">CH{n}</span> {fmt(telemetry?.[`ch${n}`])}
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* Wi-Fi 配置 */}
        <Card>
          <CardHeader>
            <CardTitle>{t('console.wifiTitle')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2 items-end">
              <div className="flex-1 min-w-[180px]">
                <label className="block text-xs text-zinc-400 mb-1">{t('console.wifiSsid')}</label>
                <Input
                  value={wifiSsid}
                  onChange={(e) => setWifiSsid(e.target.value)}
                  placeholder="SSID"
                />
              </div>
              <div className="flex-1 min-w-[180px]">
                <label className="block text-xs text-zinc-400 mb-1">{t('console.wifiPassword')}</label>
                <Input
                  type="password"
                  value={wifiPassword}
                  onChange={(e) => setWifiPassword(e.target.value)}
                  placeholder="••••••"
                />
              </div>
              <Button onClick={scanWifi} disabled={wifiScanning} variant="secondary" size="sm">
                {wifiScanning ? t('console.wifiScanning') : t('console.wifiScan')}
              </Button>
              <Button onClick={connectWifi} disabled={wifiConnecting || !wifiSsid.trim()} size="sm">
                {wifiConnecting ? t('console.wifiConnecting') : t('console.wifiConnect')}
              </Button>
            </div>
            <div className={`text-xs font-medium ${wifi?.connected ? 'text-green-400' : 'text-zinc-500'}`}>
              {wifi?.connected
                ? t('console.wifiConnected', { ip: wifi?.sta_ip || '' })
                : t('console.wifiDisconnected')}
            </div>
            {wifiNotice && <div className="text-xs text-red-400 break-all">{wifiNotice}</div>}
            {wifiNetworks.length > 0 && (
              <div className="max-h-48 overflow-y-auto rounded-md border border-zinc-800 divide-y divide-zinc-800/70">
                {wifiNetworks.map((n) => (
                  <button
                    key={n.ssid}
                    type="button"
                    onClick={() => setWifiSsid(n.ssid)}
                    className="w-full text-left px-3 py-2 hover:bg-zinc-800/60 flex items-center justify-between gap-2"
                  >
                    <span className="text-sm text-zinc-100 truncate">{n.ssid}</span>
                    <span className="text-xs text-zinc-500 whitespace-nowrap">
                      {n.rssi} dBm CH{n.channel}
                      {n.secure ? '' : ' OPEN'}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-6">
          {/* OTA 固件升级 */}
          <Card>
            <CardHeader>
              <CardTitle>{t('console.otaTitle')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <input
                type="file"
                accept=".bin"
                onChange={(e) => setOtaFile(e.target.files?.[0] ?? null)}
                className="block w-full text-sm text-zinc-300 file:mr-3 file:rounded-md file:border-0 file:bg-cyan-600 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-white hover:file:bg-cyan-700"
              />
              <Button onClick={uploadOta} disabled={otaUploading || !otaFile} size="sm">
                {otaUploading ? t('console.otaUploading') : t('console.otaUpload')}
              </Button>
              {otaMessage && <div className="text-xs break-all text-zinc-300">{otaMessage}</div>}
            </CardContent>
          </Card>

          {/* 系统开关 */}
          <Card>
            <CardHeader>
              <CardTitle>{t('console.devModeTitle')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-zinc-300">{t('console.devModeTitle')}</span>
                <button
                  type="button"
                  onClick={toggleDevMode}
                  disabled={devMode === null}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium border transition-colors disabled:opacity-50 ${
                    devMode
                      ? 'bg-cyan-600/20 text-cyan-400 border-cyan-500/50'
                      : 'bg-zinc-800 text-zinc-400 border-zinc-700 hover:text-zinc-200'
                  }`}
                >
                  {devMode ? t('console.devModeEnabled') : t('console.devModeDisabled')}
                </button>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-zinc-300">{t('console.muteTitle')}</span>
                <button
                  type="button"
                  onClick={toggleMute}
                  disabled={muted === null}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium border transition-colors disabled:opacity-50 ${
                    muted
                      ? 'bg-cyan-600/20 text-cyan-400 border-cyan-500/50'
                      : 'bg-zinc-800 text-zinc-400 border-zinc-700 hover:text-zinc-200'
                  }`}
                >
                  {muted ? t('console.muteOn') : t('console.muteOff')}
                </button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* 终端 + 日志 */}
      <Card>
        <CardHeader>
          <CardTitle>{t('console.terminalTitle')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Input
              value={cmd}
              onChange={(e) => setCmd(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !sending) void sendCommand();
              }}
              placeholder={t('console.commandPlaceholder')}
              className="flex-1 min-w-[220px] font-mono"
            />
            <select
              className="h-10 rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-cyan-500"
              value={cmdTarget}
              onChange={(e) => setCmdTarget(e.target.value as 'web' | 'serial')}
              aria-label={t('console.target')}
            >
              <option value="web">{t('console.targetWeb')}</option>
              <option value="serial">{t('console.targetSerial')}</option>
            </select>
            <Button onClick={sendCommand} disabled={sending || !selectedIp || !cmd.trim()} size="sm">
              {t('console.send')}
            </Button>
          </div>
          <div>
            <div className="text-xs text-zinc-400 mb-1">{t('console.logTitle')}</div>
            <div className="max-h-64 overflow-y-auto rounded-md bg-zinc-950 border border-zinc-800 p-3 font-mono text-xs text-zinc-300 space-y-0.5">
              {logs.length === 0 && <div className="text-zinc-600">{t('console.logEmpty')}</div>}
              {logs.map((line, i) => (
                <div key={i} className="break-all whitespace-pre-wrap">
                  {line}
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
