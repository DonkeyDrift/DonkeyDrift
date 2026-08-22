import React, { useEffect, useState, useCallback } from 'react';
import { Card, CardHeader, CardContent } from '../components/ui/Card';
import { SectionCardTitle } from '../components/ui/SectionCardTitle';
import { Button } from '../components/ui/Button';
import { Car, Download, Settings, Upload } from 'lucide-react';
import { Input } from '../components/ui/Input';
import {
  getConnectorConfig,
  setConnectorConfig,
  checkConnectorStatus,
  listConnectorTubs,
  pullConnectorTub,
  pushConnectorPilots,
  startConnectorDrive,
  stopConnectorDrive,
  getConnectorDriveStatus,
  getApiErrorMessage,
  getDriveCarWebSocketUrl,
  getConnectorLocalIps,
  loadTub,
  type ConnectorConfig as ConnectorConfigType,
} from '../services/api';
import { useConnectorJob } from '../hooks/useConnectorJob';
import { useDriveWebsocket } from '../hooks/useDriveWebsocket';
import { useStore } from '../store/useStore';
import { useTranslation } from '@/i18n';
import { useNavigate } from 'react-router-dom';
import { CarSettingsPanel } from '../components/CarSettingsPanel';

type FormatOption = 'h5' | 'savedmodel' | 'tflite' | 'trt';

const FORMAT_OPTIONS: { key: FormatOption; label: string }[] = [
  { key: 'tflite', label: 'TFLite' },
  { key: 'h5', label: 'H5' },
  { key: 'savedmodel', label: 'SavedModel' },
  { key: 'trt', label: 'TensorRT' },
];

export const CarConnectorPage: React.FC = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { setTub, setError } = useStore();
  const { connected: driveConnected, carState } = useDriveWebsocket();

  // 连接配置
  const [config, setConfig] = useState<ConnectorConfigType>({
    host: '',
    user: 'pi',
    port: 22,
    car_dir: '~/mycar',
    key_path: null,
  });
  const [configSaving, setConfigSaving] = useState(false);

  // 连接状态
  const [online, setOnline] = useState<boolean | null>(null);
  const [statusMessage, setStatusMessage] = useState('');
  const [checking, setChecking] = useState(false);

  // 远端列表
  const [tubs, setTubs] = useState<string[]>([]);
  const [selectedTub, setSelectedTub] = useState('');
  const [createNewDir, setCreateNewDir] = useState(false);
  const [bridgeServerUrl, setBridgeServerUrl] = useState(() => getDriveCarWebSocketUrl());
  const [drivePid, setDrivePid] = useState<number | null>(null);
  const [selectedFormats, setSelectedFormats] = useState<Set<FormatOption>>(new Set(['tflite']));

  // 扫描车辆发现：车端 IP 的发现/配网由 DC（Drifter Console）负责（issue #177），CC 仅手动填写 host

  // 加载配置
  useEffect(() => {
    getConnectorConfig()
      .then((data) => {
        if (data.config) setConfig(data.config);
      })
      .catch(() => {});
  }, []);

  const refreshDriveStatus = useCallback(async () => {
    try {
      const result = await getConnectorDriveStatus();
      setDrivePid(result.pid);
    } catch {
      setDrivePid(null);
    }
  }, []);

  useEffect(() => {
    refreshDriveStatus();
  }, [refreshDriveStatus]);

  // 自动修正 bridgeServerUrl：如果当前是 localhost/127.0.0.1，尝试替换为本机局域网 IP
  useEffect(() => {
    const currentUrl = bridgeServerUrl;
    if (!currentUrl.includes('localhost') && !currentUrl.includes('127.0.0.1')) {
      return;
    }
    getConnectorLocalIps()
      .then((data) => {
        if (data.ips && data.ips.length > 0) {
          const bestIp = data.ips[0].ip;
          const corrected = currentUrl
            .replace('localhost', bestIp)
            .replace('127.0.0.1', bestIp);
          setBridgeServerUrl(corrected);
          setStatusMessage(t('connector.ipAutoCorrected', { ip: bestIp }));
        }
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const { isJobRunning, startJob } = useConnectorJob({
    onDrivePid: setDrivePid,
    onFinished: refreshDriveStatus,
  });

  // 保存配置
  const handleSaveConfig = useCallback(async () => {
    setConfigSaving(true);
    try {
      await setConnectorConfig(config);
    } finally {
      setConfigSaving(false);
    }
  }, [config]);

  // 检查连接
  const handleCheckStatus = useCallback(async () => {
    setChecking(true);
    try {
      const result = await checkConnectorStatus();
      setOnline(result.online);
      setStatusMessage(result.message);
    } catch (error) {
      setOnline(false);
      setStatusMessage(getApiErrorMessage(error, t('connector.checkFailed')));
    } finally {
      setChecking(false);
    }
  }, [t]);

  // 加载远端列表
  const loadRemoteLists = useCallback(async () => {
    try {
      const tubResult = await listConnectorTubs();
      setTubs(tubResult.items);
    } catch (error) {
      setStatusMessage(getApiErrorMessage(error, t('connector.remoteListLoadFailed')));
    }
  }, [t]);

  useEffect(() => {
    if (online) loadRemoteLists();
  }, [online, loadRemoteLists]);

  const refreshLocalTub = useCallback(async (localTubPath: string) => {
    try {
      const data = await loadTub(localTubPath);
      setTub(data.path, data.records || [], data.fields || [], data.total_physical_records, data.deleted_indexes);
      setStatusMessage(t('connector.tubPulledAndRefreshed', { path: data.path }));
    } catch (error) {
      const message = getApiErrorMessage(error, t('connector.localTubRefreshFailed'));
      setStatusMessage(t('connector.tubPulledButRefreshFailed', { message }));
      setError(message);
    }
  }, [setTub, setError, t]);

  // 拉取 Tub
  const handlePullTub = useCallback(() => {
    if (!selectedTub) return;
    const localTubPath = createNewDir ? `./data/${selectedTub}` : './data';
    startJob(
      () =>
        pullConnectorTub({
          remote_tub: selectedTub,
          local_data_path: './data',
          create_new_dir: createNewDir,
        }),
      {
        onCompleted: () => refreshLocalTub(localTubPath),
      },
    );
  }, [selectedTub, createNewDir, refreshLocalTub, startJob]);

  const startPushPilotsJob = useCallback((formats: FormatOption[]) => {
    startJob(() =>
      pushConnectorPilots({
        local_models_path: './models',
        formats,
      }),
    );
  }, [startJob]);

  // 推送 Pilots
  const handlePushPilots = useCallback(() => {
    startPushPilotsJob(Array.from(selectedFormats));
  }, [selectedFormats, startPushPilotsJob]);

  const handlePushAllPilots = useCallback(() => {
    startPushPilotsJob([]);
  }, [startPushPilotsJob]);

  // 远程启动驾驶（模型选择由 Drive 页面的 ModelSelector 负责，这里只负责启停）
  const handleDriveStart = useCallback(() => {
    startJob(() =>
      startConnectorDrive({
        bridge_server_url: bridgeServerUrl.trim() || undefined,
      }),
    );
  }, [bridgeServerUrl, startJob]);

  // 远程停止驾驶
  const handleDriveStop = useCallback(() => {
    startJob(() => stopConnectorDrive({ pid: drivePid ?? undefined }));
  }, [drivePid, startJob]);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* 左栏 */}
        <div className="space-y-6">
          {/* 连接配置 */}
          <Card>
            <CardHeader>
              <SectionCardTitle
                icon={<Settings className="w-5 h-5" />}
                title={t('connector.configTitle')}
                subtitle={t('connector.configTitleSubtitle')}
              />
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-zinc-400 mb-1">{t('connector.hostLabel')}</label>
                  <Input
                    value={config.host}
                    onChange={(e) => setConfig({ ...config, host: e.target.value })}
                    placeholder="donkeycar.local"
                  />
                </div>
                <div>
                  <label className="block text-xs text-zinc-400 mb-1">{t('connector.usernameLabel')}</label>
                  <Input
                    value={config.user}
                    onChange={(e) => setConfig({ ...config, user: e.target.value })}
                    placeholder="pi"
                  />
                </div>
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-zinc-400 mb-1">{t('connector.sshPortLabel')}</label>
                  <Input
                    type="number"
                    value={config.port}
                    onChange={(e) => setConfig({ ...config, port: parseInt(e.target.value) || 22 })}
                  />
                </div>
                <div>
                  <label className="block text-xs text-zinc-400 mb-1">{t('connector.carDirLabel')}</label>
                  <Input
                    value={config.car_dir}
                    onChange={(e) => setConfig({ ...config, car_dir: e.target.value })}
                    placeholder="~/mycar"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs text-zinc-400 mb-1">{t('connector.sshKeyPathLabel')}</label>
                <Input
                  value={config.key_path || ''}
                  onChange={(e) => setConfig({ ...config, key_path: e.target.value || null })}
                  placeholder="~/.ssh/id_rsa"
                />
              </div>
              <div className="flex items-center gap-3">
                <Button onClick={handleSaveConfig} disabled={configSaving} size="sm">
                  {configSaving ? t('connector.saving') : t('connector.saveConfig')}
                </Button>
                <Button onClick={handleCheckStatus} disabled={checking} variant="secondary" size="sm">
                  {checking ? t('connector.checking') : t('connector.checkConnection')}
                </Button>
                {online !== null && (
                  <span
                    className={`text-xs font-medium ${online ? 'text-green-400' : 'text-red-400'}`}
                  >
                    {statusMessage}
                  </span>
                )}
              </div>
            </CardContent>
          </Card>

          {/* 拉取 Tub */}
          <Card>
            <CardHeader>
              <SectionCardTitle
                icon={<Download className="w-5 h-5" />}
                title={t('connector.pullTubTitle')}
                subtitle={t('connector.pullTubTitleSubtitle')}
              />
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="block text-xs text-zinc-400 mb-1">{t('connector.selectRemoteTubLabel')}</label>
                <select
                  className="w-full h-10 rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                  value={selectedTub}
                  onChange={(e) => setSelectedTub(e.target.value)}
                >
                  <option value="">{t('connector.selectTubPlaceholder')}</option>
                  {tubs.map((tub) => (
                    <option key={tub} value={tub}>
                      {tub}
                    </option>
                  ))}
                </select>
              </div>
              <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={createNewDir}
                  onChange={(e) => setCreateNewDir(e.target.checked)}
                  className="rounded border-zinc-600 bg-zinc-800 text-cyan-500 focus:ring-cyan-500"
                />
                {t('connector.createNewDirLabel')}
              </label>
              <Button
                onClick={handlePullTub}
                disabled={!online || !selectedTub || isJobRunning}
                size="sm"
              >
                {t('connector.pullTubButton', { tub: selectedTub || 'Tub' })}
              </Button>
            </CardContent>
          </Card>

          {/* 推送 Pilots */}
          <Card>
            <CardHeader>
              <SectionCardTitle
                icon={<Upload className="w-5 h-5" />}
                title={t('connector.pushPilotsTitle')}
                subtitle={t('connector.pushPilotsTitleSubtitle')}
              />
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap gap-2">
                {FORMAT_OPTIONS.map(({ key, label }) => (
                  <button
                    key={key}
                    onClick={() =>
                      setSelectedFormats((prev) => {
                        const next = new Set(prev);
                        if (next.has(key)) next.delete(key);
                        else next.add(key);
                        return next;
                      })
                    }
                    className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors border ${
                      selectedFormats.has(key)
                        ? 'bg-cyan-600/20 text-cyan-400 border-cyan-500/50'
                        : 'bg-zinc-800 text-zinc-400 border-zinc-700 hover:text-zinc-200'
                    }`}
                  >
                    {label}
                  </button>
                ))}
                <button
                  onClick={() => setSelectedFormats(new Set(FORMAT_OPTIONS.map(({ key }) => key)))}
                  className="px-3 py-1.5 rounded-md text-xs font-medium transition-colors border bg-zinc-800 text-zinc-300 border-zinc-700 hover:text-zinc-100"
                >
                  {t('connector.selectAll')}
                </button>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  onClick={handlePushPilots}
                  disabled={!online || isJobRunning || selectedFormats.size === 0}
                  size="sm"
                >
                  {t('connector.pushSelectedFormats', { formats: Array.from(selectedFormats).join(', ') })}
                </Button>
                <Button
                  onClick={handlePushAllPilots}
                  disabled={!online || isJobRunning}
                  variant="secondary"
                  size="sm"
                >
                  {t('connector.syncAll')}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* 右栏 */}
        <div className="space-y-6">
          {/* 远程驾驶 */}
          <Card>
            <CardHeader>
              <SectionCardTitle
                icon={<Car className="w-5 h-5" />}
                title={t('connector.remoteDriveTitle')}
                subtitle={t('connector.remoteDriveTitleSubtitle')}
              />
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="block text-xs text-zinc-400 mb-1">{t('connector.bridgeUrlLabel')}</label>
                <Input
                  value={bridgeServerUrl}
                  onChange={(e) => setBridgeServerUrl(e.target.value)}
                  placeholder={t('connector.bridgeUrlPlaceholder')}
                />
                <p className="mt-1 text-xs text-zinc-500">
                  {t('connector.bridgeUrlHint')}
                </p>
              </div>
              <div className={`text-xs ${driveConnected && carState.online ? 'text-green-400' : 'text-zinc-500'}`}>
                {driveConnected
                  ? carState.online
                    ? t('connector.carOnline')
                    : t('connector.carNotConnected')
                  : t('connector.driveStatusConnecting')}
              </div>
              <div className="text-xs text-zinc-400">
                {t('connector.drivePidLabel', { pid: drivePid ?? t('connector.notRunning') })}
              </div>
              <div className="flex items-center gap-3">
                <Button
                  onClick={handleDriveStart}
                  disabled={!online || isJobRunning}
                  size="sm"
                >
                  {t('connector.startDrive')}
                </Button>
                <Button
                  onClick={handleDriveStop}
                  disabled={!online || isJobRunning}
                  variant="danger"
                  size="sm"
                >
                  {t('connector.stopDrive')}
                </Button>
                <Button
                  onClick={() => navigate('/drive')}
                  variant="ghost"
                  size="sm"
                >
                  {t('connector.openDriveConsole')}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
      <CarSettingsPanel />
    </div>
  );
};
