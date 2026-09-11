import React from 'react';
import { Inbox } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { cn } from '@/lib/utils';

interface EmptyProps {
  /** 空态图标（lucide 元素），默认 Inbox */
  icon?: React.ReactNode;
  /** 空态标题，默认「暂无数据」 */
  title?: string;
  /** 一句操作引导（告诉用户下一步做什么），默认见 common.empty.hint */
  hint?: string;
  className?: string;
}

/** 统一空状态：lucide 图标 + 标题 + 一句引导，语义色全部走皮肤变量。 */
export default function Empty({ icon, title, hint, className }: EmptyProps) {
  const { t } = useTranslation();
  return (
    <div className={cn('flex h-full flex-col items-center justify-center gap-2 py-10 text-center', className)}>
      <div className="text-zinc-500">{icon ?? <Inbox className="h-8 w-8" strokeWidth={1.5} />}</div>
      <p className="text-sm font-medium text-zinc-300">{title ?? t('common.empty.title')}</p>
      <p className="text-[13px] text-zinc-500">{hint ?? t('common.empty.hint')}</p>
    </div>
  );
}
