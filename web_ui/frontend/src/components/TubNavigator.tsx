import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Button } from './ui/Button';
import { useStore } from '../store/useStore';
import { getImageUrl } from '../services/api';
import { Navigation, Play, Pause, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, AlertCircle } from 'lucide-react';

export const TubNavigator: React.FC = () => {
  const { records, currentIndex, setCurrentIndex, totalRecords, config, isDragging, setIsDragging } = useStore();
  const [isPlaying, setIsPlaying] = useState(false);
  const playbackSpeed = 1000 / Math.max(1, Number(config?.DRIVE_LOOP_HZ) || 60);
  const playbackFps = Math.round(1000 / playbackSpeed);
  const [actualFps, setActualFps] = useState(0);
  const [imageError, setImageError] = useState(false);

  const requestRef = useRef<number>();
  const lastTimeRef = useRef<number>(0);
  const isPlayingRef = useRef(isPlaying);
  const imageCacheRef = useRef<Map<string, HTMLImageElement>>(new Map());
  const fpsStartRef = useRef<number>(0);
  const fpsFramesRef = useRef<number>(0);
  const lastIndexRef = useRef(currentIndex);

  // Sync ref with state
  useEffect(() => {
    isPlayingRef.current = isPlaying;
  }, [isPlaying]);

  // Sync currentIndex ref for performance optimization
  useEffect(() => {
    lastIndexRef.current = currentIndex;
  }, [currentIndex]);

  const currentRecord = records[currentIndex];
  
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
      const nextIndex = Math.min(totalRecords - 1, lastIndexRef.current + steps);
      
      if (nextIndex >= totalRecords - 1) {
        setIsPlaying(false);
      }
      
      // 直接更新索引，避免函数调用开销
      lastIndexRef.current = nextIndex;
      setCurrentIndex(nextIndex);
      
      lastTimeRef.current = time - (deltaTime % playbackSpeed);
    }
    
    requestRef.current = requestAnimationFrame(animate);
  }, [playbackSpeed, totalRecords, setCurrentIndex]);

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
  }, [currentIndex]);

  const preloadImage = useCallback((path: string | null) => {
    if (!path) return;
    if (imageCacheRef.current.has(path)) return;
    const img = new Image();
    img.src = getImageUrl(path);
    imageCacheRef.current.set(path, img);
  }, []);

  useEffect(() => {
    if (!records.length) return;
    for (let offset = 1; offset <= 3; offset += 1) {
      const nextRecord = records[currentIndex + offset];
      if (!nextRecord) continue;
      const nextKey = Object.keys(nextRecord).find((k) => k.endsWith('image_array'));
      const nextPath = nextKey && typeof nextRecord?.[nextKey] === 'string' ? nextRecord[nextKey] : null;
      preloadImage(nextPath);
    }
  }, [currentIndex, records, preloadImage]);

  const handleSliderInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newIndex = parseInt(e.target.value);
    setIsPlaying(false); // Stop playing when user scrubs
    lastIndexRef.current = newIndex;
    setCurrentIndex(newIndex);
  };

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newIndex = parseInt(e.target.value);
    setIsPlaying(false); // Stop playing when user scrubs
    setIsDragging(false); // End dragging
    lastIndexRef.current = newIndex;
    setCurrentIndex(newIndex);
  };

  const handleSliderMouseDown = () => {
    setIsDragging(true);
    setIsPlaying(false);
  };

  const handleSliderMouseUp = () => {
    setIsDragging(false);
  };

  const handleImageError = () => {
    // Ignore errors during playback as they might be due to rapid switching/cancellation
    if (isPlayingRef.current) return;
    
    console.error(`Failed to load image for record ${currentIndex}: ${imagePath}`);
    setImageError(true);
  };

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
        <CardTitle className="flex items-center gap-2">
          <Navigation className="w-5 h-5" />
          Tub Navigator
        </CardTitle>
        <p className="text-sm text-zinc-400">Navigate through tub records</p>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="aspect-[4/3] bg-zinc-950 rounded-lg overflow-hidden border border-zinc-800 flex items-center justify-center relative">
            {imagePath && !imageError ? (
              <img 
                src={imageUrl ?? undefined} 
                alt={`Record ${currentIndex}`} 
                className="w-full h-full object-contain"
                onError={handleImageError}
                loading="eager"
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
              Record {currentIndex} / {totalRecords - 1}
            </div>
          </div>

          <div className="space-y-6">
            <div className="grid grid-cols-3 gap-4">
               {/* Display key values */}
               <div className="bg-zinc-800 p-3 rounded-md">
                 <div className="text-xs text-zinc-400 uppercase">Angle</div>
                 <div className="text-xl font-mono text-cyan-400">
                   {getRecordValue('user/angle', 'pilot/angle')}
                 </div>
               </div>
               <div className="bg-zinc-800 p-3 rounded-md">
                 <div className="text-xs text-zinc-400 uppercase">Throttle</div>
                 <div className="text-xl font-mono text-cyan-400">
                   {getRecordValue('user/throttle', 'pilot/throttle')}
                 </div>
               </div>
               <div className="bg-zinc-800 p-3 rounded-md">
                 <div className="text-xs text-zinc-400 uppercase">FPS</div>
                 <div className="text-xl font-mono text-cyan-400">
                   {playbackFps} / {actualFps}
                 </div>
               </div>
            </div>

            <div className="flex flex-col gap-2">
               <label className="text-xs text-zinc-400 flex items-center gap-2">
                 Timeline
                 {isDragging && <span className="text-cyan-400 text-xs">(Dragging...)</span>}
               </label>
               <input 
                 type="range" 
                 min="0" 
                 max={totalRecords - 1} 
                 value={currentIndex} 
                 onInput={handleSliderInput}
                 onChange={handleSliderChange}
                 onMouseDown={handleSliderMouseDown}
                 onMouseUp={handleSliderMouseUp}
                 onTouchStart={handleSliderMouseDown}
                 onTouchEnd={handleSliderMouseUp}
                 className={`w-full h-2 bg-zinc-700 rounded-lg appearance-none cursor-pointer ${isDragging ? 'accent-cyan-400' : 'accent-cyan-500'}`}
               />
            </div>

            <div className="grid grid-cols-4 gap-2">
              <Button
                variant="secondary"
                size="sm"
                aria-label="First record"
                onClick={() => setCurrentIndex(0)}
              >
                <ChevronsLeft className="w-4 h-4" />
                <span className="ml-1 text-xs">First</span>
              </Button>
              <Button
                variant="secondary"
                size="sm"
                aria-label="Previous record"
                onClick={() => setCurrentIndex(Math.max(0, currentIndex - 1))}
              >
                <ChevronLeft className="w-4 h-4" />
                <span className="ml-1 text-xs">Prev</span>
              </Button>
              <Button
                variant="secondary"
                size="sm"
                aria-label="Next record"
                onClick={() => setCurrentIndex(Math.min(totalRecords - 1, currentIndex + 1))}
              >
                <ChevronRight className="w-4 h-4" />
                <span className="ml-1 text-xs">Next</span>
              </Button>
              <Button
                variant="secondary"
                size="sm"
                aria-label="Last record"
                onClick={() => setCurrentIndex(Math.max(0, totalRecords - 1))}
              >
                <ChevronsRight className="w-4 h-4" />
                <span className="ml-1 text-xs">Last</span>
              </Button>
            </div>

            <div className="text-xs text-zinc-400">
              Current record: {currentIndex + 1} of {totalRecords}
            </div>
            
            <Button 
              className="w-full"
              variant={isPlaying ? "danger" : "primary"}
              aria-label={isPlaying ? 'Stop playback' : 'Start playback'}
              onClick={() => setIsPlaying(!isPlaying)}
            >
              {isPlaying ? <><Pause className="w-4 h-4" /> Stop</> : <><Play className="w-4 h-4" /> Play</>}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
