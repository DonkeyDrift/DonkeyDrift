import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { useStore } from '../store/useStore';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import type { Chart as ChartInstance, Plugin } from 'chart.js';
import { Line } from 'react-chartjs-2';
import { LineChart } from 'lucide-react';

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend
);

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
  } = useStore();
  const chartRef = useRef<ChartInstance<'line'> | null>(null);
  const [isChartReady, setIsChartReady] = useState(false);
  const lineDashOffsetRef = useRef(0);
  const visualSelectionRef = useRef<{ startProgress: number; endProgress: number } | null>(null);
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

  useEffect(() => {
    currentIndexRef.current = currentIndex;
  }, [currentIndex]);

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
      const relativeX = clampedX - chartArea.left;
      const chartWidth = chartArea.right - chartArea.left;
      const progress = chartWidth > 0 ? relativeX / chartWidth : 0;

      const dataIndex = Math.round(progress * (records.length - 1));
      const clampedIndex = Math.max(0, Math.min(dataIndex, records.length - 1));

      const record = records[clampedIndex];
      const steering = (record['user/angle'] as number) ?? 0;
      const throttle = (record['user/throttle'] as number) ?? 0;

      setHoverPosition({ x: clampedX, y, dataIndex: clampedIndex });
      setTooltipData({
        x: event.clientX,
        y: event.clientY,
        steering,
        throttle,
        index: clampedIndex,
      });

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
    [records, selectionDraft]
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

    const relativeX = x - chartArea.left;
    const chartWidth = chartArea.right - chartArea.left;
    const progress = relativeX / chartWidth;

    const dataIndex = Math.round(progress * (records.length - 1));
    const clampedIndex = Math.max(0, Math.min(dataIndex, records.length - 1));

    setCurrentIndex(clampedIndex);
  }, [records, setCurrentIndex]);

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

      const relativeX = x - chartArea.left;
      const chartWidth = chartArea.right - chartArea.left;
      const progress = chartWidth > 0 ? relativeX / chartWidth : 0;

      const dataIndex = Math.round(progress * (records.length - 1));
      const clampedIndex = Math.max(0, Math.min(dataIndex, records.length - 1));

      setSelectionDraft({
        startX: x,
        currentX: x,
        startIndex: clampedIndex,
        currentIndex: clampedIndex,
      });

      setCurrentIndex(clampedIndex);
    },
    [records.length, setCurrentIndex]
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

      // Calculate Visual Selection
      if (chartRef.current) {
        const chart = chartRef.current;
        const chartArea = chart.chartArea;
        const chartWidth = chartArea.right - chartArea.left;
        
        const sX = Math.min(selectionDraft.startX, selectionDraft.currentX);
        const eX = Math.max(selectionDraft.startX, selectionDraft.currentX);
        const pixelDelta = Math.abs(selectionDraft.currentX - selectionDraft.startX);
        
        if (pixelDelta < 3) {
           // Snap to grid if it's a click
           const startIndex = Math.min(selectionDraft.startIndex, selectionDraft.currentIndex);
           const total = records.length;
           let pStart = startIndex / (total - 1);
           let pEnd = (startIndex + 1) / (total - 1);
           
           // If last frame, show the segment before it to make it visible
           if (startIndex === total - 1 && total > 1) {
              pStart = (total - 2) / (total - 1);
              pEnd = 1.0;
           }
           
           visualSelectionRef.current = { startProgress: pStart, endProgress: pEnd };
        } else {
           // Use exact drag position
           const pStart = Math.max(0, (sX - chartArea.left) / chartWidth);
           const pEnd = Math.min(1, (eX - chartArea.left) / chartWidth);
           visualSelectionRef.current = { startProgress: pStart, endProgress: pEnd };
        }
      }

      const startIndex = Math.min(selectionDraft.startIndex, selectionDraft.currentIndex);
      const endIndex = Math.max(selectionDraft.startIndex, selectionDraft.currentIndex) + 1;

      const pixelDelta = Math.abs(selectionDraft.currentX - selectionDraft.startX);
      const finalStart = startIndex;
      const finalEnd = pixelDelta < 3 ? startIndex + 1 : endIndex;

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
    if (!records.length) return { data: { labels: [], datasets: [] }, sampledIndices: [] as number[] };

    // Use a subset of records for performance if needed, but charting 10k points might be heavy
    // Let's sample if too many
    const maxPoints = 1000;
    const step = Math.ceil(records.length / maxPoints);
    const sampledRecords = records.filter((_, i) => i % step === 0);

    const labels = sampledRecords.map(r => r._index);
    const angleData = sampledRecords.map(r => r['user/angle']);
    const throttleData = sampledRecords.map(r => r['user/throttle']);

    return {
      data: {
        labels,
        datasets: [
          {
            label: 'Steering',
            data: angleData,
            borderColor: 'rgb(6, 182, 212)', // Cyan-500
            backgroundColor: 'rgba(6, 182, 212, 0.5)',
            borderWidth: 1,
            pointRadius: 0,
            tension: 0.1
          },
          {
            label: 'Throttle',
            data: throttleData,
            borderColor: 'rgb(234, 179, 8)', // Yellow-500
            backgroundColor: 'rgba(234, 179, 8, 0.5)',
            borderWidth: 1,
            pointRadius: 0,
             tension: 0.1
          },
        ],
      },
      sampledIndices: labels,
    };
  }, [records]);

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
    },
    scales: {
        x: {
            ticks: { color: '#71717a' }, // zinc-500
            grid: { color: '#27272a' } // zinc-800
        },
        y: {
            ticks: { color: '#71717a' },
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
        const chartWidth = chartArea.right - chartArea.left;
        
        const latestIndex = currentIndexRef.current;
        const totalRecords = records.length;
        const progress = totalRecords > 1 ? latestIndex / (totalRecords - 1) : 0;
        const currentX = chartArea.left + (progress * chartWidth);
        
        if (!isNaN(currentX) && currentX > 0 && currentX <= chartArea.right) {
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

        const drawSelectionBox = (sP: number, eP: number, isDraft: boolean) => {
            const startX = chartArea.left + sP * chartWidth;
            const endX = chartArea.left + eP * chartWidth;
            
            if (endX > startX) {
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
            const draftStartX = Math.min(selectionDraft.startX, selectionDraft.currentX);
            const draftEndX = Math.max(selectionDraft.startX, selectionDraft.currentX);
            // Convert to progress
            const sP = Math.max(0, (draftStartX - chartArea.left) / chartWidth);
            const eP = Math.min(1, (draftEndX - chartArea.left) / chartWidth); // draft is clamped to area in handleMove
            drawSelectionBox(sP, eP, true);
        } else if (visualSelectionRef.current) {
            drawSelectionBox(visualSelectionRef.current.startProgress, visualSelectionRef.current.endProgress, false);
        } else if (selectionStartIndex != null && selectionEndIndex != null && totalRecords > 1) {
             // Fallback
             let startP = Math.max(0, Math.min(selectionStartIndex, totalRecords - 1)) / (totalRecords - 1);
             let endP = Math.max(0, Math.min(selectionEndIndex, totalRecords)) / (totalRecords - 1);
             
             // Ensure the last frame selection is visible
             if (selectionEndIndex === totalRecords) {
                 endP = 1.0;
                 if (selectionStartIndex === totalRecords - 1) {
                     startP = (totalRecords - 2) / (totalRecords - 1);
                 }
             }
             
             drawSelectionBox(startP, endP, false);
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
            const vStartIdx = Math.round(visualSelectionRef.current.startProgress * (total - 1));
            if (vStartIdx !== selectionStartIndex) {
                shouldUpdate = true;
            }
        }
        
        if (shouldUpdate) {
            let startP = Math.max(0, Math.min(selectionStartIndex, total - 1)) / (total - 1);
            let endP = Math.max(0, Math.min(selectionEndIndex, total)) / (total - 1);
            
            // Ensure the last frame selection is visible
            if (selectionEndIndex === total) {
                endP = 1.0;
                if (selectionStartIndex === total - 1 && total > 1) {
                    startP = (total - 2) / (total - 1);
                }
            }
            
            visualSelectionRef.current = { startProgress: startP, endProgress: endP };
        }
    } else {
        visualSelectionRef.current = null;
    }
  }, [selectionStartIndex, selectionEndIndex, records.length]);

  useEffect(() => {
    if (!chartRef.current || !isChartReady) return;
    
    let frameId: number;
    const animate = () => {
      if (selectionDraft || visualSelectionRef.current) {
          lineDashOffsetRef.current = (lineDashOffsetRef.current - 0.5) % 20;
          chartRef.current?.render();
          frameId = requestAnimationFrame(animate);
      } else {
          chartRef.current?.render();
      }
    };
    
    animate();
    
    return () => {
      cancelAnimationFrame(frameId);
    };
  }, [currentIndex, isChartReady, hoverPosition, selectionStartIndex, selectionEndIndex, selectionDraft]);

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

      const relativeX = x - chartArea.left;
      const chartWidth = chartArea.right - chartArea.left;
      const progress = chartWidth > 0 ? relativeX / chartWidth : 0;

      const dataIndex = Math.round(progress * (records.length - 1));
      const clampedIndex = Math.max(0, Math.min(dataIndex, records.length - 1));

      setSelectionDraft({
        startX: x,
        currentX: x,
        startIndex: clampedIndex,
        currentIndex: clampedIndex,
      });

      setCurrentIndex(clampedIndex);

      event.preventDefault();
    },
    [records.length, setCurrentIndex]
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
      const relativeX = clampedX - chartArea.left;
      const chartWidth = chartArea.right - chartArea.left;
      const progress = chartWidth > 0 ? relativeX / chartWidth : 0;

      const dataIndex = Math.round(progress * (records.length - 1));
      const clampedIndex = Math.max(0, Math.min(dataIndex, records.length - 1));

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
        x: touch.clientX,
        y: touch.clientY,
        steering,
        throttle,
        index: clampedIndex,
      });

      event.preventDefault();
    },
    [records, selectionDraft]
  );

  const handleTouchEnd = useCallback(
    (event: React.TouchEvent<HTMLDivElement>) => {
      isSelectingRef.current = false;
      if (!selectionDraft || !records.length) {
        setSelectionDraft(null);
        return;
      }
      
      // Calculate Visual Selection
      if (chartRef.current) {
        const chart = chartRef.current;
        const chartArea = chart.chartArea;
        const chartWidth = chartArea.right - chartArea.left;
        
        const sX = Math.min(selectionDraft.startX, selectionDraft.currentX);
        const eX = Math.max(selectionDraft.startX, selectionDraft.currentX);
        
        // Touch drags usually don't have the pixelDelta < 3 check for clicks in the same way as mouse
        // But let's assume if it's a very small drag it's a tap
        const pixelDelta = Math.abs(selectionDraft.currentX - selectionDraft.startX);
        
        if (pixelDelta < 3) {
           const startIndex = Math.min(selectionDraft.startIndex, selectionDraft.currentIndex);
           const total = records.length;
           let pStart = startIndex / (total - 1);
           let pEnd = (startIndex + 1) / (total - 1);
           
           // If last frame, show the segment before it to make it visible
           if (startIndex === total - 1 && total > 1) {
              pStart = (total - 2) / (total - 1);
              pEnd = 1.0;
           }
           
           visualSelectionRef.current = { startProgress: pStart, endProgress: pEnd };
        } else {
           const pStart = Math.max(0, (sX - chartArea.left) / chartWidth);
           const pEnd = Math.min(1, (eX - chartArea.left) / chartWidth);
           visualSelectionRef.current = { startProgress: pStart, endProgress: pEnd };
        }
      }

      const startIndex = Math.min(selectionDraft.startIndex, selectionDraft.currentIndex);
      const endIndex = Math.max(selectionDraft.startIndex, selectionDraft.currentIndex) + 1;

      setSelectionRange(startIndex, endIndex);
      setSelectionDraft(null);
      event.preventDefault();
    },
    [selectionDraft, setSelectionRange, records.length]
  );

  if (!records.length) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <LineChart className="w-5 h-5" />
            Tub Chart
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div
            id="empty-chart"
            className="empty-chart-placeholder flex h-[300px] w-full items-center justify-center rounded-lg border border-dashed border-zinc-700 text-sm text-zinc-400"
            aria-label="empty-chart placeholder"
          >
            No data
          </div>
        </CardContent>
      </Card>
    );
  }

  // 计算同步状态信息
  const syncInfo = {
    currentIndex,
    totalRecords: records.length,
    progress: records.length > 1 ? (currentIndex / (records.length - 1) * 100).toFixed(1) : '0.0'
  };

   const containerCursorClass = selectionDraft ? 'cursor-ew-resize' : 'cursor-crosshair';

  return (
      <Card>
        <CardHeader className="relative">
          <CardTitle className="flex items-center gap-2">
            <LineChart className="w-5 h-5" />
            Tub Chart
          {isDragging && (
            <span className="ml-2 px-2 py-0.5 bg-cyan-500/20 text-cyan-400 text-xs rounded-full animate-pulse">
              Live Update
            </span>
          )}
        </CardTitle>
        <div className="text-xs text-zinc-400 mt-1">
          Index: {syncInfo.currentIndex} / {syncInfo.totalRecords - 1} ({syncInfo.progress}%)
        </div>
        {selectionInfo && (
          <div className="mt-1 text-[11px] text-cyan-300">
            <span className="font-semibold mr-1">
              {selectionInfo.isDraft ? 'Selecting' : 'Selected'}:
            </span>
            <span className="font-mono">
              [{selectionInfo.startIndex} – {selectionInfo.endIndex}]
            </span>
            {selectionInfo.startTimeMs != null && selectionInfo.endTimeMs != null && (
              <span className="ml-2 text-cyan-200/80">
                {(selectionInfo.startTimeMs / 1000).toFixed(2)}s →{' '}
                {(selectionInfo.endTimeMs / 1000).toFixed(2)}s
                {selectionInfo.durationMs != null && (
                  <> ({(selectionInfo.durationMs / 1000).toFixed(2)}s)</>
                )}
              </span>
            )}
          </div>
        )}
        {tooltipData && (
          <div 
            className="absolute top-6 right-6 pointer-events-none bg-zinc-900/95 border border-zinc-700 rounded-lg p-3 shadow-xl text-xs z-50 backdrop-blur-sm"
          >
            <div className="font-semibold text-zinc-200 mb-2">Frame: {tooltipData.index}</div>
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
      </CardHeader>
      <CardContent>
        <div 
          ref={containerRef}
          className={`h-[300px] w-full relative ${containerCursorClass} touch-none`}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
          onMouseDown={handleMouseDown}
          onMouseUp={handleMouseUp}
          onClick={handleClick}
          onTouchStart={handleTouchStart}
          onTouchMove={handleTouchMove}
          onTouchEnd={handleTouchEnd}
        >
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
      </CardContent>
    </Card>
  );
};
