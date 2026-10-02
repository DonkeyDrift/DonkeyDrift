import React, { useState } from 'react';
import { ChevronDown, ChevronUp, Box } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { Menu } from '../Menu';

interface ModelSelectorProps {
  value: string;
  options: string[];
  onChange: (value: string) => void;
  disabled?: boolean;
  className?: string;
}

const EMPTY_VALUE = '';

export const ModelSelector: React.FC<ModelSelectorProps> = ({
  value,
  options,
  onChange,
  disabled = false,
  className = '',
}) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  const emptyLabel = t('drive.noModel');
  const allOptions = [EMPTY_VALUE, ...options];
  const effectiveValue = options.includes(value) ? value : EMPTY_VALUE;
  const selectedLabel = effectiveValue || emptyLabel;
  const otherOptions = allOptions.filter((v) => v !== effectiveValue);

  const handleSelect = (model: string) => {
    if (disabled) return;
    onChange(model);
    setOpen(false);
  };

  return (
    <Menu
      open={open && !disabled}
      onOpenChange={setOpen}
      data-testid="model-selector"
      className={`relative inline-block ${className}`}
      panelClassName="top-full left-0 w-full pt-1"
      trigger={
        <button
          onClick={() => !disabled && setOpen(!open)}
          disabled={disabled}
          className={`w-full px-3 py-1.5 rounded-lg border border-zinc-800 bg-zinc-900 text-xs font-medium flex items-center justify-between gap-2 text-cyan-400 hover:bg-zinc-800 transition-colors min-w-[6.5rem]
            ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
          `}
          title={t('drive.currentModel')}
        >
          <span className="flex items-center gap-1.5">
            <Box className="w-3.5 h-3.5" />
            <span className="truncate max-w-[8rem]">{selectedLabel}</span>
          </span>
          {open ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>
      }
    >
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 shadow-float overflow-hidden">
        {otherOptions.map((model) => {
          const label = model || emptyLabel;
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
    </Menu>
  );
};
