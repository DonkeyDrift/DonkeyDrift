import React, { useState } from 'react';

interface ProgrammableButtonsProps {
  onClick?: (buttonId: string) => void;
  className?: string;
}

const BUTTONS = [
  { id: 'w1', label: 'W1', hint: '增加油门上限' },
  { id: 'w2', label: 'W2', hint: '降低油门上限' },
  { id: 'w3', label: 'W3', hint: '切换模型' },
  { id: 'w4', label: 'W4', hint: '重置方向' },
  { id: 'w5', label: 'W5', hint: '紧急停止' },
];

export const ProgrammableButtons: React.FC<ProgrammableButtonsProps> = ({ onClick, className = '' }) => {
  const [pressed, setPressed] = useState<string | null>(null);

  const handleClick = (id: string) => {
    setPressed(id);
    onClick?.(id);
    setTimeout(() => setPressed(null), 150);
  };

  return (
    <div className={`flex gap-2 ${className}`}>
      {BUTTONS.map((btn) => (
        <button
          key={btn.id}
          onClick={() => handleClick(btn.id)}
          title={btn.hint}
          className={`flex-1 h-9 rounded text-xs font-bold transition-all
            ${pressed === btn.id
              ? 'bg-cyan-500 text-white scale-95'
              : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-200'
            }
          `}
        >
          {btn.label}
        </button>
      ))}
    </div>
  );
};
