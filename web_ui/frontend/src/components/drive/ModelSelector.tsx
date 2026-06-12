import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp, Box } from 'lucide-react';

interface ModelSelectorProps {
  value: string;
  options: string[];
  onChange: (value: string) => void;
  disabled?: boolean;
  className?: string;
}

const EMPTY_VALUE = '';
const EMPTY_LABEL = '无模型';

export const ModelSelector: React.FC<ModelSelectorProps> = ({
  value,
  options,
  onChange,
  disabled = false,
  className = '',
}) => {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const allOptions = [EMPTY_VALUE, ...options];
  const effectiveValue = options.includes(value) ? value : EMPTY_VALUE;
  const selectedLabel = effectiveValue || EMPTY_LABEL;
  const otherOptions = allOptions.filter((v) => v !== effectiveValue);

  const handleSelect = (model: string) => {
    if (disabled) return;
    onChange(model);
    setOpen(false);
  };

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  return (
    <div
      ref={containerRef}
      data-testid="model-selector"
      className={`relative inline-block ${className}`}
      onMouseEnter={() => !disabled && setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        onClick={() => !disabled && setOpen(!open)}
        disabled={disabled}
        className={`w-full px-3 py-1.5 rounded-lg border border-zinc-800 bg-zinc-900 text-xs font-medium flex items-center justify-between gap-2 text-cyan-400 hover:bg-zinc-800 transition-colors min-w-[6.5rem]
          ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
        `}
        title="当前模型"
      >
        <span className="flex items-center gap-1.5">
          <Box className="w-3.5 h-3.5" />
          <span className="truncate max-w-[8rem]">{selectedLabel}</span>
        </span>
        {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
      </button>
      {open && !disabled && (
        <div className="absolute top-full left-0 w-full pt-1 z-50">
          <div className="rounded-lg border border-zinc-800 bg-zinc-900 shadow-[0_8px_24px_rgba(0,0,0,0.25)] overflow-hidden">
            {otherOptions.map((model) => {
              const label = model || EMPTY_LABEL;
              return (
                <button
                  key={label}
                  onClick={() => handleSelect(model)}
                  className="w-full px-3 py-1.5 text-xs font-medium flex items-center gap-1.5 transition-colors text-left text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800"
                  title={label}
                >
                  <Box className="w-3.5 h-3.5" />
                  <span className="truncate">{label}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
