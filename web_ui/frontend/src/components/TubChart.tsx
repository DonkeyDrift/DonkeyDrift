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
import { LineChart, RotateCcw, ZoomIn, ZoomOut } from 'lucide-react';

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

export const TubChart: React.FC = () => {
  const {
    records,
    currentIndex,
    isDragging,
    setCurrentIndex,
    selectionStartIndex,
    selectionEndIndex,
    setSelectionRange,
    clearSelectionRange,
    undoSelectionRange,
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
  const [isConfirmOpen, setIsConfirmOpen] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [actionMode, setActionMode] = useState<'delete' | 'restore'>('delete');
  const [actionError, setActionError] = useState<string | null>(null);
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

  const parseRange = useCallback(() => {
    const start = Number(startIndex);
    const end = Number(endIndex);

    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end < start) {
      return null;
    }

    return { start, end };
  }, [startIndex, endIndex]);

  const handleOpenConfirm = useCallback(
    (mode: 'delete' | 'restore') => {
      const range = parseRange();
      if (!range) {
        setActionError('Invalid index range');
        return;
      }
      setActionError(null);
      setActionMode(mode);
      setIsConfirmOpen(true);
    },
    [parseRange]
  );

  const handleOpenDeleteConfirm = useCallback(() => {
    handleOpenConfirm('delete');
  }, [handleOpenConfirm]);

  const handleOpenRestoreConfirm = useCallback(() => {
    handleOpenConfirm('restore');
  }, [handleOpenConfirm]);

  const handleCancelConfirm = useCallback(() => {
    setIsConfirmOpen(false);
  }, []);

  const handleConfirmAction = useCallback(async () => {
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

    if (indexes.length === 0) {
      setActionError('No records in selected range');
      return;
    }

    setIsProcessing(true);
    try {
      if (actionMode === 'delete') {
        await deleteRecords(indexes);
      } else {
        await restoreRecords(indexes);
      }

      const data = await getRecords(0, 100000);
      const nextRecords = data.records || [];
      setAllRecords(nextRecords);
      setIsConfirmOpen(false);
      setActionError(null);
    } catch {
      setActionError(actionMode === 'delete' ? 'Delete failed' : 'Restore failed');
    } finally {
      setIsProcessing(false);
    }
  }, [actionMode, parseRange, setAllRecords, setSelectionRange]);

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

  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (!records.length) return;

      if (event.key === 'Escape') {
        event.preventDefault();
        clearSelectionRange();
        setSelectionDraft(null);
        return;
      }

      if ((event.key === 'z' || event.key === 'Z') && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        if (event.shiftKey) {
          redoSelectionRange();
        } else {
          undoSelectionRange();
        }
        return;
      }

      if ((event.key === 'y' || event.key === 'Y') && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        redoSelectionRange();
        return;
      }

      if (
        selectionStartIndex != null &&
        selectionEndIndex != null &&
        event.shiftKey &&
        (event.key === 'ArrowLeft' || event.key === 'ArrowRight')
      ) {
        event.preventDefault();
        const delta = event.key === 'ArrowLeft' ? -1 : 1;
        const start = selectionStartIndex;
        const nextEnd = Math.max(start + 1, Math.min(selectionEndIndex + delta, records.length));
        setSelectionRange(start, nextEnd);
        return;
      }

      const step = event.shiftKey ? 10 : 1;

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
      selectionStartIndex,
      selectionEndIndex,
      setSelectionRange,
      undoSelectionRange,
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
        let shouldUpdate = false;
        
        if (!visualSelectionRef.current) {
            shouldUpdate = true;
        } else {
            const vStartIdx = Math.round(visualSelectionRef.current.startIndex);
            if (vStartIdx !== selectionStartIndex) {
                shouldUpdate = true;
            }
        }
        
        if (shouldUpdate) {
            visualSelectionRef.current = {
              startIndex: Math.max(0, Math.min(selectionStartIndex, total - 1)),
              endIndex: Math.max(selectionStartIndex + 1, Math.min(selectionEndIndex, total)),
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
          <CardTitle className="flex items-center gap-2">
            <LineChart className="w-5 h-5" />
            Tub Chart
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
      <CardHeader className="relative flex flex-row items-start justify-between gap-4 space-y-0">
        <CardTitle className="flex items-center gap-2">
          <LineChart className="w-5 h-5" />
          Tub Chart
          {isDragging && (
            <span className="ml-2 px-2 py-0.5 bg-cyan-500/20 text-cyan-400 text-xs rounded-full animate-pulse">
              Live Update
            </span>
          )}
        </CardTitle>
        <div className="flex max-w-full flex-col items-end gap-2">
          <div className="flex min-h-[30px] flex-wrap items-center justify-end gap-2">
            <Input
              aria-label="Start index"
              placeholder="Start"
              value={startIndex}
              onChange={(e) => setStartIndex(e.target.value)}
              className="w-[70px] h-full text-xs"
            />
            <span className="text-xs text-zinc-400">to</span>
            <Input
              aria-label="End index"
              placeholder="End"
              value={endIndex}
              onChange={(e) => setEndIndex(e.target.value)}
              className="w-[70px] h-full text-xs"
            />
            <Button size="sm" variant="danger" onClick={handleOpenDeleteConfirm} className="h-full text-xs">
              Delete
            </Button>
            <Button size="sm" variant="secondary" onClick={handleOpenRestoreConfirm} className="h-full text-xs">
              Restore
            </Button>
            {actionError && (
              <span className="ml-2 text-xs text-red-400">
                {actionError}
              </span>
            )}
          </div>
          <div className="flex min-h-[30px] flex-wrap items-center justify-end gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={handleZoomOut}
              disabled={zoomPercent <= MIN_ZOOM_PERCENT}
              className="h-full text-xs"
              aria-label="缩小图表"
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
            >
              <ZoomIn className="h-4 w-4" />
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={handleZoomReset}
              disabled={zoomPercent === MIN_ZOOM_PERCENT}
              className="h-full text-xs"
              aria-label="还原图表缩放"
            >
              <RotateCcw className="h-4 w-4" />
            </Button>
            <div className="flex h-[18px] box-content items-center gap-2 rounded-md bg-zinc-800 px-3 text-left rotate-0">
              <div className="h-4 box-content text-xs text-zinc-400 uppercase">ZOOM</div>
              <div className="h-4 box-content text-[15px] font-mono text-cyan-400 leading-none">{zoomMultiplier}x</div>
            </div>
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
        <div className="mt-3 shrink-0">
          <input
            type="range"
            min="0"
            max="1000"
            step="1"
            value={Math.round(scrollProgress * 1000)}
            onChange={handleScrollSliderChange}
            disabled={zoomPercent === MIN_ZOOM_PERCENT || records.length <= visibleRange.visibleCount}
            aria-label="图表横向滚动"
            className="w-full h-2 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-cyan-500 disabled:cursor-not-allowed disabled:opacity-40"
          />
        </div>
        {isConfirmOpen && (
          <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60">
            <div className="rounded-lg bg-zinc-900 border border-zinc-700 p-6 w-full max-w-sm space-y-4">
              <div className="text-sm font-semibold">
                {actionMode === 'delete' ? 'Confirm deletion' : 'Confirm restore'}
              </div>
              <div className="text-xs text-zinc-300">
                {actionMode === 'delete'
                  ? 'This will delete records in the selected index range. This action cannot be undone. Continue?'
                  : 'This will restore records in the selected index range back into the active dataset. Continue?'}
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="secondary" onClick={handleCancelConfirm} disabled={isProcessing}>
                  Cancel
                </Button>
                <Button variant="danger" onClick={handleConfirmAction} disabled={isProcessing}>
                  {isProcessing ? (actionMode === 'delete' ? 'Deleting...' : 'Restoring...') : 'Confirm'}
                </Button>
              </div>
              <div className="text-[11px] text-emerald-400">
                {actionMode === 'delete'
                  ? 'Success: Records in range will be removed from the tub and chart after confirmation.'
                  : 'Success: Records in range will be restored into the tub and chart after confirmation.'}
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
