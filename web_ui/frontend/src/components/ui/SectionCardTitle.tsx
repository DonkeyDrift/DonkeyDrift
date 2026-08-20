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
  /** 悬停后淡入弹出的灰色副标题（可选） */
  subtitle?: React.ReactNode;
  /** 副标题改为跑马灯滚动（用于宽度受限处，循环从左到右展示完整文案） */
  subtitleMarquee?: boolean;
  /** 追加在标题行末尾、位于副标题之前的额外内容（如实时状态徽标） */
  children?: React.ReactNode;
}

/**
 * 全站统一的「图标小标题」：左侧图标 + 标题，悬停时在右侧淡入灰色副标题。
 * 交互细节与 TubLibrary 基准实现一致（transition-all duration-300）。
 */
export const SectionCardTitle: React.FC<SectionCardTitleProps> = ({
  icon,
  title,
  subtitle,
  subtitleMarquee = false,
  children,
  className,
  ...props
}) => {
  return (
    <CardTitle
      className={cn('flex items-center w-fit group cursor-default', className)}
      {...props}
    >
      <div className="flex items-center gap-2">
        {icon}
        <span className="whitespace-nowrap">{title}</span>
        {children}
      </div>
      {subtitle && !subtitleMarquee && (
        <span className="max-w-0 opacity-0 overflow-hidden whitespace-nowrap transition-all duration-300 ease-in-out group-hover:max-w-[300px] group-hover:opacity-100 group-hover:ml-3 text-sm text-zinc-400 font-normal">
          {subtitle}
        </span>
      )}
      {subtitle && subtitleMarquee && (
        <span className="max-w-0 opacity-0 overflow-hidden transition-[opacity,margin-left] duration-300 ease-in-out group-hover:max-w-40 group-hover:opacity-100 group-hover:ml-3 text-sm text-zinc-400 font-normal">
          <span className="inline-block whitespace-nowrap will-change-transform group-hover:animate-[marquee-x_9s_ease-in-out_infinite]">
            {subtitle}
          </span>
        </span>
      )}
    </CardTitle>
  );
};
