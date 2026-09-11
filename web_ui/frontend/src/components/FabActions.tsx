import React, { useEffect, useState } from 'react';
import { useTranslation } from '@/i18n';

// FAB cluster mirrored 1:1 from the ESP32 Drifter Console
// (Firmware/MUS4_FW/libraries/mus4_web/src/WebConsoleAssets.h):
// .fabToggle (accent dot) + .fabActions (.helpFab) + .helpModal.
// Only the help modal's shortcut list content differs (DonkeyDrifter shortcuts).
// 语言入口不在此处：顶栏 LanguageSwitcher 为静音式单按钮（issue #139）。
// 颜色全部走标准 Tailwind 工具类，由 themes/*.css 皮肤按语义变量重映射——
// Apple 象限无投影无 glow（--shadow-lg/xl = none），座舱保持原观感。
export const FabActions: React.FC = () => {
  const { t } = useTranslation();
  const [fabOpen, setFabOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  // ESP: document.addEventListener('click', collapseFabActions) — any outside
  // click collapses the FAB cluster. Inner buttons stopPropagation so they
  // don't immediately retrigger this.
  useEffect(() => {
    const collapse = () => {
      setFabOpen(false);
    };
    document.addEventListener('click', collapse);
    return () => document.removeEventListener('click', collapse);
  }, []);

  const toggleFab = (e: React.MouseEvent) => {
    e.stopPropagation();
    setFabOpen((v) => !v);
  };

  const openHelp = (e: React.MouseEvent) => {
    e.stopPropagation();
    setFabOpen(true);
    setHelpOpen(true);
  };

  const fabBallBase =
    'absolute bottom-0 right-0 flex h-[46px] w-[46px] min-w-0 items-center justify-center rounded-full border p-0 font-black leading-none shadow-lg backdrop-blur-[4px] transition-[opacity,transform] duration-[180ms]';
  const fabBallVisibility = fabOpen
    ? 'pointer-events-auto scale-100 opacity-100'
    : 'pointer-events-none scale-[0.55] opacity-0';

  // ESP32 fill 语言：accent 填充 + on-accent 文字（皮肤规则 .bg-cyan-500.text-white）
  const fabToggleColors =
    'border-cyan-500 bg-cyan-500 hover:bg-cyan-700 focus-visible:bg-cyan-700';
  const helpFabColors =
    'border-cyan-500/60 bg-cyan-500 text-white hover:border-cyan-500 hover:bg-cyan-700 focus-visible:border-cyan-500 focus-visible:bg-cyan-700';
  const helpModalColors = 'border-cyan-500/50 bg-zinc-900 shadow-xl';
  const helpCloseColors = 'text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100';
  const helpBodyText = 'text-zinc-200';
  const sectionHeadText = 'text-zinc-400';
  const kbdColors = 'border-zinc-700 bg-zinc-800 text-zinc-200';

  return (
    <>
      {/* .fabToggle: accent dot that expands/collapses the cluster */}
      <button
        type="button"
        onClick={toggleFab}
        aria-label={t('fab.quickActions')}
        className={`fixed bottom-[24px] right-[24px] z-50 h-[18px] w-[18px] min-w-0 rounded-full border ${fabToggleColors} p-0 hover:scale-[1.18] focus-visible:scale-[1.18] active:scale-[1.18]`}
      />

      {/* .fabActions: anchor point; ball flies out left (help) */}
      <div className="pointer-events-none fixed bottom-[18px] right-[18px] z-50">
        {/* .helpFab */}
        <button
          type="button"
          onClick={openHelp}
          aria-label={t('fab.help')}
          className={`${fabBallBase} ${helpFabColors} text-[24px] ${fabBallVisibility} ${fabOpen ? '-translate-x-[56px]' : ''}`}
        >
          ?
        </button>
      </div>

      {/* Help modal chrome: mirrors ESP32 .helpOverlay/.helpModal 1:1; only the shortcut list content differs */}
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
