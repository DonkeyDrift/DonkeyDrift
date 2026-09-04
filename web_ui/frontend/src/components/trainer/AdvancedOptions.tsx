import React, { useId, useState, useEffect } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

interface AdvancedOptionsProps {
  /** 左侧图标（lucide 元素，建议 w-5 h-5） */
  icon: React.ReactNode;
  /** 折叠框标题文案 */
  title: React.ReactNode;
  /** 是否默认展开，默认 false */
  defaultOpen?: boolean;
  /** 外部受控展开信号：从 false 变 true 时自动展开（不影响手动收起） */
  externalOpen?: boolean;
  children: React.ReactNode;
}

/**
 * 受控折叠容器：标题行可点击切换展开/收起，外观与现有卡片一致。
 * 参照 LocalConfigForm 中 ChevronDown/Up + aria-expanded 写法。
 */
export const AdvancedOptions: React.FC<AdvancedOptionsProps> = ({
  icon,
  title,
  defaultOpen = false,
  externalOpen,
  children,
}) => {
  const [open, setOpen] = useState(defaultOpen);
  const contentId = useId();

  useEffect(() => {
    if (externalOpen) setOpen(true);
  }, [externalOpen]);

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={contentId}
        className="w-full flex items-center justify-between p-4 cursor-pointer text-sm text-zinc-400 hover:text-zinc-200 transition-colors"
      >
        {/* 与 SectionCardTitle 视觉一致，但用 span 而非 h3 以保证 button 内语义合法 */}
        <div className="flex items-center gap-2">
          {icon}
          <span className="font-semibold text-white whitespace-nowrap">{title}</span>
        </div>
        {open ? (
          <ChevronUp className="w-5 h-5" />
        ) : (
          <ChevronDown className="w-5 h-5" />
        )}
      </button>
      <div
        id={contentId}
        data-testid="advanced-options-content"
        hidden={!open}
        className={open ? 'p-4 pt-0 space-y-4' : 'hidden'}
      >
        {children}
      </div>
    </div>
  );
};
