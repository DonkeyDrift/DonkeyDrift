import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Button } from './ui/Button';
import { useStore } from '../store/useStore';
import { getImageUrl } from '../services/api';
import { Navigation, Play, Pause, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, AlertCircle, Repeat, ArrowRightToLine } from 'lucide-react';

interface RecordStatsProps {
  steering: string;
  throttle: string;
}

const RecordStats = React.memo(({ steering, throttle }: RecordStatsProps) => (
  <div className="flex gap-4 text-left">
    <div className="bg-zinc-800 rounded-md flex h-[60px] w-[88px] flex-col items-start justify-center px-3 pt-[10px] pb-[10px] text-left">
      <div className="text-xs text-zinc-400 uppercase">STEERING</div>
      <div className="text-lg font-mono text-cyan-400">{steering}</div>
    </div>
    <div className="bg-zinc-800 rounded-md flex h-[60px] w-[88px] flex-col items-start justify-center px-3 pt-[10px] pb-[10px] text-left">
      <div className="text-xs text-zinc-400 uppercase">Throttle</div>
      <div className="text-lg font-mono text-cyan-400">{throttle}</div>
    </div>
  </div>
));

interface TimelineSliderProps {
  max: number;
  value: number;
  isDragging: boolean;
  onInput: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onMouseDown: () => void;
  onMouseUp: () => void;
}

const TimelineSlider = React.memo(({ max, value, isDragging, onInput, onChange, onMouseDown, onMouseUp, recordIndex, totalRecords }: TimelineSliderProps & { recordIndex: number; totalRecords: number }) => {
  const progress = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;
  const accentColor = isDragging ? '#22d3ee' : '#06b6d4';

  return (
    <div className="flex flex-col gap-2">
      <div className="w-full flex items-center gap-2 justify-between">
        <label className="text-xs text-zinc-400 flex items-center gap-2">
          Timeline
          {isDragging && <span className="text-cyan-400 text-xs">(Dragging...)</span>}
        </label>
        <span className="text-xs text-white bg-black/70 px-2 py-1 rounded">Index {recordIndex} / {totalRecords}</span>
      </div>
      <input 
        type="range" 
        min="0" 
        max={max} 
        value={value} 
        onInput={onInput}
        onChange={onChange}
        onMouseDown={onMouseDown}
        onMouseUp={onMouseUp}
        onTouchStart={onMouseDown}
        onTouchEnd={onMouseUp}
        style={{ background: `linear-gradient(to right, ${accentColor} 0%, ${accentColor} ${progress}%, #3f3f46 ${progress}%, #3f3f46 100%)` }}
        className={`w-full h-2 rounded-lg appearance-none cursor-pointer ${isDragging ? 'accent-cyan-400' : 'accent-cyan-500'}`}
      />
    </div>
  );
});

export const TubNavigator: React.FC = () => {
  const records = useStore((state) => state.records);
  const setCurrentIndex = useStore((state) => state.setCurrentIndex);
  const totalRecords = useStore((state) => state.totalRecords);
  const tubTotalRecords = useStore((state) => state.tubTotalRecords);
  const config = useStore((state) => state.config);
  const isDragging = useStore((state) => state.isDragging);
  const setIsDragging = useStore((state) => state.setIsDragging);
  const isPlaying = useStore((state) => state.isPlaying);
  const setIsPlaying = useStore((state) => state.setIsPlaying);
  const isLooping = useStore((state) => state.isLooping);
  const setIsLooping = useStore((state) => state.setIsLooping);
  const playbackSpeed = 1000 / Math.max(1, Number(config?.DRIVE_LOOP_HZ) || 60);
  const [actualFps, setActualFps] = useState(0);
  const [imageError, setImageError] = useState(false);

  const requestRef = useRef<number>();
  const lastTimeRef = useRef<number>(0);
  const isPlayingRef = useRef(isPlaying);
  const isLoopingRef = useRef(isLooping);
  const currentIndexRef = useRef(useStore.getState().currentIndex);
  const selectionRangeRef = useRef<{ start: number | null; end: number | null }>({
    start: useStore.getState().selectionStartIndex,
    end: useStore.getState().selectionEndIndex,
  });
  const imageCacheRef = useRef<Map<string, HTMLImageElement>>(new Map());
  const fpsStartRef = useRef<number>(0);
  const fpsFramesRef = useRef<number>(0);
  const displayIndexRef = useRef(currentIndexRef.current);

  const canvasRef = useRef<HTMLCanvasElement>(null);

  const lastSyncTimeRef = useRef<number>(0);

  // Sync ref with state
  useEffect(() => {
    isPlayingRef.current = isPlaying;
    if (!isPlaying) {
      // Ensure final sync when stopping
      setCurrentIndex(displayIndexRef.current);
    }
  }, [isPlaying, setCurrentIndex]);

  useEffect(() => {
    isLoopingRef.current = isLooping;
  }, [isLooping]);

  useEffect(() => {
    const unsubscribe = useStore.subscribe((state) => {
      currentIndexRef.current = state.currentIndex;
      
      const prevStart = selectionRangeRef.current.start;
      const prevEnd = selectionRangeRef.current.end;

      selectionRangeRef.current = {
        start: state.selectionStartIndex,
        end: state.selectionEndIndex,
      };

      // Stop playback if selection becomes exactly 1 frame
      if (
        state.selectionStartIndex !== null &&
        state.selectionEndIndex !== null &&
        state.selectionEndIndex - state.selectionStartIndex === 1
      ) {
        if (state.selectionStartIndex !== prevStart || state.selectionEndIndex !== prevEnd) {
          setIsPlaying(false);
          isPlayingRef.current = false;
        }
      }

      if (!isPlayingRef.current && !isDragging) {
        setLocalIndex((prev) => {
          if (prev === state.currentIndex) {
            return prev;
          }
          return state.currentIndex;
        });
        displayIndexRef.current = state.currentIndex;
      }
    });

    return unsubscribe;
  }, [isDragging]);

  // Use a local state for the index to avoid triggering global store re-renders 60 times/sec
  const [localIndex, setLocalIndex] = useState(currentIndexRef.current);

  // Removed the throttled setInterval effect as we'll sync directly in the animation loop
  // for better responsiveness and to avoid interval/animation-frame conflicts.

  const currentRecord = records[localIndex];
  
  // Find image key
  const imageKey = currentRecord ? Object.keys(currentRecord).find(k => k.endsWith('image_array')) : null;
  const imagePath = imageKey && typeof currentRecord?.[imageKey] === 'string' ? currentRecord[imageKey] : null;
  const imageUrl = useMemo(() => (imagePath ? getImageUrl(imagePath) : null), [imagePath]);

  // Animation Loop - 优化同步性能
  const animate = useCallback((time: number) => {
    if (!isPlayingRef.current) return;

    if (fpsStartRef.current === 0) {
      fpsStartRef.current = time;
    }
    fpsFramesRef.current += 1;
    const fpsElapsed = time - fpsStartRef.current;
    if (fpsElapsed >= 1000) {
      setActualFps(Math.round((fpsFramesRef.current * 1000) / fpsElapsed));
      fpsStartRef.current = time;
      fpsFramesRef.current = 0;
    }

    if (lastTimeRef.current === 0) {
      lastTimeRef.current = time;
    }
    
    const deltaTime = time - lastTimeRef.current;

    if (deltaTime >= playbackSpeed) {
      const steps = Math.floor(deltaTime / playbackSpeed);
      let nextIndex = (displayIndexRef.current || 0) + steps;
      
      const { start, end } = selectionRangeRef.current;
      const hasSelection = start !== null && end !== null && (end - start > 1);

      if (hasSelection) {
        if (isLoopingRef.current) {
          // Loop within selection range
          const range = end - start;
          if (range > 0 && (nextIndex >= end || nextIndex < start)) {
            nextIndex = start + (Math.max(0, nextIndex - start) % range);
          }
        } else {
          // Play once within selection range
          if (nextIndex >= end) {
            nextIndex = end - 1;
            setIsPlaying(false);
          } else if (nextIndex < start) {
            nextIndex = start;
          }
        }
      } else {
        // Normal playback or loop (no selection)
        if (nextIndex >= totalRecords) {
          if (isLoopingRef.current && totalRecords > 0) {
            nextIndex = nextIndex % totalRecords;
          } else {
            nextIndex = Math.max(0, totalRecords - 1);
            setIsPlaying(false);
          }
        } else if (nextIndex < 0) {
          nextIndex = 0;
        }
      }
      
      // Final safety check
      if (isNaN(nextIndex)) nextIndex = 0;
      
      displayIndexRef.current = nextIndex;
      setLocalIndex(nextIndex);

      // Sync to global store - throttled to ~30fps
      if (time - lastSyncTimeRef.current > 30) {
        setCurrentIndex(nextIndex);
        lastSyncTimeRef.current = time;
      }
      
      lastTimeRef.current = time - (deltaTime % playbackSpeed);
    }
    
    requestRef.current = requestAnimationFrame(animate);
  }, [playbackSpeed, totalRecords, setCurrentIndex]);

  useEffect(() => {
    if (isPlaying) {
      // If we have a selection > 1 frame and we're outside of it, jump to start
      const { start, end } = selectionRangeRef.current;
      const currentPos = displayIndexRef.current;
      
      if (start !== null && end !== null && (end - start > 1)) {
        if (currentPos >= end - 1 || currentPos < start) {
          displayIndexRef.current = start;
          setLocalIndex(start);
          setCurrentIndex(start);
        }
      } else {
        // If no selection and at the very end, jump to beginning
        if (currentPos >= totalRecords - 1) {
          displayIndexRef.current = 0;
          setLocalIndex(0);
          setCurrentIndex(0);
        }
      }

      lastTimeRef.current = 0;
      fpsStartRef.current = 0;
      fpsFramesRef.current = 0;
      requestRef.current = requestAnimationFrame(animate);
    } else {
      if (requestRef.current) {
        cancelAnimationFrame(requestRef.current);
      }
      setActualFps(0);
    }
    return () => {
      if (requestRef.current) {
        cancelAnimationFrame(requestRef.current);
      }
    };
  }, [isPlaying, animate, totalRecords, setCurrentIndex]);

  // Reset error when index changes
  useEffect(() => {
    setImageError(false);
  }, [localIndex]);

  // Handle spacebar shortcut for play/pause and M for loop mode
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code === 'Space' || e.code === 'KeyM') {
        // Ignore if user is typing in a text input or textarea
        if (
          document.activeElement instanceof HTMLInputElement && 
          document.activeElement.type !== 'range' &&
          document.activeElement.type !== 'checkbox' &&
          document.activeElement.type !== 'radio' &&
          document.activeElement.type !== 'button' &&
          document.activeElement.type !== 'submit'
        ) {
          return;
        }
        
        if (document.activeElement instanceof HTMLTextAreaElement || document.activeElement instanceof HTMLSelectElement) {
          return;
        }
        
        // Prevent page scroll and default button/range behavior
        e.preventDefault(); 
        
        if (e.code === 'Space') {
          setIsPlaying(!isPlayingRef.current);
        } else if (e.code === 'KeyM') {
          setIsLooping(!isLoopingRef.current);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  useEffect(() => {
    if (!imageUrl) {
      setImageError(false);
      
      // Attempt to clear canvas when no image
      const canvas = canvasRef.current;
      if (canvas) {
        const ctx = canvas.getContext('2d');
        if (ctx) {
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          // Draw a placeholder or just leave it blank, but ensure we don't hold old data
          ctx.fillStyle = '#18181b'; // zinc-900 to match background roughly
          ctx.fillRect(0, 0, canvas.width, canvas.height);
          
          // Draw some text to indicate no image
          ctx.fillStyle = '#52525b'; // zinc-500
          ctx.font = '14px sans-serif';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          ctx.fillText('No Image Available', canvas.width / 2, canvas.height / 2);
        }
      }
      return;
    }

    let isCurrent = true;
    let img = imageCacheRef.current.get(imageUrl);

    const drawImage = (imageToDraw: HTMLImageElement) => {
      if (!isCurrent) return;
      setImageError(false);
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      // Adjust canvas resolution to match image
      if (canvas.width !== imageToDraw.width || canvas.height !== imageToDraw.height) {
        canvas.width = imageToDraw.width;
        canvas.height = imageToDraw.height;
      }

      // Ensure clear before draw to prevent ghosting
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(imageToDraw, 0, 0);
    };

    if (!img) {
      img = new Image();
      // Removing crossOrigin as it may cause CORS failures on local servers
      // if the backend doesn't explicitly send Access-Control-Allow-Origin headers.
      img.src = imageUrl;
      imageCacheRef.current.set(imageUrl, img);
    }

    if (img.complete) {
      if (img.naturalWidth === 0) {
        if (isCurrent) handleImageError();
      } else {
        // Use requestAnimationFrame to ensure the browser has time to paint
        requestAnimationFrame(() => drawImage(img as HTMLImageElement));
      }
    } else {
      const handleLoad = () => {
        if (isCurrent) {
          requestAnimationFrame(() => drawImage(img as HTMLImageElement));
        }
      };
      const handleError = () => {
        if (isCurrent) handleImageError();
      };
      
      img.addEventListener('load', handleLoad);
      img.addEventListener('error', handleError);
      
      return () => {
        isCurrent = false;
        img?.removeEventListener('load', handleLoad);
        img?.removeEventListener('error', handleError);
      };
    }

    return () => {
      isCurrent = false;
    };
    // Removed imagePath from dependencies to avoid redundant triggers, imageUrl is sufficient
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageUrl]);

  useEffect(() => {
    if (!records.length) return;
    for (let offset = 1; offset <= 10; offset += 1) { // Preload 10 frames instead of 3
      const nextRecord = records[localIndex + offset];
      if (!nextRecord) continue;
      const nextKey = Object.keys(nextRecord).find((k) => k.endsWith('image_array'));
      const nextPath = nextKey && typeof nextRecord?.[nextKey] === 'string' ? nextRecord[nextKey] : null;
      if (!nextPath) continue;
      const url = getImageUrl(nextPath);
      if (imageCacheRef.current.has(url)) continue;
      const img = new Image();
      img.src = url;
      imageCacheRef.current.set(url, img);
    }
  }, [localIndex, records]);

  const handleSliderInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const newIndex = parseInt(e.target.value);
    setIsPlaying(false); // Stop playing when user scrubs
    displayIndexRef.current = newIndex;
    setLocalIndex(newIndex);
  }, []);

  const handleSliderChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const newIndex = parseInt(e.target.value);
    setIsPlaying(false); // Stop playing when user scrubs
    setIsDragging(false); // End dragging
    displayIndexRef.current = newIndex;
    setLocalIndex(newIndex);
    setCurrentIndex(newIndex);
  }, [setCurrentIndex, setIsDragging]);

  const handleSliderMouseDown = useCallback(() => {
    setIsDragging(true);
    setIsPlaying(false);
  }, [setIsDragging]);

  const handleSliderMouseUp = useCallback(() => {
    setIsDragging(false);
  }, [setIsDragging]);

  const handleImageError = useCallback(() => {
    console.error(`Failed to load image for record ${localIndex}: ${imagePath}`);
    setImageError(true);
    if (isPlayingRef.current) {
      setIsPlaying(false);
    }
  }, [localIndex, imagePath]);

  if (!records.length) {
    return (
      <Card className="opacity-50 pointer-events-none">
        <CardHeader>
          <CardTitle>Tub Navigator</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-64 flex items-center justify-center bg-zinc-950 rounded-lg border border-zinc-800 text-zinc-600">
            No records loaded
          </div>
        </CardContent>
      </Card>
    );
  }

  const formatValue = (value: unknown) => {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value.toFixed(2);
    }
    if (typeof value === 'string') {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) {
        return parsed.toFixed(2);
      }
    }
    return 'N/A';
  };

  const getRecordValue = (key: string, altKey?: string) => {
    const val = currentRecord?.[key] ?? (altKey ? currentRecord?.[altKey] : undefined);
    return formatValue(val);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center w-fit group cursor-default">
          <div className="flex items-center gap-2">
            <Navigation className="w-5 h-5" />
            <span>Tub Navigator</span>
          </div>
          <span className="text-sm text-zinc-400 font-normal max-w-0 opacity-0 overflow-hidden whitespace-nowrap transition-all duration-300 ease-in-out group-hover:max-w-[300px] group-hover:opacity-100 group-hover:ml-3">
            Navigate through tub records
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="w-full md:max-w-[40vw] aspect-[4/3] bg-zinc-950 rounded-lg overflow-hidden border border-zinc-800 flex items-center justify-center relative">
            <div className="absolute right-2 top-2 z-10 rounded-md border border-white/10 bg-zinc-900/35 px-2 py-1 text-center shadow-[0_8px_24px_rgba(0,0,0,0.25)] backdrop-blur-md">
              <div className="text-[10px] text-zinc-400 uppercase leading-none">FPS</div>
              <div className="text-base font-mono leading-tight text-cyan-400">{actualFps}</div>
            </div>
            {imagePath && !imageError ? (
              <canvas
                ref={canvasRef}
                className="w-full h-full object-contain"
                width={640}
                height={240}
              />
            ) : (
              <div className="flex flex-col items-center justify-center text-zinc-600 gap-2">
                {imageError ? (
                  <>
                    <AlertCircle className="w-8 h-8 text-red-500" />
                    <span className="text-red-500">Image Load Error</span>
                  </>
                ) : (
                  <span>No Image</span>
                )}
              </div>
            )}
          </div>

          <div className="space-y-6">
            <RecordStats 
              steering={getRecordValue('user/angle', 'pilot/angle')}
              throttle={getRecordValue('user/throttle', 'pilot/throttle')}
            />

            <TimelineSlider 
              max={totalRecords - 1}
              value={localIndex}
              isDragging={isDragging}
              onInput={handleSliderInput}
              onChange={handleSliderChange}
              onMouseDown={handleSliderMouseDown}
              onMouseUp={handleSliderMouseUp}
              recordIndex={localIndex}
              totalRecords={tubTotalRecords}
            />

            <div className="grid grid-cols-4 gap-2">
              <Button
                variant="secondary"
                size="sm"
                aria-label="First record"
                disabled={isPlaying}
                onClick={() => {
                  setLocalIndex(0);
                  displayIndexRef.current = 0;
                  setCurrentIndex(0);
                }}
              >
                <ChevronsLeft className="w-4 h-4" />
                <span className="ml-1 text-xs">First</span>
              </Button>
              <Button
                variant="secondary"
                size="sm"
                aria-label="Previous record"
                disabled={isPlaying}
                onClick={() => {
                  const newIndex = Math.max(0, localIndex - 1);
                  setLocalIndex(newIndex);
                  displayIndexRef.current = newIndex;
                  setCurrentIndex(newIndex);
                }}
              >
                <ChevronLeft className="w-4 h-4" />
                <span className="ml-1 text-xs">Prev</span>
              </Button>
              <Button
                variant="secondary"
                size="sm"
                aria-label="Next record"
                disabled={isPlaying}
                onClick={() => {
                  const newIndex = Math.min(totalRecords - 1, localIndex + 1);
                  setLocalIndex(newIndex);
                  displayIndexRef.current = newIndex;
                  setCurrentIndex(newIndex);
                }}
              >
                <ChevronRight className="w-4 h-4" />
                <span className="ml-1 text-xs">Next</span>
              </Button>
              <Button
                variant="secondary"
                size="sm"
                aria-label="Last record"
                disabled={isPlaying}
                onClick={() => {
                  const newIndex = Math.max(0, totalRecords - 1);
                  setLocalIndex(newIndex);
                  displayIndexRef.current = newIndex;
                  setCurrentIndex(newIndex);
                }}
              >
                <ChevronsRight className="w-4 h-4" />
                <span className="ml-1 text-xs">Last</span>
              </Button>
            </div>

            <div className="flex gap-2 h-[30px]">
              <Button 
                size="sm"
                className="flex-1 h-full"
                variant={isPlaying ? "danger" : "primary"}
                aria-label={isPlaying ? 'Stop playback' : 'Start playback'}
                onClick={() => setIsPlaying(!isPlaying)}
              >
                {isPlaying ? <><Pause className="w-4 h-4" /> Stop</> : <><Play className="w-4 h-4" /> Play</>}
              </Button>
              
              <Button
                size="sm"
                variant={isLooping ? "primary" : "secondary"}
                aria-label={isLooping ? 'Loop mode active' : 'Play once mode'}
                onClick={() => setIsLooping(!isLooping)}
                title={isLooping ? "循环播放 (M)" : "播放后停止 (M)"}
                className="px-3 h-full"
              >
                {isLooping ? <Repeat className="w-4 h-4" /> : <ArrowRightToLine className="w-4 h-4" />}
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
