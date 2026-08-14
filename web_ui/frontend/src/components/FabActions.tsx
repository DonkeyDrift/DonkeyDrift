import React, { useEffect, useState } from 'react';
import { useTranslation, type UiLanguage } from '@/i18n';
import { useResolvedTheme } from '@/lib/theme';

// FAB cluster mirrored 1:1 from the ESP32 Drifter Console
// (Firmware/MUS4_FW/libraries/mus4_web/src/WebConsoleAssets.h):
// .fabToggle (glowing dot) + .fabActions (.langFab/.helpFab) + .langMenu + .helpModal.
// Only the help modal's shortcut list content differs (DonkeyDrifter shortcuts).
const LANG_SEGMENTS: ReadonlyArray<{ value: UiLanguage; label: string }> = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
];

export const FabActions: React.FC = () => {
  const { lang, setLanguage, t } = useTranslation();
  const [fabOpen, setFabOpen] = useState(false);
  const [langMenuOpen, setLangMenuOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  // ESP: document.addEventListener('click', collapseFabActions) — any outside
  // click collapses the FAB cluster and closes the language menu. Inner buttons
  // stopPropagation so they don't immediately retrigger this.
  useEffect(() => {
    const collapse = () => {
      setFabOpen(false);
      setLangMenuOpen(false);
    };
    document.addEventListener('click', collapse);
    return () => document.removeEventListener('click', collapse);
  }, []);

  const toggleFab = (e: React.MouseEvent) => {
    e.stopPropagation();
    setFabOpen((v) => !v);
  };

  const toggleLangMenu = (e: React.MouseEvent) => {
    e.stopPropagation();
    setFabOpen(true);
    setLangMenuOpen((v) => !v);
  };

  const openHelp = (e: React.MouseEvent) => {
    e.stopPropagation();
    setFabOpen(true);
    setLangMenuOpen(false);
    setHelpOpen(true);
  };

  const chooseLanguage = (value: UiLanguage) => {
    setLanguage(value);
    setLangMenuOpen(false);
  };

  // Skin CSS (themes/theme-light.css) only remaps standard Tailwind utilities;
  // the arbitrary-value colors below are JS-side and must branch on the
  // resolved theme. The dark branch keeps the current ESP32 palette verbatim.
  const isLight = useResolvedTheme() === 'light';

  const fabBallBase =
    `absolute bottom-0 right-0 flex h-[46px] w-[46px] min-w-0 items-center justify-center rounded-full border p-0 font-black leading-none ${
      isLight
        ? 'shadow-[0_8px_22px_rgba(15,23,42,0.14)]'
        : 'shadow-[0_8px_22px_rgba(0,0,0,0.22)]'
    } backdrop-blur-[4px] transition-[opacity,transform] duration-[180ms]`;
  const fabBallVisibility = fabOpen
    ? 'pointer-events-auto scale-100 opacity-100'
    : 'pointer-events-none scale-[0.55] opacity-0';

  const fabToggleColors = isLight
    ? 'border-[#5cc8ff] bg-[#5cc8ff] shadow-[0_0_18px_rgba(2,128,189,0.45),0_0_36px_rgba(2,128,189,0.3)] hover:shadow-[0_0_22px_rgba(2,128,189,0.5),0_0_44px_rgba(2,128,189,0.4)] focus-visible:shadow-[0_0_22px_rgba(2,128,189,0.5),0_0_44px_rgba(2,128,189,0.4)]'
    : 'border-[#8bdcff] bg-[#8bdcff] shadow-[0_0_18px_#5cc8ff,0_0_36px_rgba(92,200,255,0.55)] hover:shadow-[0_0_22px_#8bdcff,0_0_44px_rgba(92,200,255,0.72)] focus-visible:shadow-[0_0_22px_#8bdcff,0_0_44px_rgba(92,200,255,0.72)]';
  const langFabColors = isLight
    ? 'border-[#5cc8ff] bg-[#0280bd] hover:border-[#5cc8ff] hover:bg-[#026a9e] hover:shadow-[0_12px_32px_rgba(15,23,42,0.18)] focus-visible:border-[#5cc8ff] focus-visible:bg-[#026a9e]'
    : 'border-[rgba(92,200,255,0.68)] bg-[rgba(37,99,235,0.58)] hover:border-[#5cc8ff] hover:bg-[#3b82f6] hover:shadow-[0_12px_32px_rgba(0,0,0,0.35)] focus-visible:border-[#5cc8ff] focus-visible:bg-[#3b82f6]';
  const helpFabColors = isLight
    ? 'border-[#5cc8ff] bg-[#5cc8ff] hover:border-[#3eb6f0] hover:bg-[#3eb6f0] hover:shadow-[0_12px_32px_rgba(15,23,42,0.18)] focus-visible:border-[#3eb6f0] focus-visible:bg-[#3eb6f0]'
    : 'border-[rgba(92,200,255,0.72)] bg-[rgba(92,200,255,0.62)] hover:border-[#8bdcff] hover:bg-[#8bdcff] hover:shadow-[0_12px_32px_rgba(0,0,0,0.35)] focus-visible:border-[#8bdcff] focus-visible:bg-[#8bdcff]';
  const langMenuColors = isLight
    ? 'border-[#0280bd] bg-[#edf1f6] shadow-[0_12px_32px_rgba(15,23,42,0.18)]'
    : 'border-[#5cc8ff] bg-[#111820] shadow-[0_12px_32px_rgba(0,0,0,0.35)]';
  const langItemIdleColors = isLight
    ? 'font-bold text-[#1c2733] hover:bg-[#dfe6ef]'
    : 'font-bold text-[#dbeafe] hover:bg-[#222b36]';
  const helpModalColors = isLight
    ? 'border-[#0280bd] bg-[linear-gradient(135deg,#ffffff,#edf1f6)] shadow-[0_18px_60px_rgba(15,23,42,0.24)]'
    : 'border-[#5cc8ff] bg-[linear-gradient(135deg,#1c2430,#121821)] shadow-[0_18px_60px_rgba(0,0,0,0.45)]';
  const helpCloseColors = isLight
    ? 'text-[#5f7185] hover:bg-[#e2e9f1] hover:text-[#1c2733]'
    : 'text-[#a1a1aa] hover:bg-[#27272a] hover:text-[#f4f4f5]';
  const helpBodyText = isLight ? 'text-[#1c2733]' : 'text-[#dbeafe]';
  const sectionHeadText = isLight ? 'text-[#5f7185]' : 'text-[#8fa1b5]';
  const kbdColors = isLight
    ? 'border-[#d9e1ea] bg-[#fbfcfe] text-[#1c2733]'
    : 'border-[#2b3441] bg-[#171c24] text-[#dbeafe]';

  return (
    <>
      {/* .fabToggle: glowing cyan dot that expands/collapses the cluster */}
      <button
        type="button"
        onClick={toggleFab}
        aria-label={t('fab.quickActions')}
        className={`fixed bottom-[24px] right-[24px] z-50 h-[18px] w-[18px] min-w-0 rounded-full border ${fabToggleColors} p-0 hover:scale-[1.18] focus-visible:scale-[1.18] active:scale-[1.18]`}
      />

      {/* .fabActions: anchor point; balls fly out up (lang) and left (help) */}
      <div className="pointer-events-none fixed bottom-[18px] right-[18px] z-50">
        {/* .langFab */}
        <button
          type="button"
          onClick={toggleLangMenu}
          aria-label={t('fab.language')}
          className={`${fabBallBase} ${langFabColors} text-[23px] text-[#eef] ${fabBallVisibility} ${fabOpen ? '-translate-y-[56px]' : ''}`}
        >
          🌐
        </button>
        {/* .helpFab */}
        <button
          type="button"
          onClick={openHelp}
          aria-label={t('fab.help')}
          className={`${fabBallBase} ${helpFabColors} text-[24px] text-[#061019] ${fabBallVisibility} ${fabOpen ? '-translate-x-[56px]' : ''}`}
        >
          ?
        </button>
      </div>

      {/* .langMenu */}
      {langMenuOpen && (
        <div className={`fixed bottom-[74px] right-[72px] z-50 min-w-[132px] rounded-[12px] border ${langMenuColors} p-[6px]`}>
          {LANG_SEGMENTS.map(({ value, label }) => {
            const active = value === lang;
            return (
              <button
                key={value}
                type="button"
                data-lang={value}
                onClick={() => chooseLanguage(value)}
                className={`my-[2px] block w-full min-w-0 rounded-[8px] px-[10px] py-[7px] text-left text-[13px] ${
                  active
                    ? 'bg-[#5cc8ff] font-extrabold text-[#061019]'
                    : langItemIdleColors
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>
      )}

      {/* Help modal chrome: mirrors ESP32 .helpOverlay/.helpModal 1:1; only the shortcut list content differs */}
      {helpOpen && (
        <>
          {/* .helpOverlay */}
          <div
            className={`fixed inset-0 z-[100] ${isLight ? 'bg-[rgba(15,23,42,0.35)]' : 'bg-[rgba(5,7,10,0.45)]'}`}
            onClick={() => setHelpOpen(false)}
          />
          {/* .helpModal: anchored bottom-right above the FAB cluster */}
          <div className={`fixed bottom-[74px] right-[18px] z-[101] max-h-[calc(100vh-100px)] w-[min(340px,calc(100vw-36px))] overflow-y-auto rounded-[14px] border ${helpModalColors} p-[14px]`}>
            {/* .helpHead */}
            <div className="mb-2 flex items-center justify-between gap-3">
              <h2 className={`m-0 text-base font-bold ${isLight ? 'text-[#1c2733]' : 'text-[#e8edf2]'}`}>{t('fab.helpTitle')}</h2>
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
