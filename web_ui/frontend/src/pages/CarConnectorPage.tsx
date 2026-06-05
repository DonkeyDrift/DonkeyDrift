import React, { useEffect, useState, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import {
  getConnectorConfig,
  setConnectorConfig,
  checkConnectorStatus,
  listConnectorTubs,
  listConnectorModels,
  pullConnectorTub,
  pushConnectorPilots,
  startConnectorDrive,
  stopConnectorDrive,
  getConnectorDriveStatus,
  getApiErrorMessage,
  getDriveCarWebSocketUrl,
  loadTub,
  type ConnectorConfig as ConnectorConfigType,
} from '../services/api';
import { useConnectorJob } from '../hooks/useConnectorJob';
import { useDriveWebsocket } from '../hooks/useDriveWebsocket';
import { useStore } from '../store/useStore';
import { useNavigate } from 'react-router-dom';

type FormatOption = 'h5' | 'savedmodel' | 'tflite' | 'trt';

const FORMAT_OPTIONS: { key: FormatOption; label: string }[] = [
  { key: 'tflite', label: 'TFLite' },
  { key: 'h5', label: 'H5' },
  { key: 'savedmodel', label: 'SavedModel' },
  { key: 'trt', label: 'TensorRT' },
];

const MODEL_TYPES = [
  'tflite_linear',
  'linear',
  'categorical',
  'rnn_lstm',
  'imu',
  '3dconv',
  'latent',
  'transformer',
];

export const CarConnectorPage: React.FC = () => {
  const navigate = useNavigate();
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
  const [remoteModels, setRemoteModels] = useState<string[]>([]);
  const [selectedTub, setSelectedTub] = useState('');
  const [createNewDir, setCreateNewDir] = useState(false);
  const [selectedPilot, setSelectedPilot] = useState('');
  const [modelType, setModelType] = useState('tflite_linear');
  const [bridgeServerUrl, setBridgeServerUrl] = useState(() => getDriveCarWebSocketUrl());
  const [drivePid, setDrivePid] = useState<number | null>(null);
  const [selectedFormats, setSelectedFormats] = useState<Set<FormatOption>>(new Set(['tflite']));

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

  const {
    jobStatus,
    jobProgress,
    jobLogs,
    isJobRunning,
    startJob,
    cancelJob,
  } = useConnectorJob({
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
      setStatusMessage(getApiErrorMessage(error, '连接检查失败'));
    } finally {
      setChecking(false);
    }
  }, []);

  // 加载远端列表
  const loadRemoteLists = useCallback(async () => {
    try {
      const [tubResult, modelResult] = await Promise.all([
        listConnectorTubs(),
        listConnectorModels(),
      ]);
      setTubs(tubResult.items);
      setRemoteModels(modelResult.items);
    } catch (error) {
      setStatusMessage(getApiErrorMessage(error, '远端列表加载失败'));
    }
  }, []);

  useEffect(() => {
    if (online) loadRemoteLists();
  }, [online, loadRemoteLists]);

  const refreshLocalTub = useCallback(async (localTubPath: string) => {
    try {
      const data = await loadTub(localTubPath);
      setTub(data.path, data.records || [], data.fields || [], data.total_physical_records, data.deleted_indexes);
      setStatusMessage(`Tub 已拉取并刷新: ${data.path}`);
    } catch (error) {
      const message = getApiErrorMessage(error, '本地 Tub 刷新失败');
      setStatusMessage(`Tub 已拉取，但本地刷新失败: ${message}`);
      setError(message);
    }
  }, [setTub, setError]);

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

  // 远程启动驾驶
  const handleDriveStart = useCallback(() => {
    startJob(() =>
      startConnectorDrive({
        model_type: selectedPilot ? modelType : undefined,
        pilot: selectedPilot || undefined,
        bridge_server_url: bridgeServerUrl.trim() || undefined,
      }),
    );
  }, [selectedPilot, modelType, bridgeServerUrl, startJob]);

  // 远程停止驾驶
  const handleDriveStop = useCallback(() => {
    startJob(() => stopConnectorDrive({ pid: drivePid ?? undefined }));
  }, [drivePid, startJob]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-zinc-100">Car Connector</h1>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* 左栏 */}
        <div className="space-y-6">
          {/* 连接配置 */}
          <Card>
            <CardHeader>
              <CardTitle>连接配置</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-zinc-400 mb-1">主机地址</label>
                  <Input
                    value={config.host}
                    onChange={(e) => setConfig({ ...config, host: e.target.value })}
                    placeholder="donkeycar.local"
                  />
                </div>
                <div>
                  <label className="block text-xs text-zinc-400 mb-1">用户名</label>
                  <Input
                    value={config.user}
                    onChange={(e) => setConfig({ ...config, user: e.target.value })}
                    placeholder="pi"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-zinc-400 mb-1">SSH 端口</label>
                  <Input
                    type="number"
                    value={config.port}
                    onChange={(e) => setConfig({ ...config, port: parseInt(e.target.value) || 22 })}
                  />
                </div>
                <div>
                  <label className="block text-xs text-zinc-400 mb-1">车端目录</label>
                  <Input
                    value={config.car_dir}
                    onChange={(e) => setConfig({ ...config, car_dir: e.target.value })}
                    placeholder="~/mycar"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs text-zinc-400 mb-1">SSH 密钥路径（可选）</label>
                <Input
                  value={config.key_path || ''}
                  onChange={(e) => setConfig({ ...config, key_path: e.target.value || null })}
                  placeholder="~/.ssh/id_rsa"
                />
              </div>
              <div className="flex items-center gap-3">
                <Button onClick={handleSaveConfig} disabled={configSaving} size="sm">
                  {configSaving ? '保存中...' : '保存配置'}
                </Button>
                <Button onClick={handleCheckStatus} disabled={checking} variant="secondary" size="sm">
                  {checking ? '检查中...' : '检查连接'}
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
              <CardTitle>拉取 Tub</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="block text-xs text-zinc-400 mb-1">选择远端 Tub 目录</label>
                <select
                  className="w-full h-10 rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                  value={selectedTub}
                  onChange={(e) => setSelectedTub(e.target.value)}
                >
                  <option value="">-- 选择 Tub --</option>
                  {tubs.map((t) => (
                    <option key={t} value={t}>
                      {t}
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
                创建新目录（不覆盖现有数据）
              </label>
              <Button
                onClick={handlePullTub}
                disabled={!online || !selectedTub || isJobRunning}
                size="sm"
              >
                拉取 {selectedTub || 'Tub'}
              </Button>
            </CardContent>
          </Card>

          {/* 推送 Pilots */}
          <Card>
            <CardHeader>
              <CardTitle>推送 Pilots</CardTitle>
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
                  一键全选
                </button>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  onClick={handlePushPilots}
                  disabled={!online || isJobRunning || selectedFormats.size === 0}
                  size="sm"
                >
                  推送选中格式（{Array.from(selectedFormats).join(', ')}）
                </Button>
                <Button
                  onClick={handlePushAllPilots}
                  disabled={!online || isJobRunning}
                  variant="secondary"
                  size="sm"
                >
                  同步全部
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
              <CardTitle>远程驾驶</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-zinc-400 mb-1">模型类型</label>
                  <select
                    className="w-full h-10 rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                    value={modelType}
                    onChange={(e) => setModelType(e.target.value)}
                  >
                    {MODEL_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-zinc-400 mb-1">选择 Pilot</label>
                  <select
                    className="w-full h-10 rounded-md border border-zinc-700 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                    value={selectedPilot}
                    onChange={(e) => setSelectedPilot(e.target.value)}
                  >
                    <option value="">无 Pilot（手动驾驶）</option>
                    {remoteModels.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-xs text-zinc-400 mb-1">DriveApiBridge 回连地址</label>
                <Input
                  value={bridgeServerUrl}
                  onChange={(e) => setBridgeServerUrl(e.target.value)}
                  placeholder="ws://你的电脑IP:8000/api/drive/ws"
                />
                <p className="mt-1 text-xs text-zinc-500">
                  车端会使用这个地址连接 Web UI 后端；如果车端在另一台机器，请把 localhost 改成电脑局域网 IP。
                </p>
              </div>
              <div className={`text-xs ${driveConnected && carState.online ? 'text-green-400' : 'text-zinc-500'}`}>
                {driveConnected
                  ? carState.online
                    ? '车端已在线，可直接打开驾驶控制台'
                    : '车端尚未连接 Drive 控制通道'
                  : 'Drive 状态通道连接中...'}
              </div>
              <div className="text-xs text-zinc-400">
                当前远程驾驶 PID: {drivePid ?? '未运行'}
              </div>
              <div className="flex items-center gap-3">
                <Button
                  onClick={handleDriveStart}
                  disabled={!online || isJobRunning}
                  size="sm"
                >
                  启动驾驶
                </Button>
                <Button
                  onClick={handleDriveStop}
                  disabled={!online || isJobRunning}
                  variant="danger"
                  size="sm"
                >
                  停止驾驶
                </Button>
                <Button
                  onClick={() => navigate('/drive')}
                  variant="ghost"
                  size="sm"
                >
                  打开驾驶控制台
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* 任务进度与日志 */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle>
                  {isJobRunning ? '任务进行中' : '任务日志'}
                </CardTitle>
                {isJobRunning && (
                  <Button onClick={cancelJob} variant="danger" size="sm">
                    取消
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {isJobRunning && (
                <div className="w-full bg-zinc-800 rounded-full h-2">
                  <div
                    className="bg-cyan-500 h-2 rounded-full transition-all duration-300"
                    style={{ width: `${jobProgress}%` }}
                  />
                </div>
              )}
              {jobStatus?.status === 'completed' && (
                <div className="text-green-400 text-sm">任务完成</div>
              )}
              {jobStatus?.status === 'failed' && (
                <div className="text-red-400 text-sm">任务失败: {jobStatus.error}</div>
              )}
              <div className="max-h-64 overflow-y-auto space-y-0.5 font-mono text-xs text-zinc-400 bg-zinc-950 rounded p-3">
                {jobLogs.length === 0 && (
                  <div className="text-zinc-600">暂无日志</div>
                )}
                {jobLogs.map((log, i) => (
                  <div key={i}>{log}</div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
};

