import React from 'react';
import { useTranslation } from '@/i18n';

interface ProgrammableButtonsProps {
  className?: string;
}

const BUTTONS = [
  { id: 'w1', label: 'W1', hintKey: 'drive.hintW1' },
  { id: 'w2', label: 'W2', hintKey: 'drive.hintW2' },
  { id: 'w3', label: 'W3', hintKey: 'drive.hintW3' },
  { id: 'w4', label: 'W4', hintKey: 'drive.hintW4' },
  { id: 'w5', label: 'W5', hintKey: 'drive.hintW5' },
];

export const ProgrammableButtons: React.FC<ProgrammableButtonsProps> = ({ className = '' }) => {
  const { t } = useTranslation();
  return (
    <div className={`flex gap-2 ${className}`}>
      {BUTTONS.map((btn) => (
        <button
          key={btn.id}
          disabled
          title={t(btn.hintKey)}
          className="flex-1 h-9 rounded text-xs font-bold transition-colors bg-zinc-800 text-zinc-500 cursor-not-allowed opacity-60"
        >
          {btn.label}
        </button>
      ))}
    </div>
  );
};
