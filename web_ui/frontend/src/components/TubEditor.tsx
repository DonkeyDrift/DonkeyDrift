import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Button } from './ui/Button';
import { Input } from './ui/Input';
import { useStore } from '../store/useStore';
import { deleteRecords, getRecords, restoreRecords } from '../services/api';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Legend,
} from 'chart.js';
import type { Chart as ChartInstance, Plugin } from 'chart.js';
import { Line } from 'react-chartjs-2';
import { LineChart, Redo2, RotateCcw, Undo2, ZoomIn, ZoomOut } from 'lucide-react';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Legend
);

const MIN_ZOOM_PERCENT = 100;
const MAX_ZOOM_PERCENT = 1000;
const ZOOM_STEP_PERCENT = 100;
const MAX_UNDO_HISTORY = 10;
const PLAYHEAD_SCROLL_PADDING_RATIO = 0.15;

type RecordAction = {
  mode: 'delete' | 'restore';
  indexes: number[];
};

export const TubEditor: React.FC = () => {
  const records = useStore((state) => state.records);
  const isDragging = useStore((state) => state.isDragging);
  const isPlaying = useStore((state) => state.isPlaying);
  const currentIndex = useStore((state) => state.currentIndex);
  const setCurrentIndex = useStore((state) => state.setCurrentIndex);
  const selectionStartIndex = useStore((state) => state.selectionStartIndex);
  const selectionEndIndex = useStore((state) => state.selectionEndIndex);
  const setSelectionRange = useStore((state) => state.setSelectionRange);
  const clearSelectionRange = useStore((state) => state.clearSelectionRange);
  const redoSelectionRange = useStore((state) => state.redoSelectionRange);
  const setAllRecords = useStore((state) => state.setAllRecords);
  const deletedIndexes = useStore((state) => state.deletedIndexes);
  const totalPhysicalRecords = useStore((state) => state.totalPhysicalRecords);
  const chartRef = useRef<ChartInstance<'line'> | null>(null);
  const lineDashOffsetRef = useRef(0);
  const visualSelectionRef = useRef<{ startIndex: number; endIndex: number } | null>(null);
  const isSelectingRef = useRef(false);
  const currentIndexRef = useRef(useStore.getState().currentIndex);
  const selectionRangeRef = useRef<{ startIndex: number | null; endIndex: number | null }>({
    startIndex: useStore.getState().selectionStartIndex,
    endIndex: useStore.getState().selectionEndIndex,
  });
  const pendingSelectionRangeRef = useRef<{ startIndex: number; endIndex: number } | null>(null);
  const selectionRangeFrameRef = useRef<number | null>(null);
  const chartRenderFrameRef = useRef<number | null>(null);
  const chartNeedsRenderRef = useRef(false);
  const selectionAnimationUntilRef = useRef(0);
  const playbackActivityUntilRef = useRef(0);
  const preserveViewportOnRecordsChangeRef = useRef(false);
  const [tooltipData, setTooltipData] = useState<{ x: number; y: number; steering: number; throttle: number; index: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [selectionDraft, setSelectionDraft] = useState<{
    startX: number;
    currentX: number;
    startIndex: number;
    currentIndex: number;
  } | null>(null);
  const selectionDraftRef = useRef(selectionDraft);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const hoverPositionRef = useRef<{ x: number; y: number; dataIndex: number } | null>(null);
  const recordsRef = useRef(records);
  const sampledIndicesRef = useRef<number[]>([]);

  useEffect(() => {
    recordsRef.current = records;
  }, [records]);
  const tooltipDataRef = useRef(tooltipData);

  const [rangeInputDraft, setRangeInputDraft] = useState<{ start: string; end: string } | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingMode, setProcessingMode] = useState<'delete' | 'restore' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionHistory, setActionHistory] = useState<RecordAction[]>([]);
  const [redoHistory, setRedoHistory] = useState<RecordAction[]>([]);
  const [zoomPercent, setZoomPercent] = useState(MIN_ZOOM_PERCENT);
  const [scrollProgress, setScrollProgress] = useState(0);
  const zoomMultiplier = zoomPercent / MIN_ZOOM_PERCENT;

  const clampZoomPercent = useCallback((value: number) => {
    return Math.max(MIN_ZOOM_PERCENT, Math.min(MAX_ZOOM_PERCENT, value));
  }, []);

  const applyZoomPercent = useCallback(
    (value: number) => {
      setZoomPercent(clampZoomPercent(value));
    },
    [clampZoomPercent]
  );

  const handleZoomOut = useCallback(() => {
    applyZoomPercent(zoomPercent - ZOOM_STEP_PERCENT);
  }, [applyZoomPercent, zoomPercent]);

  const handleZoomIn = useCallback(() => {
    applyZoomPercent(zoomPercent + ZOOM_STEP_PERCENT);
  }, [applyZoomPercent, zoomPercent]);

  const handleZoomReset = useCallback(() => {
    applyZoomPercent(MIN_ZOOM_PERCENT);
    setScrollProgress(0);
  }, [applyZoomPercent]);

  const ensureChartRenderLoop = useCallback(() => {
    if (!chartRef.current || chartRenderFrameRef.current != null) {
      return;
    }

    const renderLoop = (time: number) => {
      chartRenderFrameRef.current = null;

      const hasDraftSelection = Boolean(selectionDraftRef.current);
      const hasSelectionAnimation = hasDraftSelection || time < selectionAnimationUntilRef.current;
      const hasPlaybackActivity = time < playbackActivityUntilRef.current;
      const shouldRender = chartNeedsRenderRef.current || hasSelectionAnimation || hasPlaybackActivity;

      if (shouldRender && chartRef.current) {
        if (hasSelectionAnimation && (hasDraftSelection || visualSelectionRef.current)) {
          lineDashOffsetRef.current = (lineDashOffsetRef.current - 0.5) % 20;
        }

        chartNeedsRenderRef.current = false;
        chartRef.current.update('none');
      }

      if (hasDraftSelection || time < selectionAnimationUntilRef.current || time < playbackActivityUntilRef.current) {
        chartRenderFrameRef.current = window.requestAnimationFrame(renderLoop);
      }
    };

    chartRenderFrameRef.current = window.requestAnimationFrame(renderLoop);
  }, []);

  const requestChartRender = useCallback(
    (options?: { animateSelection?: boolean; markPlaybackActive?: boolean }) => {
      const now = performance.now();

      chartNeedsRenderRef.current = true;
      if (options?.animateSelection) {
        selectionAnimationUntilRef.current = Math.max(selectionAnimationUntilRef.current, now + 220);
      }
      if (options?.markPlaybackActive) {
        playbackActivityUntilRef.current = Math.max(playbackActivityUntilRef.current, now + 120);
      }

      ensureChartRenderLoop();
    },
    [ensureChartRenderLoop]
  );

  const flushPendingSelectionRange = useCallback(() => {
    selectionRangeFrameRef.current = null;
    const pendingRange = pendingSelectionRangeRef.current;
    if (!pendingRange) {
      return;
    }

    pendingSelectionRangeRef.current = null;
    setSelectionRange(pendingRange.startIndex, pendingRange.endIndex);
  }, [setSelectionRange]);

  const queueSelectionRangeUpdate = useCallback(
    (startIndex: number, endIndex: number) => {
      if (!records.length) {
        return;
      }

      const nextStartIndex = Math.max(0, Math.min(startIndex, records.length - 1));
      const nextEndIndex = Math.max(nextStartIndex + 1, Math.min(endIndex, records.length));
      const currentStartIndex = pendingSelectionRangeRef.current?.startIndex ?? selectionRangeRef.current.startIndex;
      const currentEndIndex = pendingSelectionRangeRef.current?.endIndex ?? selectionRangeRef.current.endIndex;

      if (currentStartIndex === nextStartIndex && currentEndIndex === nextEndIndex) {
        return;
      }

      pendingSelectionRangeRef.current = {
        startIndex: nextStartIndex,
        endIndex: nextEndIndex,
      };
      selectionRangeRef.current = {
        startIndex: nextStartIndex,
        endIndex: nextEndIndex,
      };
      visualSelectionRef.current = {
        startIndex: nextStartIndex,
        endIndex: nextEndIndex,
      };
      requestChartRender({ animateSelection: true });

      if (selectionRangeFrameRef.current == null) {
        selectionRangeFrameRef.current = window.requestAnimationFrame(() => {
          flushPendingSelectionRange();
        });
      }
    },
    [flushPendingSelectionRange, records.length, requestChartRender]
  );

  useEffect(() => {
    selectionRangeRef.current = {
      startIndex: selectionStartIndex,
      endIndex: selectionEndIndex,
    };
  }, [selectionStartIndex, selectionEndIndex]);

  useEffect(() => {
    selectionDraftRef.current = selectionDraft;
  }, [selectionDraft]);

  useEffect(() => {
    tooltipDataRef.current = tooltipData;
  }, [tooltipData]);

  useEffect(() => {
    requestChartRender({ animateSelection: selectionStartIndex != null && selectionEndIndex != null });
  }, [requestChartRender, selectionEndIndex, selectionStartIndex]);

  const syncedStartIndex = selectionStartIndex != null ? String(selectionStartIndex) : '';
  const syncedEndIndex = selectionEndIndex != null ? String(selectionEndIndex - 1) : '';
  const rangeStartInput = rangeInputDraft?.start ?? syncedStartIndex;
  const rangeEndInput = rangeInputDraft?.end ?? syncedEndIndex;

  useEffect(() => {
    if (!rangeInputDraft) {
      return;
    }

    if (rangeInputDraft.start === syncedStartIndex && rangeInputDraft.end === syncedEndIndex) {
      setRangeInputDraft(null);
    }
  }, [rangeInputDraft, syncedEndIndex, syncedStartIndex]);

  const rangeValidation = useMemo(() => {
    const normalizedStart = rangeStartInput.trim();
    const normalizedEnd = rangeEndInput.trim();

    if (!normalizedStart && !normalizedEnd) {
      return {
        startError: null,
        endError: null,
        message: null,
      };
    }

    if (!normalizedStart) {
      return {
        startError: '请输入开始索引',
        endError: null,
        message: '请输入完整的开始和结束索引',
      };
    }

    if (!normalizedEnd) {
      return {
        startError: null,
        endError: '请输入结束索引',
        message: '请输入完整的开始和结束索引',
      };
    }

    if (!/^\d+$/.test(normalizedStart)) {
      return {
        startError: '开始索引必须是非负整数',
        endError: null,
        message: '索引必须是非负整数',
      };
    }

    if (!/^\d+$/.test(normalizedEnd)) {
      return {
        startError: null,
        endError: '结束索引必须是非负整数',
        message: '索引必须是非负整数',
      };
    }

    const start = Number.parseInt(normalizedStart, 10);
    const end = Number.parseInt(normalizedEnd, 10);

    if (end < start) {
      return {
        startError: null,
        endError: '结束索引不能小于开始索引',
        message: '结束索引不能小于开始索引',
      };
    }

    return {
      startError: null,
      endError: null,
      message: null,
    };
  }, [rangeEndInput, rangeStartInput]);

  const parseRange = useCallback(() => {
    if (rangeValidation.message) {
      return null;
    }

    return {
      start: Number.parseInt(rangeStartInput.trim(), 10),
      end: Number.parseInt(rangeEndInput.trim(), 10),
    };
  }, [rangeEndInput, rangeStartInput, rangeValidation.message]);

  const hasRangeInput = rangeStartInput.trim() !== '' || rangeEndInput.trim() !== '';
  const isPartialRangeInput = rangeStartInput.trim() === '' || rangeEndInput.trim() === '';
  const visibleRangeValidation = isPartialRangeInput
    ? { startError: null, endError: null, message: null }
    : rangeValidation;
  const hasValidRange =
    rangeValidation.message === null && rangeStartInput.trim() !== '' && rangeEndInput.trim() !== '';

  const runRecordAction = useCallback(
    async (
      mode: 'delete' | 'restore',
      indexes: number[],
      rememberAction = true
    ) => {
      if (indexes.length === 0) {
        setActionError('No records in selected range');
        return false;
      }

      setIsProcessing(true);
      setProcessingMode(mode);
      try {
        const actionResponse =
          mode === 'delete'
            ? await deleteRecords(indexes)
            : await restoreRecords(indexes);

        const data = await getRecords(0, 100000);
        const nextRecords = data.records || [];
        preserveViewportOnRecordsChangeRef.current = true;
        setAllRecords(
          nextRecords,
          actionResponse.total_physical_records,
          actionResponse.deleted_indexes
        );
        setActionError(null);
        if (rememberAction) {
          setActionHistory((prev) => {
            const nextHistory = [...prev, { mode, indexes: [...indexes] }];
            return nextHistory.slice(-MAX_UNDO_HISTORY);
          });
          setRedoHistory([]);
        }
        return true;
      } catch {
        setActionError(mode === 'delete' ? 'Delete failed' : 'Restore failed');
        return false;
      } finally {
        setIsProcessing(false);
        setProcessingMode(null);
      }
    },
    [setAllRecords]
  );

  const handleAction = useCallback(async (mode: 'delete' | 'restore') => {
    const range = parseRange();
    if (!range) {
      setActionError('Invalid index range');
      return;
    }

    // Use current range before it gets cleared
    const startIdx = range.start;
    const endIdx = range.end;

    // The user input (range.start and range.end) are array indices (as shown
    // in the index inputs), not physical _index values. We must map them to
    // the actual _index values before sending to the backend.
    let indexes: number[] = [];
    const start = Math.max(0, Math.min(startIdx, records.length - 1));
    const end = Math.max(start, Math.min(endIdx, records.length - 1));

    if (mode === 'delete') {
      // For delete, collect the _index values of the visible records in the
      // selected array-index range.
      indexes = records.slice(start, end + 1).map((record) => record._index);
    } else {
      // For restore, the deleted records are not in the current array.
      // We generate all physical indexes from the _index of the first selected
      // record to the _index of the last selected record.
      if (records.length === 0) {
        setActionError('No records available');
        return;
      }
      const startXValue = records[start]._index;
      const endXValue = records[end]._index;
      const maxRestoreCount = 1000000; // Prevent out-of-memory if user inputs a huge range
      const actualEnd = Math.min(endXValue, startXValue + maxRestoreCount);
      for (let i = startXValue; i <= actualEnd; i++) {
        indexes.push(i);
      }
    }

    if (indexes.length === 0) {
      setActionError('No valid records in selected range');
      return;
    }

    await runRecordAction(mode, indexes, true);
    clearSelectionRange();
    visualSelectionRef.current = null;
    selectionDraftRef.current = null;
    setSelectionDraft(null);
  }, [parseRange, runRecordAction, clearSelectionRange, records]);

  const handleUndoLastAction = useCallback(async () => {
    const lastAction = actionHistory[actionHistory.length - 1];
    if (!lastAction) {
      return;
    }

    const inverseMode = lastAction.mode === 'delete' ? 'restore' : 'delete';
    const succeeded = await runRecordAction(inverseMode, lastAction.indexes, false);
    if (succeeded) {
      setActionHistory((prev) => prev.slice(0, -1));
      setRedoHistory((prev) => {
        const nextHistory = [...prev, { mode: lastAction.mode, indexes: [...lastAction.indexes] }];
        return nextHistory.slice(-MAX_UNDO_HISTORY);
      });
    }
  }, [actionHistory, runRecordAction]);

  const handleRedoLastAction = useCallback(async () => {
    const lastRedoAction = redoHistory[redoHistory.length - 1];
    if (!lastRedoAction) {
      return;
    }

    const succeeded = await runRecordAction(lastRedoAction.mode, lastRedoAction.indexes, false);
    if (succeeded) {
      setRedoHistory((prev) => prev.slice(0, -1));
      setActionHistory((prev) => {
        const nextHistory = [
          ...prev,
          { mode: lastRedoAction.mode, indexes: [...lastRedoAction.indexes] },
        ];
        return nextHistory.slice(-MAX_UNDO_HISTORY);
      });
    }
  }, [redoHistory, runRecordAction]);

  useEffect(() => {
    const unsubscribe = useStore.subscribe((state) => {
      const previousIndex = currentIndexRef.current;
      currentIndexRef.current = state.currentIndex;
      if (state.currentIndex !== previousIndex) {
        requestChartRender({ markPlaybackActive: true });
      }
    });

    return unsubscribe;
  }, [requestChartRender]);

  useEffect(() => {
    if (!records.length || zoomPercent === MIN_ZOOM_PERCENT) return;

    const totalRecords = records.length;
    const visibleCount = Math.max(
      2,
      Math.min(totalRecords, Math.ceil((totalRecords * MIN_ZOOM_PERCENT) / zoomPercent))
    );
    const maxStartIndex = Math.max(0, totalRecords - visibleCount);

    if (maxStartIndex <= 0) {
      preserveViewportOnRecordsChangeRef.current = false;
      setScrollProgress(0);
      return;
    }

    if (preserveViewportOnRecordsChangeRef.current) {
      preserveViewportOnRecordsChangeRef.current = false;
      setScrollProgress((previousProgress) => Math.max(0, Math.min(1, previousProgress)));
      return;
    }

    const centeredStartIndex = currentIndexRef.current - Math.floor(visibleCount / 2);
    const targetStartIndex = Math.max(0, Math.min(centeredStartIndex, maxStartIndex));
    setScrollProgress(targetStartIndex / maxStartIndex);
  }, [records.length, zoomPercent]);

  useEffect(() => {
    if (!isPlaying || !records.length || zoomPercent === MIN_ZOOM_PERCENT) {
      return;
    }

    const totalRecords = records.length;
    const visibleCount = Math.max(
      2,
      Math.min(totalRecords, Math.ceil((totalRecords * MIN_ZOOM_PERCENT) / zoomPercent))
    );
    const maxStartIndex = Math.max(0, totalRecords - visibleCount);

    if (maxStartIndex <= 0) {
      return;
    }

    const padding = Math.max(1, Math.floor(visibleCount * PLAYHEAD_SCROLL_PADDING_RATIO));
    const currentStartIndex = Math.round(maxStartIndex * scrollProgress);
    const currentEndIndex = Math.min(totalRecords - 1, currentStartIndex + visibleCount - 1);
    const safeStartIndex = currentStartIndex + padding;
    const safeEndIndex = currentEndIndex - padding;
    let targetStartIndex: number | null = null;

    if (currentIndex < safeStartIndex) {
      targetStartIndex = currentIndex - padding;
    } else if (currentIndex > safeEndIndex) {
      targetStartIndex = currentIndex + padding - visibleCount + 1;
    }

    if (targetStartIndex == null) {
      return;
    }

    const nextStartIndex = Math.max(0, Math.min(targetStartIndex, maxStartIndex));
    const nextProgress = nextStartIndex / maxStartIndex;

    setScrollProgress((previousProgress) => {
      if (Math.abs(previousProgress - nextProgress) < 0.0005) {
        return previousProgress;
      }

      return nextProgress;
    });
  }, [
    currentIndex,
    isPlaying,
    records.length,
    scrollProgress,
    zoomPercent,
  ]);

  const visibleRange = useMemo(() => {
    if (!records.length) {
      return { startIndex: 0, endIndex: 0, visibleCount: 0 };
    }

    const totalRecords = records.length;
    const visibleCount = Math.max(
      2,
      Math.min(totalRecords, Math.ceil((totalRecords * MIN_ZOOM_PERCENT) / zoomPercent))
    );
    const maxStartIndex = Math.max(0, totalRecords - visibleCount);
    const startIndex = Math.round(maxStartIndex * scrollProgress);
    const endIndex = Math.min(totalRecords - 1, startIndex + visibleCount - 1);

    return { startIndex, endIndex, visibleCount };
  }, [records.length, scrollProgress, zoomPercent]);

  const getIndexFromPointerX = useCallback(
    (x: number, chart: ChartInstance<'line'>) => {
      const xAxis = chart.scales.x;
      const currentRecords = recordsRef.current;
      if (!xAxis || !currentRecords.length) return 0;
      
      const targetIndexValue = xAxis.getValueForPixel(x);
      
      let low = 0;
      let high = currentRecords.length - 1;
      let closest = 0;
      let minDiff = Infinity;
      
      while (low <= high) {
        const mid = Math.floor((low + high) / 2);
        const diff = Math.abs(currentRecords[mid]._index - targetIndexValue);
        
        if (diff < minDiff) {
          minDiff = diff;
          closest = mid;
        }
        
        if (currentRecords[mid]._index === targetIndexValue) {
          return mid;
        } else if (currentRecords[mid]._index < targetIndexValue) {
          low = mid + 1;
        } else {
          high = mid - 1;
        }
      }
      
      return closest;
    },
    []
  );

  const handleScrollSliderChange = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const nextProgress = Number(event.target.value) / 1000;
    setScrollProgress(Math.max(0, Math.min(1, nextProgress)));
  }, []);

  const handleWheel = useCallback((event: React.WheelEvent) => {
    if (!records.length) return;

    // Ctrl/Meta + vertical wheel = zoom
    if ((event.ctrlKey || event.metaKey) && event.deltaY !== 0) {
      event.preventDefault();
      if (event.deltaY < 0) {
        handleZoomIn();
      } else {
        handleZoomOut();
      }
      return;
    }

    // Horizontal pan (trackpad two-finger swipe left/right)
    // Require dominant horizontal delta to avoid interfering with vertical scrolling
    if (Math.abs(event.deltaX) > Math.abs(event.deltaY) && Math.abs(event.deltaX) > 0) {
      event.preventDefault();

      const totalRecords = records.length;
      const visibleCount = Math.max(
        2,
        Math.min(totalRecords, Math.ceil((totalRecords * MIN_ZOOM_PERCENT) / zoomPercent))
      );
      const maxStartIndex = Math.max(0, totalRecords - visibleCount);

      if (maxStartIndex <= 0) return;

      const containerWidth = containerRef.current?.clientWidth || 1;
      const sensitivity = 1.5;
      const deltaProgress = (event.deltaX / containerWidth) * sensitivity;
      const newProgress = Math.max(0, Math.min(1, scrollProgress + deltaProgress));
      setScrollProgress(newProgress);
    }
  }, [records.length, zoomPercent, scrollProgress, handleZoomIn, handleZoomOut]);

  const updateTooltipPosition = useCallback((x: number, y: number) => {
    if (!tooltipRef.current || !containerRef.current) {
      return;
    }

    const isRightHalf = x > containerRef.current.clientWidth / 2;
    const isBottomHalf = y > containerRef.current.clientHeight / 2;
    tooltipRef.current.style.left = `${x}px`;
    tooltipRef.current.style.top = `${y}px`;
    tooltipRef.current.style.transform = `translate(${isRightHalf ? 'calc(-100% - 15px)' : '15px'}, ${isBottomHalf ? 'calc(-100% - 15px)' : '15px'})`;
  }, []);

  const handleMouseMove = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!chartRef.current || !containerRef.current || !recordsRef.current.length) return;

      const rect = containerRef.current.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;

      const chart = chartRef.current;
      const chartArea = chart.chartArea;

      if (x < chartArea.left || x > chartArea.right || y < chartArea.top || y > chartArea.bottom) {
        if (hoverPositionRef.current || tooltipDataRef.current) {
          hoverPositionRef.current = null;
          tooltipDataRef.current = null;
          setTooltipData(null);
          requestChartRender();
        }
        return;
      }

      const clampedX = Math.max(chartArea.left, Math.min(x, chartArea.right));
      const clampedIndex = getIndexFromPointerX(clampedX, chart);

      const currentRecords = recordsRef.current;
      const record = currentRecords[clampedIndex];
      const steering = (record?.['user/angle'] as number) ?? 0;
      const throttle = (record?.['user/throttle'] as number) ?? 0;

      hoverPositionRef.current = { x: clampedX, y, dataIndex: clampedIndex };
      requestChartRender();

      const nextTooltipData = {
        x: clampedX,
        y,
        steering,
        throttle,
        index: clampedIndex,
      };
      const previousTooltipData = tooltipDataRef.current;

      if (
        !previousTooltipData ||
        previousTooltipData.index !== clampedIndex ||
        previousTooltipData.steering !== steering ||
        previousTooltipData.throttle !== throttle
      ) {
        tooltipDataRef.current = nextTooltipData;
        setTooltipData(nextTooltipData);
      } else {
        updateTooltipPosition(clampedX, y);
        tooltipDataRef.current = {
          ...previousTooltipData,
          x: clampedX,
          y,
        };
      }

      if (selectionDraftRef.current) {
        const nextDraft = {
          ...selectionDraftRef.current,
          currentX: clampedX,
          currentIndex: clampedIndex,
        };
        selectionDraftRef.current = nextDraft;
        setSelectionDraft(nextDraft);
      }
    },
    [getIndexFromPointerX, requestChartRender, updateTooltipPosition]
  );

  const handleMouseLeave = useCallback(() => {
    if (!hoverPositionRef.current && !tooltipDataRef.current) {
      return;
    }

    hoverPositionRef.current = null;
    tooltipDataRef.current = null;
    setTooltipData(null);
    requestChartRender();
  }, [requestChartRender]);

  const handleInteraction = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    if (!chartRef.current || !containerRef.current || !records.length) return;

    const rect = containerRef.current.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;

    const chart = chartRef.current;
    const chartArea = chart.chartArea;

    if (x < chartArea.left || x > chartArea.right) return;
    const clampedIndex = getIndexFromPointerX(x, chart);

    // Update hover position so the red line can follow the mouse exactly
    hoverPositionRef.current = { x, y, dataIndex: clampedIndex };
    requestChartRender();

    setCurrentIndex(clampedIndex);

    if (selectionDraftRef.current) {
      const nextDraft = {
        ...selectionDraftRef.current,
        currentX: x,
        currentIndex: clampedIndex,
      };
      selectionDraftRef.current = nextDraft;
      setSelectionDraft(nextDraft);
    }
  }, [getIndexFromPointerX, records, setCurrentIndex, requestChartRender]);

  const handleMouseDown = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!chartRef.current || !containerRef.current || !records.length) return;
      if (event.button !== 0) return;

      const rect = containerRef.current.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;

      const chart = chartRef.current;
      const chartArea = chart.chartArea;

      if (x < chartArea.left || x > chartArea.right) return;

      isSelectingRef.current = true;
      const clampedIndex = getIndexFromPointerX(x, chart);

      const draft = {
        startX: x,
        currentX: x,
        startIndex: clampedIndex,
        currentIndex: clampedIndex,
      };
      selectionDraftRef.current = draft;
      setSelectionDraft(draft);

      // Update hover position so the red line can follow the mouse exactly
      hoverPositionRef.current = { x, y, dataIndex: clampedIndex };
      requestChartRender();

      setCurrentIndex(clampedIndex);
    },
    [getIndexFromPointerX, records.length, setCurrentIndex, requestChartRender]
  );

  const handleClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (selectionDraftRef.current) return;
      handleInteraction(event);
    },
    [handleInteraction]
  );

  const handleMouseUp = useCallback(
    () => {
      isSelectingRef.current = false;
      const draft = selectionDraftRef.current;
      if (!draft || !records.length) {
        selectionDraftRef.current = null;
        setSelectionDraft(null);
        return;
      }

      const startIndex = Math.min(draft.startIndex, draft.currentIndex);
      const endIndex = Math.max(draft.startIndex, draft.currentIndex) + 1;

      const pixelDelta = Math.abs(draft.currentX - draft.startX);
      const finalStart = startIndex;
      const finalEnd = pixelDelta < 3 ? startIndex + 1 : endIndex;

      visualSelectionRef.current = { startIndex: finalStart, endIndex: finalEnd };
      setSelectionRange(finalStart, finalEnd);
      selectionDraftRef.current = null;
      setSelectionDraft(null);
    },
    [setSelectionRange, records.length]
  );

  const isEditableTarget = (target: EventTarget | null) => {
    if (!(target instanceof HTMLElement)) {
      return false;
    }

    return (
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement ||
      target.isContentEditable
    );
  };

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (!records.length) return;
      if (isEditableTarget(event.target)) return;

      if (event.key === 'Escape') {
        event.preventDefault();
        clearSelectionRange();
        selectionDraftRef.current = null;
        setSelectionDraft(null);
        return;
      }

      if ((event.key === 'z' || event.key === 'Z') && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        if (!event.shiftKey && actionHistory.length > 0) {
          void handleUndoLastAction();
        } else if (event.shiftKey) {
          if (redoHistory.length > 0) {
            void handleRedoLastAction();
          } else {
            redoSelectionRange();
          }
        }
        return;
      }

      if ((event.key === 'y' || event.key === 'Y') && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        if (redoHistory.length > 0) {
          void handleRedoLastAction();
        } else {
          redoSelectionRange();
        }
        return;
      }

      if (event.key === 'p' || event.key === 'P') {
        event.preventDefault();
        handleZoomReset();
        return;
      }

      if (event.key === '-' || event.key === '_') {
        event.preventDefault();
        handleZoomOut();
        return;
      }

      if (event.key === '=' || event.key === '+') {
        event.preventDefault();
        handleZoomIn();
        return;
      }

      if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault();
        if (!isProcessing && hasValidRange) {
          void handleAction('delete');
        }
        return;
      }

      if (event.key === '\\') {
        event.preventDefault();
        if (!isProcessing && hasValidRange) {
          void handleAction('restore');
        }
        return;
      }

      if (
        selectionRangeRef.current.startIndex != null &&
        selectionRangeRef.current.endIndex != null &&
        (event.key === '[' || event.key === ']')
      ) {
        event.preventDefault();
        const delta = event.key === '[' ? -1 : 1;
        const start = selectionRangeRef.current.startIndex;
        const end = selectionRangeRef.current.endIndex;
        const nextEnd = Math.max(start + 1, Math.min(end + delta, records.length));
        queueSelectionRangeUpdate(start, nextEnd);
        return;
      }

      const step = 1;

      switch (event.key) {
        case 'ArrowLeft':
          if (isPlaying) return;
          event.preventDefault();
          setCurrentIndex((prev) => Math.max(0, prev - step));
          break;
        case 'ArrowRight':
          if (isPlaying) return;
          event.preventDefault();
          setCurrentIndex((prev) => Math.min(records.length - 1, prev + step));
          break;
        case 'Home':
          if (isPlaying) return;
          event.preventDefault();
          setCurrentIndex(0);
          break;
        case 'End':
          if (isPlaying) return;
          event.preventDefault();
          setCurrentIndex(records.length - 1);
          break;
      }
    },
    [
      records.length,
      isPlaying,
      setCurrentIndex,
      clearSelectionRange,
      actionHistory.length,
      handleUndoLastAction,
      redoHistory.length,
      handleRedoLastAction,
      isProcessing,
      hasValidRange,
      handleAction,
      queueSelectionRangeUpdate,
      handleZoomIn,
      handleZoomOut,
      handleZoomReset,
      redoSelectionRange,
    ]
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  useEffect(() => {
    return () => {
      if (selectionRangeFrameRef.current != null) {
        window.cancelAnimationFrame(selectionRangeFrameRef.current);
      }
      if (chartRenderFrameRef.current != null) {
        window.cancelAnimationFrame(chartRenderFrameRef.current);
      }
    };
  }, []);

  const { data, sampledIndices } = useMemo(() => {
    if (!records.length) return { data: { datasets: [] }, sampledIndices: [] as number[] };

    // Increase point density while zooming in so horizontal zoom reveals more detail.
    const maxPoints = Math.min(records.length, Math.max(1000, zoomPercent * 10));
    const step = Math.max(1, Math.ceil(records.length / maxPoints));
    const sampledRecords = records
      .map((record, i) => ({ record, originalIndex: i }))
      .filter((_, i) => i % step === 0 || i === records.length - 1);

    const sampledX = sampledRecords.map(({ record }) => record._index);
    const angleData: { x: number; y: number | null }[] = [];
    const throttleData: { x: number; y: number | null }[] = [];

    sampledRecords.forEach(({ record, originalIndex }, i) => {
      if (i > 0) {
        const { record: prevRecord, originalIndex: prevOriginalIndex } = sampledRecords[i - 1];
        // If the gap in _index is larger than the gap in array indices, it means records were deleted
        const originalIndexGap = originalIndex - prevOriginalIndex;
        
        if (record._index - prevRecord._index > originalIndexGap) {
          // Insert a null point to break the line
          angleData.push({ x: prevRecord._index + 1, y: null });
          throttleData.push({ x: prevRecord._index + 1, y: null });
        }
      }
      
      angleData.push({
        x: record._index,
        y: Number(record['user/angle'] ?? 0),
      });
      throttleData.push({
        x: record._index,
        y: Number(record['user/throttle'] ?? 0),
      });
    });

    return {
      data: {
        datasets: [
          {
            label: 'Steering',
            data: angleData,
            borderColor: 'rgb(6, 182, 212)',
            backgroundColor: 'rgba(6, 182, 212, 0.5)',
            borderWidth: 1,
            pointRadius: 0,
            tension: 0.1,
            spanGaps: false,
          },
          {
            label: 'Throttle',
            data: throttleData,
            borderColor: 'rgb(234, 179, 8)',
            backgroundColor: 'rgba(234, 179, 8, 0.5)',
            borderWidth: 1,
            pointRadius: 0,
            tension: 0.1,
            spanGaps: false,
          },
        ],
      },
      sampledIndices: sampledX,
    };
  }, [records, zoomPercent]);

  useEffect(() => {
    sampledIndicesRef.current = sampledIndices;
  }, [sampledIndices]);

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'top' as const,
        labels: {
            color: '#e4e4e7' // zinc-200
        }
      },
      tooltip: {
        enabled: false,
      },
    },
    scales: {
        x: {
            type: 'linear' as const,
            min: records.length > 0 && records[visibleRange.startIndex] ? records[visibleRange.startIndex]._index : visibleRange.startIndex,
            max: records.length > 0 && records[visibleRange.endIndex] ? records[visibleRange.endIndex]._index : visibleRange.endIndex,
            ticks: {
              color: '#71717a',
              callback: (value: string | number) => `${Math.round(Number(value))}`,
            },
            grid: { color: '#27272a' }
        },
        y: {
            min: -1,
            max: 1,
            ticks: {
              color: '#71717a',
              stepSize: 0.2,
            },
            grid: { color: '#27272a' }
        }
    },
    animation: {
        duration: 0 // Disable animation for performance
    }
  };

  const verticalLinePlugin = useMemo<Plugin<'line'>>(() => ({
    id: 'verticalLine',
    afterDraw: (chart: ChartInstance<'line'>) => {
      const records = recordsRef.current;
      const sampledIndices = sampledIndicesRef.current;
      
      if (!sampledIndices.length || !records.length) {
        return;
      }
      
      try {
        const xAxis = chart.scales.x;
        const yAxis = chart.scales.y;
        if (!xAxis || !yAxis) {
          return;
        }
        
        const ctx = chart.ctx;
        const chartArea = chart.chartArea;
        const latestIndex = currentIndexRef.current;
        const totalRecords = records.length;
        const currentRecord = records[latestIndex];
        const currentXValue = currentRecord ? currentRecord._index : latestIndex;
        
        const currentX = xAxis.getPixelForValue(currentXValue);

        if (!isNaN(currentX) && currentX >= chart.chartArea.left && currentX <= chart.chartArea.right) {
          ctx.save();
          ctx.strokeStyle = 'rgb(239, 68, 68)';
          ctx.lineWidth = 2;
          ctx.globalAlpha = 0.9;
          ctx.setLineDash([5, 3]);
          
          ctx.beginPath();
          ctx.moveTo(currentX, yAxis.top);
          ctx.lineTo(currentX, yAxis.bottom);
          ctx.stroke();
          
          ctx.setLineDash([]);
          ctx.fillStyle = 'rgb(239, 68, 68)';
          ctx.beginPath();
          ctx.arc(currentX, yAxis.top, 3, 0, 2 * Math.PI);
          ctx.fill();
          ctx.beginPath();
          ctx.arc(currentX, yAxis.bottom, 3, 0, 2 * Math.PI);
          ctx.fill();
          
          ctx.restore();
        }

        const drawSelectionBox = (startValue: number, endValue: number, isDraft: boolean) => {
            const chartArea = chart.chartArea;
            
            const startRecord = records[Math.max(0, Math.min(startValue, records.length - 1))];
            const startXValue = startRecord ? startRecord._index : 0;
            
            // endValue is exclusive. Get the last selected record.
            const lastSelectedRecord = records[Math.max(0, Math.min(endValue - 1, records.length - 1))];
            const endXValue = lastSelectedRecord ? lastSelectedRecord._index + 1 : startXValue + 1;

            const startX = xAxis.getPixelForValue(startXValue);
            const endX = xAxis.getPixelForValue(endXValue);
            
            if (!isNaN(startX) && !isNaN(endX) && endX > startX) {
                ctx.save();
                ctx.beginPath();
                ctx.rect(startX, chartArea.top, endX - startX, chartArea.bottom - chartArea.top);
                ctx.clip(); // Clip to ensure we don't draw outside if endX > right

                ctx.lineDashOffset = -lineDashOffsetRef.current;
                
                if (isDraft) {
                    // 拖动过程中也使用绿色，确保用户体验一致
                    ctx.fillStyle = 'rgba(34, 197, 94, 0.15)'; 
                    ctx.strokeStyle = 'rgb(34, 197, 94)';
                } else {
                    ctx.fillStyle = 'rgba(34, 197, 94, 0.15)'; 
                    ctx.strokeStyle = 'rgb(34, 197, 94)';
                }

                ctx.fillRect(startX, chartArea.top, endX - startX, chartArea.bottom - chartArea.top);
                ctx.lineWidth = 2;
                ctx.setLineDash([6, 4]);
                ctx.strokeRect(startX, chartArea.top, endX - startX, chartArea.bottom - chartArea.top);
                ctx.restore();
            }
        };

        const currentSelectionDraft = selectionDraftRef.current;
        if (currentSelectionDraft) {
            const chartArea = chart.chartArea;
            const startX = currentSelectionDraft.startX;
            const endX = currentSelectionDraft.currentX;
            const minX = Math.min(startX, endX);
            const maxX = Math.max(startX, endX);

            if (!isNaN(minX) && !isNaN(maxX) && maxX > minX) {
                ctx.save();
                ctx.beginPath();
                ctx.rect(minX, chartArea.top, maxX - minX, chartArea.bottom - chartArea.top);
                ctx.clip();

                ctx.lineDashOffset = -lineDashOffsetRef.current;
                ctx.fillStyle = 'rgba(34, 197, 94, 0.15)'; 
                ctx.strokeStyle = 'rgb(34, 197, 94)';

                ctx.fillRect(minX, chartArea.top, maxX - minX, chartArea.bottom - chartArea.top);
                ctx.lineWidth = 2;
                ctx.setLineDash([6, 4]);
                ctx.strokeRect(minX, chartArea.top, maxX - minX, chartArea.bottom - chartArea.top);
                ctx.restore();
            }
        } else if (visualSelectionRef.current) {
            drawSelectionBox(visualSelectionRef.current.startIndex, visualSelectionRef.current.endIndex, false);
        } else if (selectionRangeRef.current.startIndex != null && selectionRangeRef.current.endIndex != null && totalRecords > 1) {
             drawSelectionBox(selectionRangeRef.current.startIndex, selectionRangeRef.current.endIndex, false);
        }

        const hoverPosData = hoverPositionRef.current;
        if (hoverPosData && hoverPosData.x >= chartArea.left && hoverPosData.x <= chartArea.right && !selectionDraftRef.current) {
          ctx.save();
          ctx.strokeStyle = 'rgb(34, 197, 94)';
          ctx.lineWidth = 2;
          ctx.globalAlpha = 0.8;
          ctx.setLineDash([]);
          
          ctx.beginPath();
          ctx.moveTo(hoverPosData.x, yAxis.top);
          ctx.lineTo(hoverPosData.x, yAxis.bottom);
          ctx.stroke();
          
          ctx.fillStyle = 'rgb(34, 197, 94)';
          ctx.beginPath();
          ctx.arc(hoverPosData.x, yAxis.top, 2, 0, 2 * Math.PI);
          ctx.fill();
          ctx.beginPath();
          ctx.arc(hoverPosData.x, yAxis.bottom, 2, 0, 2 * Math.PI);
          ctx.fill();
          
          ctx.restore();
        }
      } catch (error) {
        console.error('Vertical line plugin error:', error);
      }
    }
  }), []);

  // Sync Visual Selection Ref
  useEffect(() => {
    if (!records.length) return;
    if (isSelectingRef.current) return;

    if (selectionStartIndex != null && selectionEndIndex != null) {
        const total = records.length;
        const nextStartIndex = Math.max(0, Math.min(selectionStartIndex, total - 1));
        const nextEndIndex = Math.max(nextStartIndex + 1, Math.min(selectionEndIndex, total));
        let shouldUpdate = false;
        
        if (!visualSelectionRef.current) {
            shouldUpdate = true;
        } else {
            const vStartIdx = Math.round(visualSelectionRef.current.startIndex);
            const vEndIdx = Math.round(visualSelectionRef.current.endIndex);
            if (vStartIdx !== nextStartIndex || vEndIdx !== nextEndIndex) {
                shouldUpdate = true;
            }
        }
        
        if (shouldUpdate) {
            visualSelectionRef.current = {
              startIndex: nextStartIndex,
              endIndex: nextEndIndex,
            };
        }
    } else {
        visualSelectionRef.current = null;
    }
  }, [selectionStartIndex, selectionEndIndex, records.length]);

  useEffect(() => {
    requestChartRender({ animateSelection: Boolean(selectionDraft) });
  }, [requestChartRender, selectionDraft]);

  const sliderSelectionRange = useMemo(() => {
    if (!records.length) {
      return null;
    }

    if (selectionDraft) {
      const startIndex = Math.min(selectionDraft.startIndex, selectionDraft.currentIndex);
      const endIndex = Math.max(selectionDraft.startIndex, selectionDraft.currentIndex) + 1;
      return { startIndex, endIndex };
    }

    if (selectionStartIndex != null && selectionEndIndex != null) {
      return {
        startIndex: Math.max(0, Math.min(selectionStartIndex, records.length - 1)),
        endIndex: Math.max(selectionStartIndex + 1, Math.min(selectionEndIndex, records.length)),
      };
    }

    return null;
  }, [records.length, selectionDraft, selectionStartIndex, selectionEndIndex]);

  const sliderSelectionStyle = useMemo<React.CSSProperties | null>(() => {
    if (!sliderSelectionRange || !records.length || !totalPhysicalRecords) {
      return null;
    }

    // Map array indices to physical _index values so the green bar aligns
    // with the red deleted bars (which are plotted in the physical coordinate space).
    const startRecord = records[Math.max(0, Math.min(sliderSelectionRange.startIndex, records.length - 1))];
    const endRecord = records[Math.max(0, Math.min(sliderSelectionRange.endIndex - 1, records.length - 1))];

    const startXValue = startRecord ? startRecord._index : 0;
    const endXValue = endRecord ? endRecord._index + 1 : startXValue + 1;

    const leftPercent = (startXValue / totalPhysicalRecords) * 100;
    const widthPercent = ((endXValue - startXValue) / totalPhysicalRecords) * 100;

    return {
      left: `${leftPercent}%`,
      width: `max(${widthPercent}%, 2px)`,
    };
  }, [records, totalPhysicalRecords, sliderSelectionRange]);

  const sliderDeletedStyles = useMemo<{ left: string; width: string }[]>(() => {
    if (!deletedIndexes.length || !totalPhysicalRecords) {
      return [];
    }

    // Group deleted indexes into contiguous ranges
    const ranges: { start: number; end: number }[] = [];
    let start = deletedIndexes[0];
    let end = deletedIndexes[0];

    for (let i = 1; i < deletedIndexes.length; i++) {
      if (deletedIndexes[i] === end + 1) {
        end = deletedIndexes[i];
      } else {
        ranges.push({ start, end });
        start = deletedIndexes[i];
        end = deletedIndexes[i];
      }
    }
    ranges.push({ start, end });

    return ranges.map(({ start, end }) => ({
      left: `${(start / totalPhysicalRecords) * 100}%`,
      width: `max(${((end - start + 1) / totalPhysicalRecords) * 100}%, 2px)`,
    }));
  }, [deletedIndexes, totalPhysicalRecords]);

  const handleTouchStart = useCallback(
    (event: React.TouchEvent<HTMLDivElement>) => {
      if (!chartRef.current || !containerRef.current || !records.length) return;
      if (event.touches.length === 0) return;

      const touch = event.touches[0];
      const rect = containerRef.current.getBoundingClientRect();
      const x = touch.clientX - rect.left;
      const y = touch.clientY - rect.top;

      const chart = chartRef.current;
      const chartArea = chart.chartArea;

      if (x < chartArea.left || x > chartArea.right) return;

      isSelectingRef.current = true;
      const clampedIndex = getIndexFromPointerX(x, chart);

      const draft = {
        startX: x,
        currentX: x,
        startIndex: clampedIndex,
        currentIndex: clampedIndex,
      };
      selectionDraftRef.current = draft;
      setSelectionDraft(draft);

      // Update hover position so the red line can follow the mouse exactly
      hoverPositionRef.current = { x, y, dataIndex: clampedIndex };
      requestChartRender();

      setCurrentIndex(clampedIndex);

      event.preventDefault();
    },
    [getIndexFromPointerX, records.length, setCurrentIndex, requestChartRender]
  );

  const handleTouchMove = useCallback(
    (event: React.TouchEvent<HTMLDivElement>) => {
      if (!chartRef.current || !containerRef.current || !recordsRef.current.length) return;
      if (!selectionDraftRef.current) return;
      if (event.touches.length === 0) return;

      const touch = event.touches[0];
      const rect = containerRef.current.getBoundingClientRect();
      const x = touch.clientX - rect.left;
      const y = touch.clientY - rect.top;

      const chart = chartRef.current;
      const chartArea = chart.chartArea;

      const clampedX = Math.max(chartArea.left, Math.min(x, chartArea.right));
      const clampedIndex = getIndexFromPointerX(clampedX, chart);

      if (selectionDraftRef.current) {
        const nextDraft = {
          ...selectionDraftRef.current,
          currentX: clampedX,
          currentIndex: clampedIndex,
        };
        selectionDraftRef.current = nextDraft;
        setSelectionDraft(nextDraft);
      }

      const currentRecords = recordsRef.current;
      const record = currentRecords[clampedIndex];
      const steering = (record?.['user/angle'] as number) ?? 0;
      const throttle = (record?.['user/throttle'] as number) ?? 0;

      hoverPositionRef.current = { x: clampedX, y, dataIndex: clampedIndex };
      requestChartRender();

      const nextTooltipData = {
        x: clampedX,
        y,
        steering,
        throttle,
        index: clampedIndex,
      };
      const previousTooltipData = tooltipDataRef.current;

      if (
        !previousTooltipData ||
        previousTooltipData.index !== clampedIndex ||
        previousTooltipData.steering !== steering ||
        previousTooltipData.throttle !== throttle
      ) {
        tooltipDataRef.current = nextTooltipData;
        setTooltipData(nextTooltipData);
      } else {
        updateTooltipPosition(clampedX, y);
        tooltipDataRef.current = {
          ...previousTooltipData,
          x: clampedX,
          y,
        };
      }

      event.preventDefault();
    },
    [getIndexFromPointerX, requestChartRender, updateTooltipPosition]
  );

  const handleTouchEnd = useCallback(
    (event: React.TouchEvent<HTMLDivElement>) => {
      isSelectingRef.current = false;
      const draft = selectionDraftRef.current;
      if (!draft || !records.length) {
        selectionDraftRef.current = null;
        setSelectionDraft(null);
        return;
      }
      
      const startIndex = Math.min(draft.startIndex, draft.currentIndex);
      const endIndex = Math.max(draft.startIndex, draft.currentIndex) + 1;

      visualSelectionRef.current = { startIndex, endIndex };
      setSelectionRange(startIndex, endIndex);
      selectionDraftRef.current = null;
      setSelectionDraft(null);
      event.preventDefault();
    },
    [setSelectionRange, records.length]
  );

  const chartCardClassName = 'relative flex min-h-[clamp(20rem,48vh,34rem)] flex-col';

  if (!records.length) {
    return (
      <Card className={chartCardClassName}>
        <CardHeader>
          <CardTitle className="group flex w-fit items-center cursor-default">
            <div className="flex items-center gap-2">
              <LineChart className="w-5 h-5" />
              <span>Tub Editor</span>
            </div>
            <span className="max-w-0 overflow-hidden whitespace-nowrap text-sm font-normal text-zinc-400 opacity-0 transition-all duration-300 ease-in-out group-hover:ml-3 group-hover:max-w-[320px] group-hover:opacity-100">
              Edit Tub with functions
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
            <div
              id="empty-chart"
              className="empty-chart-placeholder flex h-[150px] w-full items-center justify-center rounded-lg border border-dashed border-zinc-700 text-sm text-zinc-400"
              aria-label="empty-chart placeholder"
            >
              Select files to view telemetry data
            </div>
          </CardContent>
      </Card>
    );
  }

   const containerCursorClass = selectionDraft ? 'cursor-ew-resize' : 'cursor-crosshair';

  return (
    <Card className={chartCardClassName}>
      <CardHeader className="relative flex flex-col items-start justify-between gap-4 space-y-0">
        <CardTitle className="group flex w-fit items-center cursor-default">
          <div className="flex items-center gap-2">
            <LineChart className="w-5 h-5" />
            <span>Tub Editor</span>
            {isDragging && (
              <span className="ml-2 rounded-full bg-cyan-500/20 px-2 py-0.5 text-xs text-cyan-400 animate-pulse">
                Live Update
              </span>
            )}
          </div>
          <span className="max-w-0 overflow-hidden whitespace-nowrap text-sm font-normal text-zinc-400 opacity-0 transition-all duration-300 ease-in-out group-hover:ml-3 group-hover:max-w-[320px] group-hover:opacity-100">
            Edit Tub with functions
          </span>
        </CardTitle>
        <div className="flex w-full max-w-full items-start justify-between gap-2">
          <div className="ml-auto flex flex-col items-end gap-1">
            <div className="flex min-h-[30px] flex-wrap items-center justify-end gap-2">
              <div className="relative">
                <Input
                  aria-label="Start index"
                  aria-invalid={hasRangeInput && !!visibleRangeValidation.startError}
                  placeholder="Start"
                  value={rangeStartInput}
                  onChange={(e) =>
                    setRangeInputDraft({
                      start: e.target.value,
                      end: rangeInputDraft?.end ?? syncedEndIndex,
                    })
                  }
                  className={`w-[70px] h-full text-xs ${
                    hasRangeInput && visibleRangeValidation.startError
                      ? 'border-red-500 text-red-100 placeholder:text-red-300/70 focus:ring-red-500'
                      : ''
                  }`}
                />
                {hasRangeInput && visibleRangeValidation.startError && (
                  <span
                    className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 -translate-x-1/2 whitespace-nowrap rounded-md border border-red-500/60 bg-zinc-950 px-2 py-1 text-xs text-red-300 shadow-lg"
                    role="alert"
                    aria-live="polite"
                  >
                    {visibleRangeValidation.startError}
                    <span className="absolute left-1/2 top-full h-2 w-2 -translate-x-1/2 -translate-y-1/2 rotate-45 border-b border-r border-red-500/60 bg-zinc-950" />
                  </span>
                )}
              </div>
              <span className="text-xs text-zinc-400">to</span>
              <div className="relative">
                <Input
                  aria-label="End index"
                  aria-invalid={hasRangeInput && !!visibleRangeValidation.endError}
                  placeholder="End"
                  value={rangeEndInput}
                  onChange={(e) =>
                    setRangeInputDraft({
                      start: rangeInputDraft?.start ?? syncedStartIndex,
                      end: e.target.value,
                    })
                  }
                  className={`w-[70px] h-full text-xs ${
                    hasRangeInput && visibleRangeValidation.endError
                      ? 'border-red-500 text-red-100 placeholder:text-red-300/70 focus:ring-red-500'
                      : ''
                  }`}
                />
                {hasRangeInput && visibleRangeValidation.endError && (
                  <span
                    className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 -translate-x-1/2 whitespace-nowrap rounded-md border border-red-500/60 bg-zinc-950 px-2 py-1 text-xs text-red-300 shadow-lg"
                    role="alert"
                    aria-live="polite"
                  >
                    {visibleRangeValidation.endError}
                    <span className="absolute left-1/2 top-full h-2 w-2 -translate-x-1/2 -translate-y-1/2 rotate-45 border-b border-r border-red-500/60 bg-zinc-950" />
                  </span>
                )}
              </div>
              <Button
                size="sm"
                variant="danger"
                onClick={() => void handleAction('delete')}
                disabled={isProcessing || !hasValidRange}
                className="h-full text-xs"
                title="删除选中范围 (Del / Backspace)"
              >
                {isProcessing && processingMode === 'delete' ? 'Deleting...' : 'Delete'}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => void handleAction('restore')}
                disabled={isProcessing || !hasValidRange}
                className="h-full text-xs"
                title="恢复选中范围 (\\)"
              >
                {isProcessing && processingMode === 'restore' ? 'Restoring...' : 'Restore'}
              </Button>
              {actionError && (
                <span className="ml-2 text-xs text-red-400">
                  {actionError}
                </span>
              )}
              <Button
                size="sm"
                variant="secondary"
                onClick={() => void handleUndoLastAction()}
                disabled={isProcessing || actionHistory.length === 0}
                className="ml-auto h-full px-2"
                aria-label="撤销最近一次删除或恢复，最多 10 步，快捷键 Ctrl+Z"
                title={`撤销最近一次删除或恢复 (Ctrl+Z，最多 ${MAX_UNDO_HISTORY} 步)`}
              >
                <Undo2 className="h-4 w-4" />
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => void handleRedoLastAction()}
                disabled={isProcessing || redoHistory.length === 0}
                className="h-full px-2"
                aria-label="重做最近一次撤销的删除或恢复，最多 10 步，快捷键 Ctrl+Y"
                title={`重做最近一次撤销的删除或恢复 (Ctrl+Y，最多 ${MAX_UNDO_HISTORY} 步)`}
              >
                <Redo2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
          <div className="order-first flex min-h-[30px] items-center justify-start gap-2">
            <div className="flex h-[30px] box-content items-center gap-2 rounded-md bg-zinc-800 px-3 text-left rotate-0">
              <div className="h-4 box-content text-xs text-zinc-400 uppercase">ZOOM</div>
              <div className="h-4 box-content text-[15px] font-mono text-cyan-400 leading-none">{zoomMultiplier}x</div>
            </div>
            <Button
              size="sm"
              variant="secondary"
              onClick={handleZoomReset}
              disabled={zoomPercent === MIN_ZOOM_PERCENT}
              className="h-full text-xs"
              aria-label="还原图表缩放"
              title="还原图表缩放 (P)"
            >
              <RotateCcw className="h-4 w-4" />
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={handleZoomOut}
              disabled={zoomPercent <= MIN_ZOOM_PERCENT}
              className="h-full text-xs"
              aria-label="缩小图表"
              title="缩小图表 (-)"
            >
              <ZoomOut className="h-4 w-4" />
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={handleZoomIn}
              disabled={zoomPercent >= MAX_ZOOM_PERCENT}
              className="h-full text-xs"
              aria-label="放大图表"
              title="放大图表 (=)"
            >
              <ZoomIn className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
        <div
          ref={containerRef}
          className={`relative min-h-[12rem] w-full flex-1 ${containerCursorClass} touch-none`}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
          onMouseDown={handleMouseDown}
          onMouseUp={handleMouseUp}
          onClick={handleClick}
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
          onWheel={handleWheel}
        >
          <div className="pointer-events-none absolute inset-0 h-full min-h-0 w-full">
            <Line 
              ref={chartRef} 
              options={options} 
              data={data} 
              plugins={[verticalLinePlugin]}
              className="w-full h-full"
            />
          </div>
          {tooltipData && (
               <div 
                 ref={tooltipRef}
                 className="absolute pointer-events-none bg-zinc-900/95 border border-zinc-700 rounded-lg p-3 shadow-xl text-xs z-50 backdrop-blur-sm"
                 style={{
                   left: tooltipData.x,
                   top: tooltipData.y,
                   transform: `translate(${tooltipData.x > (containerRef.current?.clientWidth || 0) / 2 ? 'calc(-100% - 15px)' : '15px'}, ${tooltipData.y > (containerRef.current?.clientHeight || 0) / 2 ? 'calc(-100% - 15px)' : '15px'})`,
                 }}
               >
              <div className="font-semibold text-zinc-200 mb-2 whitespace-nowrap">Frame: {tooltipData.index}</div>
              <div className="space-y-1">
                <div className="flex justify-between gap-4">
                  <span className="text-zinc-400">Steering:</span>
                  <span className="text-cyan-400 font-mono">{tooltipData.steering.toFixed(3)}</span>
                </div>
                <div className="flex justify-between gap-4">
                  <span className="text-zinc-400">Throttle:</span>
                  <span className="text-yellow-400 font-mono">{tooltipData.throttle.toFixed(3)}</span>
                </div>
              </div>
            </div>
          )}
        </div>
        <div className="relative mt-3 h-4 shrink-0">
          <div className="pointer-events-none absolute inset-x-0 top-1/2 h-2 -translate-y-1/2 rounded-lg bg-zinc-700" />
          {sliderSelectionStyle && (
            <div className="pointer-events-none absolute inset-x-0 top-1/2 z-10 h-2 -translate-y-1/2">
              <div
                className="absolute h-full rounded-lg border border-emerald-400/70 bg-emerald-500/25"
                style={sliderSelectionStyle}
              />
            </div>
          )}
          {sliderDeletedStyles.map((style, i) => (
            <div
              key={i}
              className="pointer-events-none absolute inset-x-0 top-1/2 z-10 h-2 -translate-y-1/2"
            >
              <div
                className="absolute h-full rounded-sm border border-red-400/60 bg-red-500/40"
                style={style}
              />
            </div>
          ))}
          <input
            type="range"
            min="0"
            max="1000"
            step="1"
            value={Math.round(scrollProgress * 1000)}
            onChange={handleScrollSliderChange}
            disabled={zoomPercent === MIN_ZOOM_PERCENT || records.length <= visibleRange.visibleCount}
            aria-label="图表横向滚动"
            className="tub-editor-scroll-slider relative z-20 h-4 w-full appearance-none cursor-pointer bg-transparent accent-cyan-500 disabled:cursor-not-allowed disabled:opacity-40"
          />
        </div>
      </CardContent>
    </Card>
  );
};
