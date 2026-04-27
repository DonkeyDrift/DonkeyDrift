import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Button } from './ui/Button';
import { useStore } from '../store/useStore';
import { getImageUrl } from '../services/api';
import { Navigation, Play, Pause, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, AlertCircle, Repeat, ArrowRightToLine } from 'lucide-react';

interface RecordStatsProps {
  steering: string;
  throttle: string;
  actualFps: number;
}

const RecordStats = React.memo(({ steering, throttle, actualFps }: RecordStatsProps) => (
  <div className="grid grid-cols-3 gap-4">
    <div className="bg-zinc-800 p-3 rounded-md">
      <div className="text-xs text-zinc-400 uppercase">STEERING</div>
      <div className="text-lg font-mono text-cyan-400">{steering}</div>
    </div>
    <div className="bg-zinc-800 p-3 rounded-md">
      <div className="text-xs text-zinc-400 uppercase">Throttle</div>
      <div className="text-lg font-mono text-cyan-400">{throttle}</div>
    </div>
    <div className="bg-zinc-800 p-3 rounded-md">
      <div className="text-xs text-zinc-400 uppercase">FPS</div>
      <div className="text-lg font-mono text-cyan-400">
        {actualFps}
      </div>
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

const TimelineSlider = React.memo(({ max, value, isDragging, onInput, onChange, onMouseDown, onMouseUp }: TimelineSliderProps) => (
  <div className="flex flex-col gap-2">
    <label className="text-xs text-zinc-400 flex items-center gap-2">
      Timeline
      {isDragging && <span className="text-cyan-400 text-xs">(Dragging...)</span>}
    </label>
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
      className={`w-full h-2 bg-zinc-700 rounded-lg appearance-none cursor-pointer ${isDragging ? 'accent-cyan-400' : 'accent-cyan-500'}`}
    />
  </div>
));

export const TubNavigator: React.FC = () => {
  const { records, currentIndex, setCurrentIndex, totalRecords, config, isDragging, setIsDragging } = useStore();
  const [isPlaying, setIsPlaying] = useState(false);
  const [isLooping, setIsLooping] = useState(false);
  const playbackSpeed = 1000 / Math.max(1, Number(config?.DRIVE_LOOP_HZ) || 60);
  const [actualFps, setActualFps] = useState(0);
  const [imageError, setImageError] = useState(false);

  const requestRef = useRef<number>();
  const lastTimeRef = useRef<number>(0);
  const isPlayingRef = useRef(isPlaying);
  const isLoopingRef = useRef(isLooping);
  const imageCacheRef = useRef<Map<string, HTMLImageElement>>(new Map());
  const fpsStartRef = useRef<number>(0);
  const fpsFramesRef = useRef<number>(0);
  const lastIndexRef = useRef(currentIndex);
  const displayIndexRef = useRef(currentIndex);

  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Sync ref with state
  useEffect(() => {
    isPlayingRef.current = isPlaying;
  }, [isPlaying]);

  useEffect(() => {
    isLoopingRef.current = isLooping;
  }, [isLooping]);

  // Sync currentIndex ref for performance optimization
  useEffect(() => {
    lastIndexRef.current = currentIndex;
  }, [currentIndex]);

  // Use a local state for the index to avoid triggering global store re-renders 60 times/sec
  const [localIndex, setLocalIndex] = useState(currentIndex);

  // Sync localIndex with global currentIndex when global changes (e.g. from other components)
  useEffect(() => {
    if (!isPlayingRef.current && !isDragging) {
      setLocalIndex(currentIndex);
      displayIndexRef.current = currentIndex;
    }
  }, [currentIndex, isDragging]);

  // Throttled sync from localIndex to global store
  useEffect(() => {
    if (isPlaying) {
      const interval = setInterval(() => {
        setCurrentIndex(displayIndexRef.current);
      }, 100); // Sync global state 10 times per second
      return () => clearInterval(interval);
    } else {
      setCurrentIndex(localIndex);
    }
  }, [isPlaying, localIndex, setCurrentIndex]);

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
      let nextIndex = displayIndexRef.current + steps;
      
      if (nextIndex >= totalRecords - 1) {
        if (isLoopingRef.current) {
          nextIndex = nextIndex % totalRecords;
        } else {
          nextIndex = totalRecords - 1;
          setIsPlaying(false);
        }
      }
      
      displayIndexRef.current = nextIndex;
      setLocalIndex(nextIndex);
      
      lastTimeRef.current = time - (deltaTime % playbackSpeed);
    }
    
    requestRef.current = requestAnimationFrame(animate);
  }, [playbackSpeed, totalRecords]);

  useEffect(() => {
    if (isPlaying) {
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
  }, [isPlaying, animate]);

  // Reset error when index changes
  useEffect(() => {
    setImageError(false);
  }, [localIndex]);

  // Handle spacebar shortcut for play/pause
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code === 'Space') {
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
        
        setIsPlaying(prev => !prev);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  useEffect(() => {
    if (!imageUrl) {
      setImageError(true);
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

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(imageToDraw, 0, 0);
    };

    if (!img) {
      img = new Image();
      img.src = imageUrl;
      imageCacheRef.current.set(imageUrl, img);
    }

    if (img.complete) {
      if (img.naturalWidth === 0) {
        if (isCurrent) handleImageError();
      } else {
        drawImage(img);
      }
    } else {
      const handleLoad = () => drawImage(img!);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageUrl, imagePath]);

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
          <div className="aspect-[4/3] bg-zinc-950 rounded-lg overflow-hidden border border-zinc-800 flex items-center justify-center relative">
            {imagePath && !imageError ? (
              <canvas
                ref={canvasRef}
                className="w-full h-full object-contain"
                width={640}
                height={480}
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
            <div className="absolute top-2 right-2 bg-black/70 px-2 py-1 rounded text-xs text-white">
              Record {localIndex} / {totalRecords - 1}
            </div>
          </div>

          <div className="space-y-6">
            <RecordStats 
              steering={getRecordValue('user/angle', 'pilot/angle')}
              throttle={getRecordValue('user/throttle', 'pilot/throttle')}
              actualFps={actualFps}
            />

            <TimelineSlider 
              max={totalRecords - 1}
              value={localIndex}
              isDragging={isDragging}
              onInput={handleSliderInput}
              onChange={handleSliderChange}
              onMouseDown={handleSliderMouseDown}
              onMouseUp={handleSliderMouseUp}
            />

            <div className="grid grid-cols-4 gap-2">
              <Button
                variant="secondary"
                size="sm"
                aria-label="First record"
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

            <div className="flex gap-2">
              <Button 
                className="flex-1"
                variant={isPlaying ? "danger" : "primary"}
                aria-label={isPlaying ? 'Stop playback' : 'Start playback'}
                onClick={() => setIsPlaying(!isPlaying)}
              >
                {isPlaying ? <><Pause className="w-4 h-4" /> Stop</> : <><Play className="w-4 h-4" /> Play</>}
              </Button>
              
              <Button
                variant={isLooping ? "primary" : "secondary"}
                aria-label={isLooping ? 'Loop mode active' : 'Play once mode'}
                onClick={() => setIsLooping(!isLooping)}
                title={isLooping ? "循环播放" : "播放后停止"}
                className="px-3"
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
