import React from 'react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export const Input: React.FC<InputProps> = ({ className, ...props }) => {
  return (
    <input
      className={cn(
        // 边框用 border-zinc-600（theme-*.css 映射 --line-mid，即 Apple separator 强档）：
        // 弱档 hairline 叠在与卡片同族的 --surface2 底上几乎看不见（浅色主题实测融进卡片），
        // 强档让输入框边界在深/浅主题都清晰可见；底色 bg-zinc-800 → --surface2 与卡片区分。
        'flex h-10 w-full rounded-md border border-zinc-600 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-transparent disabled:cursor-not-allowed disabled:opacity-50',
        className
      )}
      {...props}
    />
  );
};
