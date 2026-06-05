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
  getImageUrl,
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
  prediction?: { angle: number; throttle: number };
  lastEvaluatedIndex?: number;
  playbackFps: number;
  inferenceFps: number;
  loading: boolean;
  error?: string;
};

const defaultViewer = (): ViewerState => ({
  localId: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
  modelType: 'tflite_linear',
  modelPath: '',
  models: [],
  playbackFps: 0,
  inferenceFps: 0,
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

const ARENA_IMAGE_CACHE_LIMIT = 40;
const ARENA_IMAGE_MAX_IN_FLIGHT = 1;
const ARENA_IMAGE_MIN_INTERVAL_MS = 16;
const ARENA_PREDICTION_MIN_INTERVAL_MS = 250;
const ARENA_BATCH_PREFETCH_MIN_INTERVAL_MS = 1000;

const formatValue = (value: number | undefined) =>
  value === undefined || Number.isNaN(value) ? '--' : value.toFixed(3);

const getRecordImagePath = (record: Record<string, unknown> | undefined) => {
  if (!record) return null;
  const imageKey = Object.keys(record).find((key) => key.endsWith('image_array') || key === 'cam/image' || key === 'image');
  const imagePath = imageKey ? record[imageKey] : null;
  return typeof imagePath === 'string' ? imagePath : null;
};

const drawControlLine = (ctx: CanvasRenderingContext2D, angle: number | undefined, throttle: number | undefined, color: string) => {
  if (angle === undefined || throttle === undefined || Number.isNaN(angle) || Number.isNaN(throttle)) return;
  const { width, height } = ctx.canvas;
  const startX = width / 2;
  const startY = height - 1;
  const endX = startX + Math.max(-1, Math.min(1, angle)) * width * 0.4;
  const endY = startY - Math.max(-1, Math.min(1, throttle)) * height * 0.6;
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(2, width / 160);
  ctx.beginPath();
  ctx.moveTo(startX, startY);
  ctx.lineTo(endX, endY);
  ctx.stroke();
};

const getRecordUserControl = (record: Record<string, unknown> | undefined) => {
  if (!record) return undefined;
  return {
    angle: Number(record['user/angle']),
    throttle: Number(record['user/throttle']),
  };
};

export const PilotArenaPage: React.FC = () => {
  const configPath = useStore((state) => state.configPath);
  const tubPath = useStore((state) => state.tubPath);
  const records = useStore((state) => state.records);
  const currentIndex = useStore((state) => state.currentIndex);
  const setCurrentIndex = useStore((state) => state.setCurrentIndex);
  const config = useStore((state) => state.config);
  const isPlaying = useStore((state) => state.isPlaying);
  const setIsPlaying = useStore((state) => state.setIsPlaying);
  const isLooping = useStore((state) => state.isLooping);
  const setIsLooping = useStore((state) => state.setIsLooping);

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
  const [imageProcessingCollapsed, setImageProcessingCollapsed] = useState(true);
  const [displayRecordIndex, setDisplayRecordIndex] = useState(currentIndex);
  const viewersRef = useRef(viewers);
  const predictionRequestRef = useRef<Record<string, number>>({});
  const predictionInFlightRef = useRef<Record<string, boolean>>({});
  const predictionInFlightCountRef = useRef<Record<string, number>>({});
  const predictionBatchInFlightRef = useRef<Record<string, boolean>>({});
  const predictionLastRequestAtRef = useRef<Record<string, number>>({});
  const predictionBatchLastRequestAtRef = useRef<Record<string, number>>({});
  const pendingViewerIndexRef = useRef<Record<string, number>>({});
  const pendingBatchStartRef = useRef<Record<string, number>>({});
  const predictionCacheRef = useRef<Record<string, Record<number, { pilot: { angle: number; throttle: number } }>>>({});
  const canvasRefs = useRef<Record<string, HTMLCanvasElement | null>>({});
  const imageCacheRef = useRef<Map<string, HTMLImageElement>>(new Map());
  const imageLoadCallbacksRef = useRef<Map<string, Map<string, (image: HTMLImageElement) => void>>>(new Map());
  const imageInFlightRef = useRef<Set<string>>(new Set());
  const lastImageRequestAtRef = useRef(0);
  const playbackFpsStartRef = useRef<Record<string, number>>({});
  const playbackFpsFramesRef = useRef<Record<string, number>>({});
  const inferenceFpsStartRef = useRef<Record<string, number>>({});
  const inferenceFpsFramesRef = useRef<Record<string, number>>({});
  const playbackFrameRef = useRef<number>();
  const lastPlaybackTimeRef = useRef(0);
  const lastPlaybackSyncTimeRef = useRef(0);
  const lastDisplaySyncTimeRef = useRef(0);
  const currentIndexRef = useRef(currentIndex);
  const isPlayingRef = useRef(isPlaying);
  const isLoopingRef = useRef(isLooping);
  const evaluationTimerRef = useRef<number>();
  const lastEvaluationAtRef = useRef(0);

  const displayRecord = records[displayRecordIndex];
  const displayUserControl = getRecordUserControl(displayRecord);
  const hasRecords = records.length > 0;
  const maxIndex = Math.max(0, records.length - 1);
  const playbackSpeed = 1000 / Math.max(1, Number(config?.DRIVE_LOOP_HZ) || 60);
  const evaluationIntervalMs = Math.max(playbackSpeed, ARENA_PREDICTION_MIN_INTERVAL_MS);
  const maxInferenceConcurrency = Math.max(1, Math.min(2, Number(config?.ARENA_INFERENCE_CONCURRENCY) || 1));
  const prefetchFrameCount = Math.max(0, Math.min(8, Number(config?.ARENA_PREFETCH_FRAMES) || 0));
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
    currentIndexRef.current = currentIndex;
    if (!isPlayingRef.current) {
      setDisplayRecordIndex(currentIndex);
    }
  }, [currentIndex]);

  useEffect(() => {
    isPlayingRef.current = isPlaying;
    if (!isPlaying) {
      lastPlaybackTimeRef.current = 0;
    }
  }, [isPlaying]);

  useEffect(() => {
    isLoopingRef.current = isLooping;
  }, [isLooping]);

  useEffect(() => {
    imageCacheRef.current.clear();
  }, [tubPath]);

  useEffect(() => {
    if (!hasRecords && isPlaying) {
      setIsPlaying(false);
    }
  }, [hasRecords, isPlaying, setIsPlaying]);

  useEffect(() => {
    setDisplayRecordIndex((index) => Math.max(0, Math.min(maxIndex, index)));
  }, [maxIndex]);

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

  const updateFps = useCallback((localId: string, kind: 'playback' | 'inference', frameCount = 1) => {
    const startRef = kind === 'playback' ? playbackFpsStartRef : inferenceFpsStartRef;
    const framesRef = kind === 'playback' ? playbackFpsFramesRef : inferenceFpsFramesRef;
    const now = window.performance.now();
    if (!startRef.current[localId]) {
      startRef.current[localId] = now;
    }
    framesRef.current[localId] = (framesRef.current[localId] ?? 0) + frameCount;
    const elapsed = now - startRef.current[localId];
    if (elapsed >= 1000) {
      const fps = Math.round((framesRef.current[localId] * 1000) / elapsed);
      updateViewer(localId, kind === 'playback' ? { playbackFps: fps } : { inferenceFps: fps });
      startRef.current[localId] = now;
      framesRef.current[localId] = 0;
    }
  }, [updateViewer]);

  const cacheImage = useCallback((imageUrl: string, onLoadKey?: string, onLoad?: (image: HTMLImageElement) => void) => {
    const cachedImage = imageCacheRef.current.get(imageUrl);
    if (cachedImage) {
      if (onLoadKey && onLoad && !cachedImage.complete) {
        const callbacks = imageLoadCallbacksRef.current.get(imageUrl) ?? new Map<string, (image: HTMLImageElement) => void>();
        callbacks.set(onLoadKey, onLoad);
        imageLoadCallbacksRef.current.set(imageUrl, callbacks);
      }
      imageCacheRef.current.delete(imageUrl);
      imageCacheRef.current.set(imageUrl, cachedImage);
      return cachedImage;
    }
    const now = window.performance.now();
    if (imageInFlightRef.current.size >= ARENA_IMAGE_MAX_IN_FLIGHT || now - lastImageRequestAtRef.current < ARENA_IMAGE_MIN_INTERVAL_MS) {
      return undefined;
    }
    lastImageRequestAtRef.current = now;

    const image = new Image();
    imageInFlightRef.current.add(imageUrl);
    if (onLoadKey && onLoad) {
      imageLoadCallbacksRef.current.set(imageUrl, new Map([[onLoadKey, onLoad]]));
    }
    image.onload = () => {
      imageInFlightRef.current.delete(imageUrl);
      const callbacks = imageLoadCallbacksRef.current.get(imageUrl);
      callbacks?.forEach((callback) => callback(image));
      imageLoadCallbacksRef.current.delete(imageUrl);
    };
    image.onerror = () => {
      imageInFlightRef.current.delete(imageUrl);
      imageLoadCallbacksRef.current.delete(imageUrl);
      imageCacheRef.current.delete(imageUrl);
    };
    image.src = imageUrl;
    imageCacheRef.current.set(imageUrl, image);
    while (imageCacheRef.current.size > ARENA_IMAGE_CACHE_LIMIT) {
      const oldestUrl = imageCacheRef.current.keys().next().value;
      if (!oldestUrl) break;
      const oldestImage = imageCacheRef.current.get(oldestUrl);
      if (oldestImage) {
        oldestImage.onload = null;
        oldestImage.onerror = null;
        oldestImage.src = '';
      }
      imageLoadCallbacksRef.current.delete(oldestUrl);
      imageInFlightRef.current.delete(oldestUrl);
      imageCacheRef.current.delete(oldestUrl);
    }
    return image;
  }, []);

  const cachePilotPrediction = useCallback((localId: string, recordIndex: number, pilot: { angle: number; throttle: number }) => {
    predictionCacheRef.current[localId] = {
      ...(predictionCacheRef.current[localId] ?? {}),
      [recordIndex]: { pilot },
    };
    const cachedIndexes = Object.keys(predictionCacheRef.current[localId]).map(Number).sort((a, b) => a - b);
    while (cachedIndexes.length > 300) {
      const indexToDelete = cachedIndexes.shift();
      if (indexToDelete !== undefined) {
        delete predictionCacheRef.current[localId][indexToDelete];
      }
    }
  }, []);

  const clearViewerPredictionState = useCallback((localId: string) => {
    delete predictionRequestRef.current[localId];
    delete predictionInFlightRef.current[localId];
    delete predictionInFlightCountRef.current[localId];
    delete predictionBatchInFlightRef.current[localId];
    delete predictionLastRequestAtRef.current[localId];
    delete predictionBatchLastRequestAtRef.current[localId];
    delete pendingViewerIndexRef.current[localId];
    delete pendingBatchStartRef.current[localId];
    delete predictionCacheRef.current[localId];
  }, []);

  const drawViewerFrame = useCallback((viewer: ViewerState, recordIndex: number) => {
    const canvas = canvasRefs.current[viewer.localId];
    const record = records[recordIndex];
    const imagePath = getRecordImagePath(record);
    if (!canvas || !imagePath) return;
    const imageUrl = getImageUrl(imagePath, tubPath);
    const draw = (imageToDraw: HTMLImageElement) => {
      if (imageToDraw.naturalWidth === 0) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      if (canvas.width !== imageToDraw.width || canvas.height !== imageToDraw.height) {
        canvas.width = imageToDraw.width;
        canvas.height = imageToDraw.height;
      }
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(imageToDraw, 0, 0);
      const userControl = getRecordUserControl(record);
      const cachedPrediction = predictionCacheRef.current[viewer.localId]?.[recordIndex];
      drawControlLine(ctx, userControl?.angle, userControl?.throttle, '#22c55e');
      drawControlLine(ctx, cachedPrediction?.pilot.angle ?? viewer.prediction?.angle, cachedPrediction?.pilot.throttle ?? viewer.prediction?.throttle, '#3b82f6');
    };
    const image = cacheImage(imageUrl, viewer.localId, (loadedImage) => {
      if (currentIndexRef.current === recordIndex) {
        draw(loadedImage);
      }
    });
    if (image?.complete) {
      draw(image);
    }
  }, [cacheImage, records, tubPath]);

  useEffect(() => {
    if (!isPlaying || !hasRecords) return;

    const animate = (time: number) => {
      if (!isPlayingRef.current) return;
      if (lastPlaybackTimeRef.current === 0) {
        lastPlaybackTimeRef.current = time;
      }

      const deltaTime = time - lastPlaybackTimeRef.current;
      if (deltaTime >= playbackSpeed) {
        const steps = Math.floor(deltaTime / playbackSpeed);
        const previousIndex = currentIndexRef.current;
        let advancedFrames = steps;
        let nextIndex = previousIndex + steps;
        if (nextIndex > maxIndex) {
          if (isLoopingRef.current && records.length > 0) {
            nextIndex %= records.length;
          } else {
            advancedFrames = Math.max(0, maxIndex - previousIndex);
            nextIndex = maxIndex;
            setIsPlaying(false);
          }
        }
        currentIndexRef.current = nextIndex;
        if (advancedFrames > 0) {
          viewersRef.current.forEach((viewer) => updateFps(viewer.localId, 'playback', advancedFrames));
        }
        if (time - lastDisplaySyncTimeRef.current > 120 || nextIndex === maxIndex) {
          setDisplayRecordIndex(nextIndex);
          lastDisplaySyncTimeRef.current = time;
        }
        if (time - lastPlaybackSyncTimeRef.current > 250 || nextIndex === maxIndex) {
          setCurrentIndex(nextIndex);
          lastPlaybackSyncTimeRef.current = time;
        }
        lastPlaybackTimeRef.current = time - (deltaTime % playbackSpeed);
      }

      viewersRef.current.forEach((viewer) => drawViewerFrame(viewer, currentIndexRef.current));
      playbackFrameRef.current = window.requestAnimationFrame(animate);
    };

    playbackFrameRef.current = window.requestAnimationFrame(animate);
    return () => {
      if (playbackFrameRef.current !== undefined) {
        window.cancelAnimationFrame(playbackFrameRef.current);
      }
    };
  }, [drawViewerFrame, hasRecords, isPlaying, maxIndex, playbackSpeed, records.length, setCurrentIndex, setIsPlaying, updateFps]);

  useEffect(() => {
    if (!hasRecords || isPlaying) return;
    viewersRef.current.forEach((viewer) => drawViewerFrame(viewer, currentIndex));
  }, [currentIndex, drawViewerFrame, hasRecords, isPlaying, viewers]);

  const refreshModels = useCallback(async (viewer: ViewerState) => {
    clearViewerPredictionState(viewer.localId);
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
  }, [clearViewerPredictionState, configPath, updateViewer]);

  const refreshPrediction = useCallback(async (
    viewer: ViewerState,
    recordIndex: number,
    options: { playback?: boolean; force?: boolean } = {},
  ) => {
    if (!viewer.pilot || !hasRecords) return;
    const inFlightCount = predictionInFlightCountRef.current[viewer.localId] ?? 0;
    const now = window.performance.now();
    if (options.playback) {
      if (inFlightCount >= maxInferenceConcurrency || now - (predictionLastRequestAtRef.current[viewer.localId] ?? 0) < ARENA_PREDICTION_MIN_INTERVAL_MS) {
        pendingViewerIndexRef.current[viewer.localId] = recordIndex;
        return;
      }
      predictionLastRequestAtRef.current[viewer.localId] = now;
    }

    predictionInFlightRef.current[viewer.localId] = true;
    predictionInFlightCountRef.current[viewer.localId] = inFlightCount + 1;
    const requestId = (predictionRequestRef.current[viewer.localId] ?? 0) + 1;
    predictionRequestRef.current[viewer.localId] = requestId;
    if (!options.playback) {
      updateViewer(viewer.localId, { loading: true, error: undefined });
    }
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
      if (!options.playback && predictionRequestRef.current[viewer.localId] !== requestId) return;
      updateFps(viewer.localId, 'inference');
      cachePilotPrediction(viewer.localId, recordIndex, data.pilot);
      const patch: Partial<ViewerState> = {
        prediction: data.pilot,
        lastEvaluatedIndex: recordIndex,
        loading: false,
      };
      updateViewer(viewer.localId, patch);
    } catch (error) {
      if (!options.playback && predictionRequestRef.current[viewer.localId] !== requestId) return;
      if (!options.playback) {
        updateViewer(viewer.localId, { loading: false, error: getApiErrorMessage(error) });
      }
    } finally {
      const nextInFlightCount = Math.max(0, (predictionInFlightCountRef.current[viewer.localId] ?? 1) - 1);
      predictionInFlightCountRef.current[viewer.localId] = nextInFlightCount;
      predictionInFlightRef.current[viewer.localId] = nextInFlightCount > 0;
      const pendingIndex = pendingViewerIndexRef.current[viewer.localId];
      if (options.playback && pendingIndex === recordIndex) {
        delete pendingViewerIndexRef.current[viewer.localId];
      }
    }
  }, [cachePilotPrediction, configPath, hasRecords, maxInferenceConcurrency, predictionOptions, updateFps, updateViewer]);

  const prefetchPredictions = useCallback(async (viewer: ViewerState, start: number, limit: number) => {
    if (!viewer.pilot || !hasRecords || limit <= 0) return;
    const now = window.performance.now();
    if (
      predictionBatchInFlightRef.current[viewer.localId]
      || now - (predictionBatchLastRequestAtRef.current[viewer.localId] ?? 0) < ARENA_BATCH_PREFETCH_MIN_INTERVAL_MS
    ) {
      pendingBatchStartRef.current[viewer.localId] = start;
      return;
    }

    predictionBatchLastRequestAtRef.current[viewer.localId] = now;
    predictionBatchInFlightRef.current[viewer.localId] = true;
    try {
      const data = await getArenaPredictions(viewer.pilot.id, {
        config_path: configPath,
        start,
        limit,
        pre_transformations: predictionOptions.preTransformations,
        augmentations: predictionOptions.augmentations,
        post_transformations: predictionOptions.postTransformations,
        brightness: predictionOptions.brightness,
        blur: predictionOptions.blur,
      });
      let inferredFrames = 0;
      data.points.forEach((point, offset) => {
        const recordIndex = start + offset;
        if (recordIndex < 0 || recordIndex > maxIndex) return;
        const existing = predictionCacheRef.current[viewer.localId]?.[recordIndex];
        cachePilotPrediction(viewer.localId, recordIndex, { angle: point.pilot_angle, throttle: point.pilot_throttle });
        if (!existing) inferredFrames += 1;
      });
      if (inferredFrames > 0) {
        updateFps(viewer.localId, 'inference', inferredFrames);
      }
      const currentPrediction = predictionCacheRef.current[viewer.localId]?.[currentIndexRef.current];
      if (currentPrediction) {
        updateViewer(viewer.localId, {
          prediction: currentPrediction.pilot,
          lastEvaluatedIndex: currentIndexRef.current,
          loading: false,
        });
      }
    } catch (error) {
      updateViewer(viewer.localId, { error: getApiErrorMessage(error) });
    } finally {
      predictionBatchInFlightRef.current[viewer.localId] = false;
      delete pendingBatchStartRef.current[viewer.localId];
    }
  }, [cachePilotPrediction, configPath, hasRecords, maxIndex, predictionOptions, updateFps, updateViewer]);

  const loadViewer = useCallback(async (viewer: ViewerState) => {
    if (!viewer.modelPath) {
      updateViewer(viewer.localId, { error: '请选择模型文件' });
      return;
    }

    clearViewerPredictionState(viewer.localId);
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
  }, [clearViewerPredictionState, configPath, currentIndex, refreshPrediction, updateViewer]);

  const unloadViewer = useCallback(async (viewer: ViewerState) => {
    if (viewer.pilot) {
      try {
        await unloadArenaPilot(viewer.pilot.id);
      } catch {
        // 后端可能已重启，前端仍应允许移除本地状态。
      }
    }
    clearViewerPredictionState(viewer.localId);
    imageLoadCallbacksRef.current.forEach((callbacks) => callbacks.delete(viewer.localId));
    delete canvasRefs.current[viewer.localId];
    setViewers((items) => items.filter((item) => item.localId !== viewer.localId));
  }, [clearViewerPredictionState]);

  const evaluateLoadedViewers = useCallback((recordIndex: number, playback = false) => {
    viewersRef.current.forEach((viewer) => {
      if (!viewer.pilot) return;
      const pendingIndex = pendingViewerIndexRef.current[viewer.localId];
      const targetIndex = playback && pendingIndex !== undefined ? pendingIndex : recordIndex;
      const cachedPrediction = predictionCacheRef.current[viewer.localId]?.[targetIndex];
      if (cachedPrediction) {
        updateViewer(viewer.localId, {
          prediction: cachedPrediction.pilot,
          lastEvaluatedIndex: targetIndex,
        });
      } else {
        if (pendingIndex === targetIndex) {
          delete pendingViewerIndexRef.current[viewer.localId];
        }
        refreshPrediction(viewer, targetIndex, { playback });
      }

      if (playback) {
        const prefetchStart = Math.min(maxIndex, recordIndex + 1);
        const prefetchLimit = Math.min(prefetchFrameCount, maxIndex - prefetchStart + 1);
        if (prefetchLimit > 0) {
          void prefetchPredictions(viewer, prefetchStart, prefetchLimit);
        }
      }
    });
  }, [maxIndex, prefetchFrameCount, prefetchPredictions, refreshPrediction, updateViewer]);

  useEffect(() => {
    if (isPlaying) return;
    const timer = window.setTimeout(() => {
      evaluateLoadedViewers(currentIndex, false);
    }, 120);
    return () => window.clearTimeout(timer);
  }, [currentIndex, evaluateLoadedViewers, isPlaying]);

  useEffect(() => {
    if (!isPlaying) return;

    const scheduleEvaluation = (delay: number) => {
      evaluationTimerRef.current = window.setTimeout(() => {
        lastEvaluationAtRef.current = window.performance.now();
        evaluateLoadedViewers(currentIndexRef.current, true);
        scheduleEvaluation(evaluationIntervalMs);
      }, delay);
    };

    const now = window.performance.now();
    const elapsed = now - lastEvaluationAtRef.current;
    scheduleEvaluation(Math.max(0, evaluationIntervalMs - elapsed));

    return () => {
      if (evaluationTimerRef.current !== undefined) {
        window.clearTimeout(evaluationTimerRef.current);
      }
    };
  }, [evaluateLoadedViewers, evaluationIntervalMs, isPlaying]);

  useEffect(() => {
    viewersRef.current.forEach((viewer) => clearViewerPredictionState(viewer.localId));
  }, [clearViewerPredictionState, predictionOptions]);

  const toggleTransformation = (name: string, target: 'pre' | 'post') => {
    const setter = target === 'pre' ? setPreTransformations : setPostTransformations;
    setter((items) => (items.includes(name) ? items.filter((item) => item !== name) : [...items, name]));
  };

  const jumpToRecord = useCallback((recordIndex: number) => {
    setIsPlaying(false);
    setCurrentIndex(Math.max(0, Math.min(maxIndex, recordIndex)));
  }, [maxIndex, setCurrentIndex, setIsPlaying]);

  const togglePlayback = useCallback(() => {
    if (!hasRecords) return;
    if (!isPlaying && currentIndex >= maxIndex && !isLooping) {
      setCurrentIndex(0);
      currentIndexRef.current = 0;
    }
    setIsPlaying(!isPlaying);
  }, [currentIndex, hasRecords, isLooping, isPlaying, maxIndex, setCurrentIndex, setIsPlaying]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, select, button, [contenteditable="true"]')) return;
      if (event.code !== 'Space') return;
      event.preventDefault();
      togglePlayback();
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [togglePlayback]);

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
            max={maxIndex}
            value={Math.min(currentIndex, maxIndex)}
            disabled={!hasRecords}
            onChange={(event) => jumpToRecord(Number(event.target.value))}
            className="w-full accent-cyan-500"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" size="sm" onClick={() => jumpToRecord(0)} disabled={!hasRecords}>首帧</Button>
            <Button variant="secondary" size="sm" onClick={() => jumpToRecord(currentIndex - 1)} disabled={!hasRecords}>上一帧</Button>
            <Button size="sm" onClick={togglePlayback} disabled={!hasRecords}>{isPlaying ? '暂停' : '播放'}</Button>
            <Button variant={isLooping ? 'primary' : 'secondary'} size="sm" onClick={() => setIsLooping(!isLooping)} disabled={!hasRecords}>
              {isLooping ? '循环' : '单次'}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => jumpToRecord(currentIndex + 1)} disabled={!hasRecords}>下一帧</Button>
            <Button variant="secondary" size="sm" onClick={() => jumpToRecord(maxIndex)} disabled={!hasRecords}>末帧</Button>
            <span className="text-xs text-zinc-500">
              播放 {Math.round(playbackSpeed)}ms / 推理目标 {Math.round(evaluationIntervalMs)}ms / 并发 {maxInferenceConcurrency}
            </span>
          </div>
          <div className="flex flex-wrap gap-3 text-sm text-zinc-400">
            <span>当前序号: {displayRecordIndex}</span>
            <span>Record index: {displayRecord?._index ?? '--'}</span>
            <span>user/angle: {formatValue(displayUserControl?.angle)}</span>
            <span>user/throttle: {formatValue(displayUserControl?.throttle)}</span>
          </div>
        </CardContent>
      </Card>

      {!hasRecords && (
        <div className="rounded-md border border-amber-700 bg-amber-950/40 px-4 py-3 text-sm text-amber-100">
          请先在 Tub Manager 加载 Tub 数据，再进入 Pilot Arena 做模型对比。
        </div>
      )}

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

              <div className="aspect-video overflow-hidden rounded-md border border-zinc-800 bg-zinc-950 flex items-center justify-center relative">
                <div className="absolute right-2 top-2 z-10 grid grid-cols-2 gap-1 rounded-md border border-white/10 bg-zinc-900/35 px-2 py-1 text-center shadow-[0_8px_24px_rgba(0,0,0,0.25)] backdrop-blur-md">
                  <div>
                    <div className="text-[10px] uppercase leading-none text-zinc-400">播放</div>
                    <div className="font-mono text-sm leading-tight text-cyan-400">{viewer.playbackFps}</div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase leading-none text-zinc-400">推理</div>
                    <div className="font-mono text-sm leading-tight text-blue-400">{viewer.inferenceFps}</div>
                  </div>
                </div>
                {hasRecords ? (
                  <canvas
                    ref={(canvas) => {
                      canvasRefs.current[viewer.localId] = canvas;
                      if (canvas && hasRecords) {
                        window.requestAnimationFrame(() => drawViewerFrame(viewer, isPlaying ? currentIndexRef.current : currentIndex));
                      }
                    }}
                    className="h-full w-full object-contain"
                    width={640}
                    height={240}
                  />
                ) : (
                  <span className="text-sm text-zinc-500">加载 Tub 后显示播放画面</span>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-md bg-zinc-950 p-3">
                  <div className="text-xs uppercase text-zinc-500">User</div>
                  <div className="mt-2 font-mono text-green-400">Angle {formatValue(displayUserControl?.angle)}</div>
                  <div className="font-mono text-green-400">Throttle {formatValue(displayUserControl?.throttle)}</div>
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

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>图像处理</CardTitle>
          <Button variant="secondary" size="sm" onClick={() => setImageProcessingCollapsed((collapsed) => !collapsed)}>
            {imageProcessingCollapsed ? '展开' : '折叠'}
          </Button>
        </CardHeader>
        {!imageProcessingCollapsed && (
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
        )}
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
    </div>
  );
};
