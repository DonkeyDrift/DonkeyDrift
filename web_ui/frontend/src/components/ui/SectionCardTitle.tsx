import React from 'react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { CardTitle } from './Card';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export interface SectionCardTitleProps
  extends Omit<React.HTMLAttributes<HTMLHeadingElement>, 'title'> {
  /** 左侧标志图标（lucide 图标元素，建议 w-5 h-5） */
  icon: React.ReactNode;
  /** 小标题文案 */
  title: React.ReactNode;
  /** 常驻 Footnote 副标题（13px 次级文字，移动端可见；过长时省略号截断） */
  subtitle?: React.ReactNode;
  /** 追加在标题行末尾、位于副标题之前的额外内容（如实时状态徽标） */
  children?: React.ReactNode;
}

/**
 * 全站统一的「图标小标题」：左侧图标 + 标题，右侧常驻 13px 次级副标题
 * （Footnote，--ink2）；宽度不足时副标题省略号截断，不再依赖 hover 展开。
 */
export const SectionCardTitle: React.FC<SectionCardTitleProps> = ({
  icon,
  title,
  subtitle,
  children,
  className,
  ...props
}) => {
  return (
    <CardTitle
      className={cn('flex items-center w-fit cursor-default', className)}
      {...props}
    >
      <div className="flex items-center gap-2">
        {icon}
        <span className="whitespace-nowrap">{title}</span>
        {children}
      </div>
      {subtitle && (
        <span className="ml-3 min-w-0 max-w-[300px] truncate text-[13px] font-normal text-zinc-300">
          {subtitle}
        </span>
      )}
    </CardTitle>
  );
};
