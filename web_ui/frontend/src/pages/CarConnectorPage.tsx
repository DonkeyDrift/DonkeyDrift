import React, { useEffect, useState, useCallback } from 'react';
import { Card, CardHeader, CardContent } from '../components/ui/Card';
import { SectionCardTitle } from '../components/ui/SectionCardTitle';
import { Button } from '../components/ui/Button';
import { Settings, Upload } from 'lucide-react';
import { Input } from '../components/ui/Input';
import {
  getConnectorConfig,
  setConnectorConfig,
  checkConnectorStatus,
  pushConnectorPilots,
  getApiErrorMessage,
  type ConnectorConfig as ConnectorConfigType,
} from '../services/api';
import { useConnectorJob } from '../hooks/useConnectorJob';
import { useTranslation } from '@/i18n';
import { CarSettingsPanel } from '../components/CarSettingsPanel';

type FormatOption = 'h5' | 'savedmodel' | 'tflite' | 'trt';

const FORMAT_OPTIONS: { key: FormatOption; label: string }[] = [
  { key: 'tflite', label: 'TFLite' },
  { key: 'h5', label: 'H5' },
  { key: 'savedmodel', label: 'SavedModel' },
  { key: 'trt', label: 'TensorRT' },
];

export const CarConnectorPage: React.FC = () => {
  const { t } = useTranslation();

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

  const [selectedFormats, setSelectedFormats] = useState<Set<FormatOption>>(new Set(['tflite']));

  // 扫描车辆发现：车端 IP 的发现/配网由 DC（Drifter Console）负责（issue #177），CC 仅手动填写 host
  // 远程驾驶启停、拉取 Tub 已从本页移除：驾驶控制统一走 Drive 页面（回连地址自动注入）；拉取 Tub 日常无使用（数据走模拟器）

  // 加载配置
  useEffect(() => {
    getConnectorConfig()
      .then((data) => {
        if (data.config) setConfig(data.config);
      })
      .catch(() => {});
  }, []);

  const { isJobRunning, startJob } = useConnectorJob();

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

  return (
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

      <CarSettingsPanel />
    </div>
  );
};
