import React, { useRef, useEffect, useState } from 'react';
import { ChevronDown, ChevronUp, ScrollText } from 'lucide-react';
import { TrainingJob } from '../../store/useStore';
import { useTranslation } from '@/i18n';

interface LogPanelProps {
  job: TrainingJob | null;
}

const MAX_VISIBLE_LOGS = 500;

export const LogPanel: React.FC<LogPanelProps> = ({ job }) => {
  const { t } = useTranslation();
  const [isExpanded, setIsExpanded] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const logs = job?.logs ?? [];
  const visibleLogs = logs.length > MAX_VISIBLE_LOGS
    ? logs.slice(logs.length - MAX_VISIBLE_LOGS)
    : logs;

  useEffect(() => {
    if (scrollRef.current && isExpanded) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [visibleLogs.length, isExpanded]);

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg flex flex-col">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="px-4 py-2 border-b border-zinc-800 flex items-center justify-between w-full hover:bg-zinc-800/50 transition-colors"
      >
        <span className="flex items-center w-fit group cursor-default">
          <span className="flex items-center gap-2">
            <ScrollText className="w-5 h-5" />
            <span className="text-sm font-semibold leading-none tracking-tight text-white">{t('trainer.trainingLog')}</span>
          </span>
          <span className="max-w-0 opacity-0 overflow-hidden whitespace-nowrap transition-all duration-300 ease-in-out group-hover:max-w-[300px] group-hover:opacity-100 group-hover:ml-3 text-sm text-zinc-400 font-normal">
            {t('trainer.trainingLogSubtitle')}
          </span>
        </span>
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-600">{t('trainer.logLines', { count: logs.length })}</span>
          {isExpanded ? (
            <ChevronUp className="w-4 h-4 text-zinc-500" />
          ) : (
            <ChevronDown className="w-4 h-4 text-zinc-500" />
          )}
        </div>
      </button>
      {isExpanded && (
        <div
          ref={scrollRef}
          className="overflow-y-auto p-3 font-mono text-xs space-y-0.5 h-96"
        >
          {visibleLogs.length === 0 && (
            <div className="text-zinc-600 italic">{t('trainer.logEmpty')}</div>
          )}
          {visibleLogs.map((line, idx) => (
            <div key={idx} className="text-zinc-300 break-all">
              {line}
            </div>
          ))}
          {logs.length > MAX_VISIBLE_LOGS && (
            <div className="text-zinc-600 italic">
              {t('trainer.olderLinesHidden', { count: logs.length - MAX_VISIBLE_LOGS })}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
