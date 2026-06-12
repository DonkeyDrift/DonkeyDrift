import React from 'react';

interface ProgrammableButtonsProps {
  className?: string;
}

const BUTTONS = [
  { id: 'w1', label: 'W1', hint: '增加油门上限' },
  { id: 'w2', label: 'W2', hint: '降低油门上限' },
  { id: 'w3', label: 'W3', hint: '切换模型' },
  { id: 'w4', label: 'W4', hint: '重置方向' },
  { id: 'w5', label: 'W5', hint: '紧急停止' },
];

export const ProgrammableButtons: React.FC<ProgrammableButtonsProps> = ({ className = '' }) => {
  return (
    <div className={`flex gap-2 ${className}`}>
      {BUTTONS.map((btn) => (
        <button
          key={btn.id}
          disabled
          title={btn.hint}
          className="flex-1 h-9 rounded text-xs font-bold transition-colors bg-zinc-800 text-zinc-500 cursor-not-allowed opacity-60"
        >
          {btn.label}
        </button>
      ))}
    </div>
  );
};
