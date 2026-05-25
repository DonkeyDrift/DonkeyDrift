import React, { useEffect, useState, useCallback, useRef } from 'react';
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
  getConnectorJobStatus,
  stopConnectorJob,
  createConnectorJobStream,
  getApiErrorMessage,
  getDriveCarWebSocketUrl,
  type ConnectorConfig as ConnectorConfigType,
  type ConnectorJobState,
  type ConnectorJobStatus,
} from '../services/api';
import { useNavigate } from 'react-router-dom';

type FormatOption = 'h5' | 'savedmodel' | 'tflite' | 'trt';

type ConnectorJobEvent = {
  type: 'progress' | 'log' | 'status' | 'drive_pid';
  progress?: number;
  line?: string;
  status?: ConnectorJobState;
  error?: string | null;
};

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

  // 任务状态
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<ConnectorJobStatus | null>(null);
  const [jobProgress, setJobProgress] = useState(0);
  const [jobLogs, setJobLogs] = useState<string[]>([]);
  const eventSourceRef = useRef<EventSource | null>(null);

  // 加载配置
  useEffect(() => {
    getConnectorConfig()
      .then((data) => {
        if (data.config) setConfig(data.config);
      })
      .catch(() => {});
  }, []);

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

  // SSE 订阅任务事件
  const subscribeJobEvents = useCallback((jobId: string) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    const es = createConnectorJobStream(jobId);
    eventSourceRef.current = es;
    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as ConnectorJobEvent;
        if (data.type === 'progress' && typeof data.progress === 'number') {
          setJobProgress(data.progress);
        } else if (data.type === 'log' && data.line) {
          setJobLogs((prev) => [...prev.slice(-199), data.line || '']);
        } else if (data.type === 'status' && data.status) {
          setJobStatus((prev) => (prev ? { ...prev, status: data.status!, error: data.error } : null));
          if (data.status === 'completed') {
            setJobProgress(100);
          }
          if (['completed', 'failed', 'stopped'].includes(data.status)) {
            es.close();
            eventSourceRef.current = null;
          }
        }
      } catch { /* 忽略解析错误 */ }
    };
    es.onerror = () => {
      es.close();
      eventSourceRef.current = null;
      // 回退轮询
      getConnectorJobStatus(jobId).then((status) => {
        setJobStatus(status);
        setJobProgress(status.progress);
        setJobLogs(status.logs);
        if (!['completed', 'failed', 'stopped'].includes(status.status)) {
          const timer = setInterval(async () => {
            const s = await getConnectorJobStatus(jobId);
            setJobStatus(s);
            setJobProgress(s.progress);
            setJobLogs(s.logs);
            if (['completed', 'failed', 'stopped'].includes(s.status)) {
              clearInterval(timer);
            }
          }, 2000);
        }
      }).catch((error) => {
        setJobLogs([`任务状态读取失败: ${getApiErrorMessage(error)}`]);
      });
    };
  }, []);

  // 清理 SSE
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
  }, []);

  // 启动任务后订阅
  const startJobAndSubscribe = useCallback(
    async (action: () => Promise<{ job_id: string; status: ConnectorJobState }>) => {
      setJobLogs([]);
      setJobProgress(0);
      try {
        const result = await action();
        setActiveJobId(result.job_id);
        setJobStatus({ id: result.job_id, kind: '', status: result.status, progress: 0, logs: [], started_at: new Date().toISOString() });
        subscribeJobEvents(result.job_id);
      } catch (err: unknown) {
        setJobLogs([`启动失败: ${getApiErrorMessage(err)}`]);
      }
    },
    [subscribeJobEvents],
  );

  // 拉取 Tub
  const handlePullTub = useCallback(() => {
    if (!selectedTub) return;
    startJobAndSubscribe(() =>
      pullConnectorTub({
        remote_tub: selectedTub,
        local_data_path: './data',
        create_new_dir: createNewDir,
      }),
    );
  }, [selectedTub, createNewDir, startJobAndSubscribe]);

  // 推送 Pilots
  const handlePushPilots = useCallback(() => {
    startJobAndSubscribe(() =>
      pushConnectorPilots({
        local_models_path: './models',
        formats: Array.from(selectedFormats),
      }),
    );
  }, [selectedFormats, startJobAndSubscribe]);

  // 远程启动驾驶
  const handleDriveStart = useCallback(() => {
    startJobAndSubscribe(() =>
      startConnectorDrive({
        model_type: selectedPilot ? modelType : undefined,
        pilot: selectedPilot || undefined,
        bridge_server_url: bridgeServerUrl.trim() || undefined,
      }),
    );
  }, [selectedPilot, modelType, bridgeServerUrl, startJobAndSubscribe]);

  // 远程停止驾驶
  const handleDriveStop = useCallback(() => {
    startJobAndSubscribe(() => stopConnectorDrive());
  }, [startJobAndSubscribe]);

  // 取消任务
  const handleCancelJob = useCallback(async () => {
    if (!activeJobId) return;
    await stopConnectorJob(activeJobId);
  }, [activeJobId]);

  const isJobRunning = jobStatus?.status === 'running' || jobStatus?.status === 'pending';

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
              </div>
              <Button
                onClick={handlePushPilots}
                disabled={!online || isJobRunning}
                size="sm"
              >
                推送 Pilots（{selectedFormats.size ? Array.from(selectedFormats).join(', ') : '全部'}）
              </Button>
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
                  <Button onClick={handleCancelJob} variant="danger" size="sm">
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

