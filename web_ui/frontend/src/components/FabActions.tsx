import React, { useEffect, useState } from 'react';
import { useTranslation } from '@/i18n';

// 单动作帮助 FAB：右下常驻 46px 圆形「?」按钮，点击直接打开快捷键说明弹窗。
// 注意：这是用户要求的刻意分歧——不再 1:1 镜像 ESP32 Drifter Console 的两级
// 展开 FAB 群（.fabToggle 小圆点 + 飞出 ? 球 + 任意点击收起），只保留帮助弹窗
// 本体（快捷键列表内容与固件侧一致）。
// 语言入口不在此处：顶栏 LanguageSwitcher 为静音式单按钮（issue #139）。
// 颜色全部走标准 Tailwind 工具类，由 themes/*.css 皮肤按语义变量重映射——
// Apple 象限无投影无 glow（--shadow-lg/xl = none），座舱保持原观感。
export const FabActions: React.FC = () => {
  const { t } = useTranslation();
  const [helpOpen, setHelpOpen] = useState(false);

  // Esc 关闭帮助弹窗（遮罩点击关闭在下方 overlay 上）
  useEffect(() => {
    if (!helpOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setHelpOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [helpOpen]);

  // ESP32 fill 语言：accent 填充 + on-accent 文字（皮肤规则 .bg-cyan-500.text-white）
  const helpFabColors =
    'border-cyan-500/60 bg-cyan-500 text-white hover:border-cyan-500 hover:bg-cyan-700 focus-visible:border-cyan-500 focus-visible:bg-cyan-700';
  const helpModalColors = 'border-cyan-500/50 bg-zinc-900 shadow-xl';
  const helpCloseColors = 'text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100';
  const helpBodyText = 'text-zinc-200';
  const sectionHeadText = 'text-zinc-400';
  const kbdColors = 'border-zinc-700 bg-zinc-800 text-zinc-200';

  return (
    <>
      {/* 右下常驻帮助按钮：点击直达快捷键说明弹窗 */}
      <button
        type="button"
        onClick={() => setHelpOpen(true)}
        aria-label={t('fab.help')}
        className={`dd-fab fixed bottom-[18px] right-[18px] z-50 flex h-[46px] w-[46px] min-w-0 items-center justify-center rounded-full border p-0 text-[24px] font-black leading-none shadow-lg transition-colors ${helpFabColors}`}
      >
        ?
      </button>

      {/* Help modal chrome: 与 ESP32 .helpOverlay/.helpModal 同款；快捷键列表内容为 DonkeyDrifter 特有 */}
      {helpOpen && (
        <>
          {/* .helpOverlay */}
          <div
            className="fixed inset-0 z-[100] bg-black/60"
            onClick={() => setHelpOpen(false)}
          />
          {/* .helpModal: anchored bottom-right above the FAB cluster */}
          <div className={`fixed bottom-[74px] right-[18px] z-[101] max-h-[calc(100vh-100px)] w-[min(340px,calc(100vw-36px))] overflow-y-auto rounded-xl border ${helpModalColors} p-[14px]`}>
            {/* .helpHead */}
            <div className="mb-2 flex items-center justify-between gap-3">
              <h2 className="m-0 text-base font-bold text-zinc-100">{t('fab.helpTitle')}</h2>
              {/* .helpClose */}
              <button
                type="button"
                onClick={() => setHelpOpen(false)}
                className={`flex h-[28px] w-[28px] min-w-0 items-center justify-center rounded-full border-none bg-transparent p-0 text-[20px] leading-none ${helpCloseColors}`}
                aria-label={t('fab.closeHelp')}
              >
                ×
              </button>
            </div>

            {/* Shortcut list: DonkeyDrifter-specific content (the intentional difference) */}
            <div className={`space-y-4 text-[13px] leading-[1.55] ${helpBodyText}`}>
              {/* Playback Controls */}
              <section>
                <h3 className={`mb-2 text-xs font-medium uppercase tracking-wider ${sectionHeadText}`}>
                  {t('fab.section.playback')}
                </h3>
                <ul className="space-y-2">
                  <li className="flex items-center justify-between">
                    <span>{t('fab.playPause')}</span>
                    <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>Space</kbd>
                  </li>
                </ul>
              </section>

              {/* Navigation */}
              <section>
                <h3 className={`mb-2 text-xs font-medium uppercase tracking-wider ${sectionHeadText}`}>
                  {t('fab.section.navigation')}
                </h3>
                <ul className="space-y-2">
                  <li className="flex items-center justify-between">
                    <span>{t('fab.prevNextFrame')}</span>
                    <div className="flex gap-1">
                      <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>←</kbd>
                      <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>→</kbd>
                    </div>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>{t('fab.jumpFirstLast')}</span>
                    <div className="flex gap-1">
                      <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>Home</kbd>
                      <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>End</kbd>
                    </div>
                  </li>
                </ul>
              </section>

              {/* Selection Controls */}
              <section>
                <h3 className={`mb-2 text-xs font-medium uppercase tracking-wider ${sectionHeadText}`}>
                  {t('fab.section.selection')}
                </h3>
                <ul className="space-y-2">
                  <li className="flex items-center justify-between">
                    <span>{t('fab.boxSelect')}</span>
                    <span className={sectionHeadText}>{t('fab.boxSelectHint')}</span>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>{t('fab.growShrinkSelection')}</span>
                    <div className="flex gap-1">
                      <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>[</kbd>
                      <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>]</kbd>
                    </div>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>{t('fab.clearSelection')}</span>
                    <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>Esc</kbd>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>{t('fab.resetZoom')}</span>
                    <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>P</kbd>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>{t('fab.zoomOut')}</span>
                    <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>-</kbd>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>{t('fab.zoomIn')}</span>
                    <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>=</kbd>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>{t('fab.deleteRange')}</span>
                    <div className="flex gap-1">
                      <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>Del</kbd>
                      <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>Backspace</kbd>
                    </div>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>{t('fab.restoreRange')}</span>
                    <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>\</kbd>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>{t('fab.undo')}</span>
                    <div className="flex gap-1">
                      <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>Ctrl/Cmd</kbd>
                      <span>+</span>
                      <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>Z</kbd>
                    </div>
                  </li>
                  <li className="flex items-center justify-between">
                    <span>{t('fab.redo')}</span>
                    <div className="flex gap-1">
                      <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>Ctrl/Cmd</kbd>
                      <span>+</span>
                      <kbd className={`rounded border ${kbdColors} px-2 py-1 font-mono text-xs`}>Y</kbd>
                    </div>
                  </li>
                </ul>
              </section>
            </div>
          </div>
        </>
      )}
    </>
  );
};
