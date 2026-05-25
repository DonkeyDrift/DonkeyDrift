import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Title,
  Tooltip,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { useStore } from '../store/useStore';
import {
  ArenaModel,
  ArenaPilot,
  ArenaPredictionPoint,
  getArenaPredictions,
  getArenaPreviewUrl,
  listArenaModels,
  listArenaModelTypes,
  loadArenaPilot,
  predictArenaPilot,
  unloadArenaPilot,
  getApiErrorMessage,
} from '../services/api';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

type ViewerState = {
  localId: string;
  modelType: string;
  modelPath: string;
  pilot?: ArenaPilot;
  models: ArenaModel[];
  user?: { angle: number; throttle: number };
  prediction?: { angle: number; throttle: number };
  previewUrl?: string;
  loading: boolean;
  error?: string;
};

const defaultViewer = (): ViewerState => ({
  localId: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
  modelType: 'tflite_linear',
  modelPath: '',
  models: [],
  loading: false,
});

const TRANSFORMATION_OPTIONS = [
  'TRAPEZE',
  'CROP',
  'RGB2BGR',
  'BGR2RGB',
  'RGB2HSV',
  'HSV2RGB',
  'BGR2HSV',
  'HSV2BGR',
  'RGB2GRAY',
  'BGR2GRAY',
  'HSV2GRAY',
  'GRAY2RGB',
  'GRAY2BGR',
  'CANNY',
  'BLUR',
  'RESIZE',
  'SCALE',
];

const formatValue = (value: number | undefined) =>
  value === undefined || Number.isNaN(value) ? '--' : value.toFixed(3);

export const PilotArenaPage: React.FC = () => {
  const configPath = useStore((state) => state.configPath);
  const tubPath = useStore((state) => state.tubPath);
  const records = useStore((state) => state.records);
  const currentIndex = useStore((state) => state.currentIndex);
  const setCurrentIndex = useStore((state) => state.setCurrentIndex);

  const [modelTypes, setModelTypes] = useState<string[]>(['tflite_linear', 'linear']);
  const [columns, setColumns] = useState<1 | 2 | 3 | 4>(2);
  const [viewers, setViewers] = useState<ViewerState[]>([defaultViewer()]);
  const [pageError, setPageError] = useState<string | null>(null);
  const [brightnessEnabled, setBrightnessEnabled] = useState(false);
  const [brightness, setBrightness] = useState(0);
  const [blurEnabled, setBlurEnabled] = useState(false);
  const [blur, setBlur] = useState(1);
  const [preTransformations, setPreTransformations] = useState<string[]>([]);
  const [postTransformations, setPostTransformations] = useState<string[]>([]);
  const [plotPilotId, setPlotPilotId] = useState('');
  const [plotLimit, setPlotLimit] = useState(200);
  const [plotPoints, setPlotPoints] = useState<ArenaPredictionPoint[]>([]);
  const [plotError, setPlotError] = useState<string | null>(null);
  const [plotLoading, setPlotLoading] = useState(false);
  const viewersRef = useRef(viewers);
  const predictionRequestRef = useRef<Record<string, number>>({});

  const currentRecord = records[currentIndex];
  const hasRecords = records.length > 0;
  const predictionOptions = useMemo(() => ({
    preTransformations,
    augmentations: [
      ...(brightnessEnabled ? ['BRIGHTNESS'] : []),
      ...(blurEnabled ? ['BLUR'] : []),
    ],
    postTransformations,
    brightness: brightnessEnabled ? brightness : null,
    blur: blurEnabled ? blur : null,
  }), [preTransformations, postTransformations, brightnessEnabled, brightness, blurEnabled, blur]);
  const gridClass = useMemo(() => {
    const classes = {
      1: 'grid-cols-1',
      2: 'grid-cols-1 xl:grid-cols-2',
      3: 'grid-cols-1 xl:grid-cols-3',
      4: 'grid-cols-1 lg:grid-cols-2 2xl:grid-cols-4',
    };
    return classes[columns];
  }, [columns]);

  useEffect(() => {
    viewersRef.current = viewers;
  }, [viewers]);

  useEffect(() => {
    listArenaModelTypes()
      .then((data) => {
        if (Array.isArray(data.model_types) && data.model_types.length > 0) {
          setModelTypes(data.model_types);
        }
      })
      .catch((error) => setPageError(error?.response?.data?.detail || error.message));
  }, []);

  const updateViewer = useCallback((localId: string, patch: Partial<ViewerState>) => {
    setViewers((items) => items.map((item) => (item.localId === localId ? { ...item, ...patch } : item)));
  }, []);

  const refreshModels = useCallback(async (viewer: ViewerState) => {
    updateViewer(viewer.localId, { loading: true, error: undefined });
    try {
      const data = await listArenaModels({ workingDir: configPath, modelType: viewer.modelType });
      updateViewer(viewer.localId, {
        models: data.models,
        modelPath: data.models[0]?.path || viewer.modelPath,
        loading: false,
      });
    } catch (error) {
      updateViewer(viewer.localId, { loading: false, error: getApiErrorMessage(error) });
    }
  }, [configPath, updateViewer]);

  const refreshPrediction = useCallback(async (viewer: ViewerState, recordIndex: number) => {
    if (!viewer.pilot || !hasRecords) return;
    const requestId = (predictionRequestRef.current[viewer.localId] ?? 0) + 1;
    predictionRequestRef.current[viewer.localId] = requestId;
    updateViewer(viewer.localId, { loading: true, error: undefined });
    try {
      const data = await predictArenaPilot(viewer.pilot.id, {
        record_index: recordIndex,
        config_path: configPath,
        pre_transformations: predictionOptions.preTransformations,
        augmentations: predictionOptions.augmentations,
        post_transformations: predictionOptions.postTransformations,
        brightness: predictionOptions.brightness,
        blur: predictionOptions.blur,
      });
      if (predictionRequestRef.current[viewer.localId] !== requestId) return;
      updateViewer(viewer.localId, {
        user: data.user,
        prediction: data.pilot,
        previewUrl: getArenaPreviewUrl(viewer.pilot.id, { recordIndex, configPath, ...predictionOptions }),
        loading: false,
      });
    } catch (error) {
      if (predictionRequestRef.current[viewer.localId] !== requestId) return;
      updateViewer(viewer.localId, { loading: false, error: getApiErrorMessage(error) });
    }
  }, [configPath, hasRecords, predictionOptions, updateViewer]);

  const loadViewer = useCallback(async (viewer: ViewerState) => {
    if (!viewer.modelPath) {
      updateViewer(viewer.localId, { error: '请选择模型文件' });
      return;
    }

    updateViewer(viewer.localId, { loading: true, error: undefined });
    try {
      const data = await loadArenaPilot({
        model_path: viewer.modelPath,
        model_type: viewer.modelType,
        config_path: configPath,
      });
      const updated = { ...viewer, pilot: data.pilot, loading: false, error: undefined };
      updateViewer(viewer.localId, updated);
      await refreshPrediction(updated, currentIndex);
    } catch (error) {
      updateViewer(viewer.localId, { loading: false, error: getApiErrorMessage(error) });
    }
  }, [configPath, currentIndex, refreshPrediction, updateViewer]);

  const unloadViewer = useCallback(async (viewer: ViewerState) => {
    if (viewer.pilot) {
      try {
        await unloadArenaPilot(viewer.pilot.id);
      } catch {
        // 后端可能已重启，前端仍应允许移除本地状态。
      }
    }
    delete predictionRequestRef.current[viewer.localId];
    setViewers((items) => items.filter((item) => item.localId !== viewer.localId));
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      viewersRef.current.forEach((viewer) => {
        if (viewer.pilot) {
          refreshPrediction(viewer, currentIndex);
        }
      });
    }, 120);
    return () => window.clearTimeout(timer);
  }, [currentIndex, refreshPrediction]);

  const toggleTransformation = (name: string, target: 'pre' | 'post') => {
    const setter = target === 'pre' ? setPreTransformations : setPostTransformations;
    setter((items) => (items.includes(name) ? items.filter((item) => item !== name) : [...items, name]));
  };

  const loadedPilots = viewers.filter((viewer) => viewer.pilot);

  const loadPlot = async () => {
    if (!plotPilotId) {
      setPlotError('请选择已加载的 Pilot');
      return;
    }
    setPlotLoading(true);
    setPlotError(null);
    try {
      const data = await getArenaPredictions(plotPilotId, {
        config_path: configPath,
        start: 0,
        limit: plotLimit,
      });
      setPlotPoints(data.points);
    } catch (error) {
      setPlotError(getApiErrorMessage(error));
    } finally {
      setPlotLoading(false);
    }
  };

  const plotData = {
    labels: plotPoints.map((point) => String(point.index)),
    datasets: [
      {
        label: 'user angle',
        data: plotPoints.map((point) => point.user_angle),
        borderColor: '#22c55e',
        backgroundColor: '#22c55e',
        tension: 0.2,
      },
      {
        label: 'pilot angle',
        data: plotPoints.map((point) => point.pilot_angle),
        borderColor: '#3b82f6',
        backgroundColor: '#3b82f6',
        tension: 0.2,
      },
      {
        label: 'user throttle',
        data: plotPoints.map((point) => point.user_throttle),
        borderColor: '#a3e635',
        backgroundColor: '#a3e635',
        tension: 0.2,
      },
      {
        label: 'pilot throttle',
        data: plotPoints.map((point) => point.pilot_throttle),
        borderColor: '#38bdf8',
        backgroundColor: '#38bdf8',
        tension: 0.2,
      },
    ],
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">Pilot Arena</h1>
          <p className="mt-1 text-sm text-zinc-400">
            并排加载多个 pilot，比较当前 Tub record 的用户控制与模型预测。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={columns}
            onChange={(event) => setColumns(Number(event.target.value) as 1 | 2 | 3 | 4)}
            className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100"
          >
            {[1, 2, 3, 4].map((value) => (
              <option key={value} value={value}>{value} 列</option>
            ))}
          </select>
          <Button onClick={() => setViewers((items) => [...items, defaultViewer()])}>添加 Pilot</Button>
        </div>
      </div>

      {pageError && (
        <div className="rounded-md border border-red-800 bg-red-950/60 px-4 py-3 text-sm text-red-200">
          {pageError}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>当前数据</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-3">
            <div className="rounded-md bg-zinc-950 px-3 py-2 text-zinc-300">Config: {configPath || '未选择'}</div>
            <div className="rounded-md bg-zinc-950 px-3 py-2 text-zinc-300">Tub: {tubPath || '未选择'}</div>
            <div className="rounded-md bg-zinc-950 px-3 py-2 text-zinc-300">Records: {records.length}</div>
          </div>
          <input
            type="range"
            min="0"
            max={Math.max(0, records.length - 1)}
            value={Math.min(currentIndex, Math.max(0, records.length - 1))}
            disabled={!hasRecords}
            onChange={(event) => setCurrentIndex(Number(event.target.value))}
            className="w-full accent-cyan-500"
          />
          <div className="flex flex-wrap gap-3 text-sm text-zinc-400">
            <span>当前序号: {currentIndex}</span>
            <span>Record index: {currentRecord?._index ?? '--'}</span>
            <span>user/angle: {formatValue(Number(currentRecord?.['user/angle']))}</span>
            <span>user/throttle: {formatValue(Number(currentRecord?.['user/throttle']))}</span>
          </div>
        </CardContent>
      </Card>

      {!hasRecords && (
        <div className="rounded-md border border-amber-700 bg-amber-950/40 px-4 py-3 text-sm text-amber-100">
          请先在 Tub Manager 加载 Tub 数据，再进入 Pilot Arena 做模型对比。
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>图像处理</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <label className="space-y-2 text-sm text-zinc-300">
              <span className="flex items-center gap-2">
                <input type="checkbox" checked={brightnessEnabled} onChange={(event) => setBrightnessEnabled(event.target.checked)} />
                Brightness {brightness.toFixed(2)}
              </span>
              <input
                type="range"
                min="-0.5"
                max="0.5"
                step="0.01"
                value={brightness}
                disabled={!brightnessEnabled}
                onChange={(event) => setBrightness(Number(event.target.value))}
                className="w-full accent-cyan-500"
              />
            </label>
            <label className="space-y-2 text-sm text-zinc-300">
              <span className="flex items-center gap-2">
                <input type="checkbox" checked={blurEnabled} onChange={(event) => setBlurEnabled(event.target.checked)} />
                Blur {blur.toFixed(2)}
              </span>
              <input
                type="range"
                min="0.1"
                max="3"
                step="0.1"
                value={blur}
                disabled={!blurEnabled}
                onChange={(event) => setBlur(Number(event.target.value))}
                className="w-full accent-cyan-500"
              />
            </label>
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div>
              <div className="mb-2 text-sm font-medium text-zinc-300">Pre Transformations</div>
              <div className="flex flex-wrap gap-2">
                {TRANSFORMATION_OPTIONS.map((name) => (
                  <button
                    key={`pre-${name}`}
                    type="button"
                    onClick={() => toggleTransformation(name, 'pre')}
                    className={`rounded-md border px-2 py-1 text-xs ${preTransformations.includes(name) ? 'border-cyan-500 bg-cyan-950 text-cyan-200' : 'border-zinc-700 bg-zinc-950 text-zinc-400'}`}
                  >
                    {name}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-2 text-sm font-medium text-zinc-300">Post Transformations</div>
              <div className="flex flex-wrap gap-2">
                {TRANSFORMATION_OPTIONS.map((name) => (
                  <button
                    key={`post-${name}`}
                    type="button"
                    onClick={() => toggleTransformation(name, 'post')}
                    className={`rounded-md border px-2 py-1 text-xs ${postTransformations.includes(name) ? 'border-cyan-500 bg-cyan-950 text-cyan-200' : 'border-zinc-700 bg-zinc-950 text-zinc-400'}`}
                  >
                    {name}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Tub Plot</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_140px_auto]">
            <select
              value={plotPilotId}
              onChange={(event) => setPlotPilotId(event.target.value)}
              className="rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100"
            >
              <option value="">选择已加载 Pilot</option>
              {loadedPilots.map((viewer) => viewer.pilot && (
                <option key={viewer.pilot.id} value={viewer.pilot.id}>{viewer.pilot.name}</option>
              ))}
            </select>
            <input
              type="number"
              min="1"
              max={Math.max(1, records.length)}
              value={plotLimit}
              onChange={(event) => setPlotLimit(Number(event.target.value))}
              className="rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100"
            />
            <Button onClick={loadPlot} disabled={plotLoading || !plotPilotId || !hasRecords}>
              {plotLoading ? '生成中...' : '生成曲线'}
            </Button>
          </div>
          {plotError && (
            <div className="rounded-md border border-red-800 bg-red-950/60 px-3 py-2 text-sm text-red-200">
              {plotError}
            </div>
          )}
          {plotPoints.length > 0 && (
            <div className="rounded-md border border-zinc-800 bg-zinc-950 p-4">
              <Line data={plotData} options={{ responsive: true, plugins: { legend: { labels: { color: '#d4d4d8' } } }, scales: { x: { ticks: { color: '#a1a1aa' } }, y: { ticks: { color: '#a1a1aa' } } } }} />
            </div>
          )}
        </CardContent>
      </Card>

      <div className={`grid gap-4 ${gridClass}`}>
        {viewers.map((viewer) => (
          <Card key={viewer.localId}>
            <CardHeader>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <CardTitle>{viewer.pilot?.name || '未加载 Pilot'}</CardTitle>
                  <p className="mt-1 text-xs text-zinc-500">{viewer.pilot?.model_type || viewer.modelType}</p>
                </div>
                <Button variant="ghost" size="sm" onClick={() => unloadViewer(viewer)}>移除</Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <label className="space-y-1 text-sm">
                  <span className="text-zinc-400">模型类型</span>
                  <select
                    value={viewer.modelType}
                    onChange={(event) => updateViewer(viewer.localId, { modelType: event.target.value, modelPath: '', models: [], pilot: undefined })}
                    className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100"
                  >
                    {modelTypes.map((type) => (
                      <option key={type} value={type}>{type}</option>
                    ))}
                  </select>
                </label>
                <div className="flex items-end">
                  <Button variant="secondary" className="w-full" onClick={() => refreshModels(viewer)} disabled={viewer.loading}>
                    扫描模型
                  </Button>
                </div>
              </div>

              <label className="space-y-1 text-sm block">
                <span className="text-zinc-400">模型文件</span>
                <select
                  value={viewer.modelPath}
                  onChange={(event) => updateViewer(viewer.localId, { modelPath: event.target.value, pilot: undefined })}
                  className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-zinc-100"
                >
                  <option value="">请选择模型</option>
                  {viewer.models.map((model) => (
                    <option key={model.path} value={model.path}>{model.name}</option>
                  ))}
                </select>
              </label>

              <div className="grid grid-cols-2 gap-2">
                <Button onClick={() => loadViewer(viewer)} disabled={viewer.loading || !viewer.modelPath}>加载并预测</Button>
                <Button variant="secondary" onClick={() => refreshPrediction(viewer, currentIndex)} disabled={viewer.loading || !viewer.pilot || !hasRecords}>
                  刷新预测
                </Button>
              </div>

              {viewer.error && (
                <div className="rounded-md border border-red-800 bg-red-950/60 px-3 py-2 text-sm text-red-200">
                  {viewer.error}
                </div>
              )}

              <div className="aspect-video overflow-hidden rounded-md border border-zinc-800 bg-zinc-950 flex items-center justify-center">
                {viewer.previewUrl ? (
                  <img src={viewer.previewUrl} alt="Pilot preview" className="h-full w-full object-contain" />
                ) : (
                  <span className="text-sm text-zinc-500">加载模型后显示叠线预览</span>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-md bg-zinc-950 p-3">
                  <div className="text-xs uppercase text-zinc-500">User</div>
                  <div className="mt-2 font-mono text-green-400">Angle {formatValue(viewer.user?.angle)}</div>
                  <div className="font-mono text-green-400">Throttle {formatValue(viewer.user?.throttle)}</div>
                </div>
                <div className="rounded-md bg-zinc-950 p-3">
                  <div className="text-xs uppercase text-zinc-500">Pilot</div>
                  <div className="mt-2 font-mono text-blue-400">Angle {formatValue(viewer.prediction?.angle)}</div>
                  <div className="font-mono text-blue-400">Throttle {formatValue(viewer.prediction?.throttle)}</div>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
};
