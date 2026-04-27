import React, { useState } from 'react';
import { HelpCircle, X, Keyboard } from 'lucide-react';

export const HelpModal: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      {/* Floating Help Button Container */}
      <div className="fixed bottom-6 right-6 z-50 flex flex-col items-center group">
        {/* Tooltip */}
        <div className="pointer-events-none absolute bottom-full mb-1 flex origin-bottom flex-col items-center opacity-0 transition-all duration-200 group-hover:-translate-y-1 group-hover:opacity-100">
          <div className="rounded bg-zinc-800 px-3 py-1.5 text-sm font-medium text-zinc-200 shadow-lg border border-zinc-700/50 backdrop-blur whitespace-nowrap">
            Help
          </div>
          {/* Tooltip arrow */}
          <div className="h-0 w-0 border-l-[6px] border-r-[6px] border-t-[6px] border-l-transparent border-r-transparent border-t-zinc-800"></div>
        </div>

        {/* Button */}
        <button
          onClick={() => setIsOpen(true)}
          className="flex h-12 w-12 items-center justify-center rounded-full bg-zinc-800/80 text-zinc-400 shadow-lg backdrop-blur transition-all hover:bg-zinc-700 hover:text-zinc-100 hover:shadow-cyan-500/20"
          aria-label="Help and Shortcuts"
        >
          <HelpCircle className="h-6 w-6" />
        </button>
      </div>

      {/* Glassmorphism Modal */}
      {isOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm transition-opacity"
            onClick={() => setIsOpen(false)}
          />

          {/* Modal Content */}
          <div className="relative w-full max-w-lg rounded-xl border border-zinc-700/50 bg-zinc-900/70 p-6 text-zinc-200 shadow-2xl backdrop-blur-md">
            <div className="mb-6 flex items-center justify-between border-b border-zinc-700/50 pb-4">
              <h2 className="flex items-center gap-2 text-xl font-semibold text-zinc-100">
                <Keyboard className="h-5 w-5 text-cyan-400" />
                快捷键说明
              </h2>
              <button
                onClick={() => setIsOpen(false)}
                className="rounded-full p-1 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-100"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-6">
              {/* Playback Controls */}
              <section>
                <h3 className="mb-3 text-sm font-medium uppercase tracking-wider text-zinc-500">
                  播放控制
                </h3>
                <ul className="space-y-2 text-sm">
                  <li className="flex items-center justify-between">
                    <span>播放 / 暂停</span>
                    <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">Space</kbd>
                  </li>
                </ul>
              </section>

              {/* Navigation */}
              <section>
                <h3 className="mb-3 text-sm font-medium uppercase tracking-wider text-zinc-500">
                  时间轴导航
                </h3>
                <ul className="space-y-2 text-sm">
                  <li className="flex items-center justify-between">
                    <span>上一帧 / 下一帧</span>
                    <div className="flex gap-1">
                      <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">←</kbd>
                      <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">→</kbd>
                    </div>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>跳转至首帧 / 尾帧</span>
                    <div className="flex gap-1">
                      <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">Home</kbd>
                      <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">End</kbd>
                    </div>
                  </li>
                </ul>
              </section>

              {/* Selection Controls */}
              <section>
                <h3 className="mb-3 text-sm font-medium uppercase tracking-wider text-zinc-500">
                  选择与图表
                </h3>
                <ul className="space-y-2 text-sm">
                  <li className="flex items-center justify-between">
                    <span>框选范围</span>
                    <span className="text-zinc-400">在图表上点击并拖拽</span>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>扩大 / 缩小选区</span>
                    <div className="flex gap-1">
                      <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">[</kbd>
                      <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">]</kbd>
                    </div>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>清除选区</span>
                    <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">Esc</kbd>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>还原图表缩放</span>
                    <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">P</kbd>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>缩小图表</span>
                    <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">-</kbd>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>放大图表</span>
                    <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">=</kbd>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>删除选中范围</span>
                    <div className="flex gap-1">
                      <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">Del</kbd>
                      <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">Backspace</kbd>
                    </div>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>恢复选中范围</span>
                    <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">\</kbd>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>撤销选区修改</span>
                    <div className="flex gap-1">
                      <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">Ctrl/Cmd</kbd>
                      <span>+</span>
                      <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">Z</kbd>
                    </div>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>重做选区修改</span>
                    <div className="flex gap-1">
                      <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">Ctrl/Cmd</kbd>
                      <span>+</span>
                      <kbd className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 font-mono text-xs text-zinc-300">Y</kbd>
                    </div>
                  </li>
                </ul>
              </section>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
