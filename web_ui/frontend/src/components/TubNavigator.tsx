import React, { useEffect, useState, useRef, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/Card';
import { Button } from './ui/Button';
import { useStore } from '../store/useStore';
import { getImageUrl } from '../services/api';
import { Navigation, Play, Pause, SkipBack, SkipForward, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, AlertCircle } from 'lucide-react';

export const TubNavigator: React.FC = () => {
  const { records, currentIndex, setCurrentIndex, totalRecords } = useStore();
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(100); // ms per frame, default faster
  const [imageError, setImageError] = useState(false);

  const requestRef = useRef<number>();
  const lastTimeRef = useRef<number>(0);
  const isPlayingRef = useRef(isPlaying);

  // Sync ref with state
  useEffect(() => {
    isPlayingRef.current = isPlaying;
  }, [isPlaying]);

  const currentRecord = records[currentIndex];
  
  // Find image key
  const imageKey = currentRecord ? Object.keys(currentRecord).find(k => k.endsWith('image_array')) : null;
  const imagePath = imageKey && typeof currentRecord?.[imageKey] === 'string' ? currentRecord[imageKey] : null;

  // Animation Loop
  const animate = useCallback((time: number) => {
    if (!isPlayingRef.current) return;

    if (lastTimeRef.current === 0) {
      lastTimeRef.current = time;
    }
    
    const deltaTime = time - lastTimeRef.current;

    if (deltaTime >= playbackSpeed) {
      setCurrentIndex((prev) => {
        if (prev >= totalRecords - 1) {
          setIsPlaying(false);
          return prev;
        }
        return prev + 1;
      });
      lastTimeRef.current = time;
    }
    
    requestRef.current = requestAnimationFrame(animate);
  }, [playbackSpeed, totalRecords, setCurrentIndex]);

  useEffect(() => {
    if (isPlaying) {
      lastTimeRef.current = 0;
      requestRef.current = requestAnimationFrame(animate);
    } else {
      if (requestRef.current) {
        cancelAnimationFrame(requestRef.current);
      }
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

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setCurrentIndex(parseInt(e.target.value));
    setIsPlaying(false); // Stop playing when user scrubs
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
          {/* Image Preview */}
          <div className="aspect-[4/3] bg-zinc-950 rounded-lg overflow-hidden border border-zinc-800 flex items-center justify-center relative">
            {imagePath && !imageError ? (
              <img 
                src={getImageUrl(imagePath)} 
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

          {/* Controls */}
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
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
            </div>

            <div className="flex flex-col gap-2">
               <label className="text-xs text-zinc-400">Timeline</label>
               <input 
                 type="range" 
                 min="0" 
                 max={totalRecords - 1} 
                 value={currentIndex} 
                 onChange={handleSliderChange}
                 className="w-full h-2 bg-zinc-700 rounded-lg appearance-none cursor-pointer accent-cyan-500"
               />
            </div>

            <div className="grid grid-cols-4 gap-2">
              <Button variant="secondary" size="sm" onClick={() => setCurrentIndex(Math.max(0, currentIndex - 10))}>
                <ChevronsLeft className="w-4 h-4" />
              </Button>
              <Button variant="secondary" size="sm" onClick={() => setCurrentIndex(Math.max(0, currentIndex - 1))}>
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <Button variant="secondary" size="sm" onClick={() => setCurrentIndex(Math.min(totalRecords - 1, currentIndex + 1))}>
                <ChevronRight className="w-4 h-4" />
              </Button>
              <Button variant="secondary" size="sm" onClick={() => setCurrentIndex(Math.min(totalRecords - 1, currentIndex + 10))}>
                <ChevronsRight className="w-4 h-4" />
              </Button>
            </div>
            
            <Button 
              className={`w-full flex items-center justify-center gap-2 transition-colors ${isPlaying ? 'bg-red-600 hover:bg-red-700 text-white' : ''}`}
              variant={isPlaying ? "danger" : "primary"}
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
