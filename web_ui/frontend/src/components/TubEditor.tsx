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

type RecordAction = {
  mode: 'delete' | 'restore';
  indexes: number[];
};

export const TubEditor: React.FC = () => {
  const {
    records,
    currentIndex,
    isDragging,
    setCurrentIndex,
    selectionStartIndex,
    selectionEndIndex,
    setSelectionRange,
    clearSelectionRange,
    redoSelectionRange,
    setAllRecords,
  } = useStore();
  const chartRef = useRef<ChartInstance<'line'> | null>(null);
  const [isChartReady, setIsChartReady] = useState(false);
  const lineDashOffsetRef = useRef(0);
  const visualSelectionRef = useRef<{ startIndex: number; endIndex: number } | null>(null);
  const isSelectingRef = useRef(false);
  const currentIndexRef = useRef(currentIndex);
  const [hoverPosition, setHoverPosition] = useState<{ x: number; y: number; dataIndex: number } | null>(null);
  const [tooltipData, setTooltipData] = useState<{ x: number; y: number; steering: number; throttle: number; index: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [selectionDraft, setSelectionDraft] = useState<{
    startX: number;
    currentX: number;
    startIndex: number;
    currentIndex: number;
  } | null>(null);
  const hydrateSelectionRef = useRef(false);
  const tooltipRef = useRef<HTMLDivElement>(null);

  const [startIndex, setStartIndex] = useState('');
  const [endIndex, setEndIndex] = useState('');
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

  useEffect(() => {
    if (selectionStartIndex != null) {
      setStartIndex(String(selectionStartIndex));
    }
    if (selectionEndIndex != null) {
      setEndIndex(String(selectionEndIndex - 1));
    }
    if (selectionStartIndex == null && selectionEndIndex == null) {
      setStartIndex('');
      setEndIndex('');
    }
  }, [selectionStartIndex, selectionEndIndex]);

  const rangeValidation = useMemo(() => {
    const normalizedStart = startIndex.trim();
    const normalizedEnd = endIndex.trim();

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
  }, [startIndex, endIndex]);

  const parseRange = useCallback(() => {
    if (rangeValidation.message) {
      return null;
    }

    return {
      start: Number.parseInt(startIndex.trim(), 10),
      end: Number.parseInt(endIndex.trim(), 10),
    };
  }, [endIndex, rangeValidation.message, startIndex]);

  const hasRangeInput = startIndex.trim() !== '' || endIndex.trim() !== '';
  const isPartialRangeInput = startIndex.trim() === '' || endIndex.trim() === '';
  const visibleRangeValidation = isPartialRangeInput
    ? { startError: null, endError: null, message: null }
    : rangeValidation;
  const hasValidRange =
    rangeValidation.message === null && startIndex.trim() !== '' && endIndex.trim() !== '';

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
        if (mode === 'delete') {
          await deleteRecords(indexes);
        } else {
          await restoreRecords(indexes);
        }

        const data = await getRecords(0, 100000);
        const nextRecords = data.records || [];
        setAllRecords(nextRecords);
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

    setSelectionRange(range.start, range.end + 1);

    const indexes: number[] = [];
    for (let i = range.start; i <= range.end; i += 1) {
      indexes.push(i);
    }

    await runRecordAction(mode, indexes, true);
  }, [parseRange, runRecordAction, setSelectionRange]);

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
    currentIndexRef.current = currentIndex;
  }, [currentIndex]);

  useEffect(() => {
    if (!isChartReady || !records.length || zoomPercent === MIN_ZOOM_PERCENT) return;

    const totalRecords = records.length;
    const visibleCount = Math.max(
      2,
      Math.min(totalRecords, Math.ceil((totalRecords * MIN_ZOOM_PERCENT) / zoomPercent))
    );
    const maxStartIndex = Math.max(0, totalRecords - visibleCount);

    if (maxStartIndex <= 0) {
      setScrollProgress(0);
      return;
    }

    const centeredStartIndex = currentIndexRef.current - Math.floor(visibleCount / 2);
    const targetStartIndex = Math.max(0, Math.min(centeredStartIndex, maxStartIndex));
    setScrollProgress(targetStartIndex / maxStartIndex);
  }, [isChartReady, records.length, zoomPercent]);

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
      const chartArea = chart.chartArea;
      const chartWidth = chartArea.right - chartArea.left;
      const relativeX = Math.max(0, Math.min(x - chartArea.left, chartWidth));
      const progress = chartWidth > 0 ? relativeX / chartWidth : 0;
      const span = Math.max(1, visibleRange.endIndex - visibleRange.startIndex);
      const dataIndex = Math.round(visibleRange.startIndex + progress * span);

      return Math.max(0, Math.min(dataIndex, records.length - 1));
    },
    [records.length, visibleRange.endIndex, visibleRange.startIndex]
  );

  const handleScrollSliderChange = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const nextProgress = Number(event.target.value) / 1000;
    setScrollProgress(Math.max(0, Math.min(1, nextProgress)));
  }, []);

  const handleMouseMove = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!chartRef.current || !containerRef.current || !records.length) return;

      const rect = containerRef.current.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;

      const chart = chartRef.current;
      const chartArea = chart.chartArea;

      if (x < chartArea.left || x > chartArea.right || y < chartArea.top || y > chartArea.bottom) {
        setHoverPosition(null);
        setTooltipData(null);
        return;
      }

      const clampedX = Math.max(chartArea.left, Math.min(x, chartArea.right));
      const clampedIndex = getIndexFromPointerX(clampedX, chart);

      const record = records[clampedIndex];
      const steering = (record['user/angle'] as number) ?? 0;
      const throttle = (record['user/throttle'] as number) ?? 0;

      setHoverPosition({ x: clampedX, y, dataIndex: clampedIndex });
      setTooltipData({
        x: clampedX,
        y,
        steering,
        throttle,
        index: clampedIndex,
      });

      // Update tooltip position via ref for maximum performance
      if (tooltipRef.current && containerRef.current) {
        const isRightHalf = clampedX > containerRef.current.clientWidth / 2;
        const isBottomHalf = y > containerRef.current.clientHeight / 2;
        tooltipRef.current.style.left = `${clampedX}px`;
        tooltipRef.current.style.top = `${y}px`;
        tooltipRef.current.style.transform = `translate(${isRightHalf ? 'calc(-100% - 15px)' : '15px'}, ${isBottomHalf ? 'calc(-100% - 15px)' : '15px'})`;
      }

      if (selectionDraft) {
        setSelectionDraft((prev) =>
          prev
            ? {
                ...prev,
                currentX: clampedX,
                currentIndex: clampedIndex,
              }
            : null
        );
      }
    },
    [getIndexFromPointerX, records, selectionDraft]
  );

  const handleMouseLeave = useCallback(() => {
    setHoverPosition(null);
    setTooltipData(null);
  }, []);

  const handleInteraction = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    if (!chartRef.current || !containerRef.current || !records.length) return;

    const rect = containerRef.current.getBoundingClientRect();
    const x = event.clientX - rect.left;

    const chart = chartRef.current;
    const chartArea = chart.chartArea;

    if (x < chartArea.left || x > chartArea.right) return;
    const clampedIndex = getIndexFromPointerX(x, chart);

    setCurrentIndex(clampedIndex);
  }, [getIndexFromPointerX, records, setCurrentIndex]);

  const handleMouseDown = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!chartRef.current || !containerRef.current || !records.length) return;
      if (event.button !== 0) return;

      const rect = containerRef.current.getBoundingClientRect();
      const x = event.clientX - rect.left;

      const chart = chartRef.current;
      const chartArea = chart.chartArea;

      if (x < chartArea.left || x > chartArea.right) return;

      isSelectingRef.current = true;
      const clampedIndex = getIndexFromPointerX(x, chart);

      setSelectionDraft({
        startX: x,
        currentX: x,
        startIndex: clampedIndex,
        currentIndex: clampedIndex,
      });

      setCurrentIndex(clampedIndex);
    },
    [getIndexFromPointerX, records.length, setCurrentIndex]
  );

  const handleClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (selectionDraft) return;
      handleInteraction(event);
    },
    [handleInteraction, selectionDraft]
  );

  const handleMouseUp = useCallback(
    () => {
      isSelectingRef.current = false;
      if (!selectionDraft || !records.length) {
        setSelectionDraft(null);
        return;
      }

      const startIndex = Math.min(selectionDraft.startIndex, selectionDraft.currentIndex);
      const endIndex = Math.max(selectionDraft.startIndex, selectionDraft.currentIndex) + 1;

      const pixelDelta = Math.abs(selectionDraft.currentX - selectionDraft.startX);
      const finalStart = startIndex;
      const finalEnd = pixelDelta < 3 ? startIndex + 1 : endIndex;

      visualSelectionRef.current = { startIndex: finalStart, endIndex: finalEnd };
      setSelectionRange(finalStart, finalEnd);
      setSelectionDraft(null);
    },
    [selectionDraft, setSelectionRange, records.length]
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
        selectionStartIndex != null &&
        selectionEndIndex != null &&
        (event.key === '[' || event.key === ']')
      ) {
        event.preventDefault();
        const delta = event.key === '[' ? -1 : 1;
        const start = selectionStartIndex;
        const nextEnd = Math.max(start + 1, Math.min(selectionEndIndex + delta, records.length));
        setSelectionRange(start, nextEnd);
        return;
      }

      const step = 1;

      switch (event.key) {
        case 'ArrowLeft':
          event.preventDefault();
          setCurrentIndex((prev) => Math.max(0, prev - step));
          break;
        case 'ArrowRight':
          event.preventDefault();
          setCurrentIndex((prev) => Math.min(records.length - 1, prev + step));
          break;
        case 'Home':
          event.preventDefault();
          setCurrentIndex(0);
          break;
        case 'End':
          event.preventDefault();
          setCurrentIndex(records.length - 1);
          break;
      }
    },
    [
      records.length,
      setCurrentIndex,
      clearSelectionRange,
      actionHistory.length,
      handleUndoLastAction,
      redoHistory.length,
      handleRedoLastAction,
      isProcessing,
      hasValidRange,
      handleAction,
      handleZoomIn,
      handleZoomOut,
      handleZoomReset,
      selectionStartIndex,
      selectionEndIndex,
      setSelectionRange,
      redoSelectionRange,
    ]
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!records.length) return;

    if (selectionStartIndex != null && selectionEndIndex != null) {
      try {
        window.localStorage.setItem(
          'tubSelectionRange',
          JSON.stringify({ start: selectionStartIndex, end: selectionEndIndex })
        );
      } catch {
        // ignore
      }
    } else {
      try {
        window.localStorage.removeItem('tubSelectionRange');
      } catch {
        // ignore
      }
    }
  }, [selectionStartIndex, selectionEndIndex, records.length]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (hydrateSelectionRef.current) return;
    if (!records.length) return;

    try {
      const raw = window.localStorage.getItem('tubSelectionRange');
      if (!raw) {
        hydrateSelectionRef.current = true;
        return;
      }
      const parsed = JSON.parse(raw) as { start: number; end: number };
      if (
        typeof parsed.start === 'number' &&
        typeof parsed.end === 'number' &&
        parsed.start >= 0 &&
        parsed.end > parsed.start
      ) {
        const clampedStart = Math.max(0, Math.min(parsed.start, records.length - 1));
        const clampedEnd = Math.max(clampedStart + 1, Math.min(parsed.end, records.length));
        setSelectionRange(clampedStart, clampedEnd);
      }
    } catch {
      // ignore
    } finally {
      hydrateSelectionRef.current = true;
    }
  }, [records.length, setSelectionRange]);

  const { data, sampledIndices } = useMemo(() => {
    if (!records.length) return { data: { datasets: [] }, sampledIndices: [] as number[] };

    // Increase point density while zooming in so horizontal zoom reveals more detail.
    const maxPoints = Math.min(records.length, Math.max(1000, zoomPercent * 10));
    const step = Math.max(1, Math.ceil(records.length / maxPoints));
    const sampledRecords = records.filter((_, i) => i % step === 0 || i === records.length - 1);

    const sampledX = sampledRecords.map((record) => record._index);
    const angleData = sampledRecords.map((record) => ({
      x: record._index,
      y: Number(record['user/angle'] ?? 0),
    }));
    const throttleData = sampledRecords.map((record) => ({
      x: record._index,
      y: Number(record['user/throttle'] ?? 0),
    }));

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
          },
          {
            label: 'Throttle',
            data: throttleData,
            borderColor: 'rgb(234, 179, 8)',
            backgroundColor: 'rgba(234, 179, 8, 0.5)',
            borderWidth: 1,
            pointRadius: 0,
            tension: 0.1,
          },
        ],
      },
      sampledIndices: sampledX,
    };
  }, [records, zoomPercent]);

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
            min: visibleRange.startIndex,
            max: visibleRange.endIndex,
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

  const hoverPositionRef = useRef(hoverPosition);

  useEffect(() => {
    hoverPositionRef.current = hoverPosition;
  }, [hoverPosition]);

  const verticalLinePlugin = useMemo<Plugin<'line'>>(() => ({
    id: 'verticalLine',
    afterDraw: (chart: ChartInstance<'line'>) => {
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
        const currentX = xAxis.getPixelForValue(latestIndex);
        
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
            const startX = xAxis.getPixelForValue(startValue);
            const endX = xAxis.getPixelForValue(endValue);
            
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

        if (selectionDraft) {
            const startIndex = Math.min(selectionDraft.startIndex, selectionDraft.currentIndex);
            const endIndex = Math.max(selectionDraft.startIndex, selectionDraft.currentIndex) + 1;
            drawSelectionBox(startIndex, endIndex, true);
        } else if (visualSelectionRef.current) {
            drawSelectionBox(visualSelectionRef.current.startIndex, visualSelectionRef.current.endIndex, false);
        } else if (selectionStartIndex != null && selectionEndIndex != null && totalRecords > 1) {
             drawSelectionBox(selectionStartIndex, selectionEndIndex, false);
        }

        const hoverPos = hoverPositionRef.current;
        if (hoverPos && hoverPos.x >= chartArea.left && hoverPos.x <= chartArea.right) {
          ctx.save();
          ctx.strokeStyle = 'rgb(34, 197, 94)';
          ctx.lineWidth = 2;
          ctx.globalAlpha = 0.8;
          ctx.setLineDash([]);
          
          ctx.beginPath();
          ctx.moveTo(hoverPos.x, yAxis.top);
          ctx.lineTo(hoverPos.x, yAxis.bottom);
          ctx.stroke();
          
          ctx.fillStyle = 'rgb(34, 197, 94)';
          ctx.beginPath();
          ctx.arc(hoverPos.x, yAxis.top, 2, 0, 2 * Math.PI);
          ctx.fill();
          ctx.beginPath();
          ctx.arc(hoverPos.x, yAxis.bottom, 2, 0, 2 * Math.PI);
          ctx.fill();
          
          ctx.restore();
        }
      } catch (error) {
        console.error('Vertical line plugin error:', error);
      }
    }
  }), [sampledIndices, records, selectionStartIndex, selectionEndIndex, selectionDraft]);

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

  // Persistent render loop to ensure smooth red line and selection animation
  useEffect(() => {
    if (!isChartReady) return;
    
    let frameId: number;
    const renderLoop = () => {
      if (chartRef.current) {
        // Animate selection border if active
        if (selectionDraft || (selectionStartIndex != null && selectionEndIndex != null)) {
          lineDashOffsetRef.current = (lineDashOffsetRef.current - 0.5) % 20;
        }
        // Use update('none') instead of render() to ensure plugins are re-evaluated 
        // with latest ref values without triggering full layout animations
        chartRef.current.update('none');
      }
      frameId = requestAnimationFrame(renderLoop);
    };
    
    frameId = requestAnimationFrame(renderLoop);
    
    return () => {
      if (frameId) cancelAnimationFrame(frameId);
    };
  }, [isChartReady, selectionStartIndex, selectionEndIndex, selectionDraft]);

  // Removed the previous useEffect that was tied to currentIndex to prevent constant restarts
  // and potential "freezing" during high-frequency state updates.

  const selectionInfo = useMemo(() => {
    if (!records.length) {
      return null;
    }

    const baseTimestamp =
      records[0] && typeof records[0]._timestamp_ms === 'number' ? records[0]._timestamp_ms : 0;

    if (selectionDraft) {
      const start = Math.min(selectionDraft.startIndex, selectionDraft.currentIndex);
      const endInclusive = Math.max(selectionDraft.startIndex, selectionDraft.currentIndex);
      const startRecord = records[start];
      const endRecord = records[endInclusive];
      const startTimeMs =
        startRecord && typeof startRecord._timestamp_ms === 'number'
          ? startRecord._timestamp_ms - baseTimestamp
          : null;
      const endTimeMs =
        endRecord && typeof endRecord._timestamp_ms === 'number'
          ? endRecord._timestamp_ms - baseTimestamp
          : null;
      const durationMs =
        startTimeMs != null && endTimeMs != null ? Math.max(0, endTimeMs - startTimeMs) : null;

      return {
        startIndex: start,
        endIndex: endInclusive,
        startTimeMs,
        endTimeMs,
        durationMs,
        isDraft: true,
      };
    }

    if (selectionStartIndex != null && selectionEndIndex != null) {
      const start = Math.min(selectionStartIndex, Math.max(0, records.length - 1));
      const endInclusive = Math.min(
        Math.max(selectionEndIndex - 1, start),
        Math.max(0, records.length - 1)
      );
      const startRecord = records[start];
      const endRecord = records[endInclusive];
      const startTimeMs =
        startRecord && typeof startRecord._timestamp_ms === 'number'
          ? startRecord._timestamp_ms - baseTimestamp
          : null;
      const endTimeMs =
        endRecord && typeof endRecord._timestamp_ms === 'number'
          ? endRecord._timestamp_ms - baseTimestamp
          : null;
      const durationMs =
        startTimeMs != null && endTimeMs != null ? Math.max(0, endTimeMs - startTimeMs) : null;

      return {
        startIndex: start,
        endIndex: endInclusive,
        startTimeMs,
        endTimeMs,
        durationMs,
        isDraft: false,
      };
    }

    return null;
  }, [selectionDraft, selectionStartIndex, selectionEndIndex, records]);

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
    if (!sliderSelectionRange || !records.length) {
      return null;
    }

    const total = records.length;
    const leftPercent = (sliderSelectionRange.startIndex / total) * 100;
    const widthPercent =
      ((sliderSelectionRange.endIndex - sliderSelectionRange.startIndex) / total) * 100;

    return {
      left: `${leftPercent}%`,
      width: `max(${widthPercent}%, 2px)`,
    };
  }, [records.length, sliderSelectionRange]);

  const handleTouchStart = useCallback(
    (event: React.TouchEvent<HTMLDivElement>) => {
      if (!chartRef.current || !containerRef.current || !records.length) return;
      if (event.touches.length === 0) return;

      const touch = event.touches[0];
      const rect = containerRef.current.getBoundingClientRect();
      const x = touch.clientX - rect.left;

      const chart = chartRef.current;
      const chartArea = chart.chartArea;

      if (x < chartArea.left || x > chartArea.right) return;

      isSelectingRef.current = true;
      const clampedIndex = getIndexFromPointerX(x, chart);

      setSelectionDraft({
        startX: x,
        currentX: x,
        startIndex: clampedIndex,
        currentIndex: clampedIndex,
      });

      setCurrentIndex(clampedIndex);

      event.preventDefault();
    },
    [getIndexFromPointerX, records.length, setCurrentIndex]
  );

  const handleTouchMove = useCallback(
    (event: React.TouchEvent<HTMLDivElement>) => {
      if (!chartRef.current || !containerRef.current || !records.length) return;
      if (!selectionDraft) return;
      if (event.touches.length === 0) return;

      const touch = event.touches[0];
      const rect = containerRef.current.getBoundingClientRect();
      const x = touch.clientX - rect.left;
      const y = touch.clientY - rect.top;

      const chart = chartRef.current;
      const chartArea = chart.chartArea;

      const clampedX = Math.max(chartArea.left, Math.min(x, chartArea.right));
      const clampedIndex = getIndexFromPointerX(clampedX, chart);

      setSelectionDraft((prev) =>
        prev
          ? {
              ...prev,
              currentX: clampedX,
              currentIndex: clampedIndex,
            }
          : null
      );

      const record = records[clampedIndex];
      const steering = (record['user/angle'] as number) ?? 0;
      const throttle = (record['user/throttle'] as number) ?? 0;

      setHoverPosition({ x: clampedX, y, dataIndex: clampedIndex });
      setTooltipData({
        x: clampedX,
        y,
        steering,
        throttle,
        index: clampedIndex,
      });

      // Update tooltip position via ref for maximum performance
      if (tooltipRef.current && containerRef.current) {
        const isRightHalf = clampedX > containerRef.current.clientWidth / 2;
        const isBottomHalf = y > containerRef.current.clientHeight / 2;
        tooltipRef.current.style.left = `${clampedX}px`;
        tooltipRef.current.style.top = `${y}px`;
        tooltipRef.current.style.transform = `translate(${isRightHalf ? 'calc(-100% - 15px)' : '15px'}, ${isBottomHalf ? 'calc(-100% - 15px)' : '15px'})`;
      }

      event.preventDefault();
    },
    [getIndexFromPointerX, records, selectionDraft]
  );

  const handleTouchEnd = useCallback(
    (event: React.TouchEvent<HTMLDivElement>) => {
      isSelectingRef.current = false;
      if (!selectionDraft || !records.length) {
        setSelectionDraft(null);
        return;
      }
      
      const startIndex = Math.min(selectionDraft.startIndex, selectionDraft.currentIndex);
      const endIndex = Math.max(selectionDraft.startIndex, selectionDraft.currentIndex) + 1;

      visualSelectionRef.current = { startIndex, endIndex };
      setSelectionRange(startIndex, endIndex);
      setSelectionDraft(null);
      event.preventDefault();
    },
    [selectionDraft, setSelectionRange, records.length]
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
                  value={startIndex}
                  onChange={(e) => setStartIndex(e.target.value)}
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
                  value={endIndex}
                  onChange={(e) => setEndIndex(e.target.value)}
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
        >
          <div className="pointer-events-none absolute inset-0 h-full min-h-0 w-full">
            <Line 
              ref={chartRef} 
              options={options} 
              data={data} 
              plugins={[verticalLinePlugin]}
              onLoad={() => {
                setIsChartReady(true);
              }}
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
