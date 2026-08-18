import React, { useState } from 'react';
import { useTranslation } from '@/i18n';
import { discoverConnectorConsoles, launchDsh, launchKimiCodeWeb } from '@/services/api';
import { useResolvedTheme } from '@/lib/theme';

// consoleFirst=true 时 DrifterConsole 在左、Kimi Code Web 在右（手机版）；桌面默认 Kimi Code Web 在左
export const EnterButtons: React.FC<{ consoleFirst?: boolean }> = ({ consoleFirst = false }) => {
  const { t } = useTranslation();
  const [scanning, setScanning] = useState(false);
  const [kimiLaunching, setKimiLaunching] = useState(false);
  const [dshLaunching, setDshLaunching] = useState(false);
  // The fill + near-black text follow the ESP32 fill language in both themes;
  // only the hover fill is JS-side and branches on the resolved theme.
  const isLight = useResolvedTheme() === 'light';

  const enterDrifterConsole = async () => {
    if (scanning) return;
    setScanning(true);
    try {
      const result = await discoverConnectorConsoles();
      if (result.found && result.found.length > 0) {
        window.open(`http://${result.found[0].ip}/`, '_blank', 'noopener,noreferrer');
      } else {
        alert(t('common.enterButtons.consoleNotFound'));
      }
    } catch {
      alert(t('common.enterButtons.consoleNotFound'));
    } finally {
      setScanning(false);
    }
  };

  // 打开 Kimi Code Web：POST /api/launch/kimi-code-web（同源，后端转发到
  // launcher :8090），拿到 url 后填入预先打开的空白标签页
  const enterKimiCodeWeb = async () => {
    if (kimiLaunching) return;
    // 点击同步上下文先开空白页拿句柄：等异步拿到 URL 再 window.open
    // 会被浏览器弹窗拦截
    const win = window.open('about:blank', '_blank');
    setKimiLaunching(true);
    // kimi 冷启动可达数十秒，launcher 端整体超时 120s，客户端超时留足余量
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 125000);
    try {
      const data = await launchKimiCodeWeb(controller.signal);
      if (data.status === 'ok' && data.url) {
        if (win) {
          win.location.href = data.url;
        } else {
          window.open(data.url, '_blank', 'noopener,noreferrer');
        }
      } else {
        win?.close();
        alert(t('common.enterButtons.kimiCodeWebFailed', { message: data.error || t('common.unknownError') }));
      }
    } catch {
      win?.close();
      alert(t('common.enterButtons.kimiCodeWebFailed', { message: t('common.enterButtons.kimiCodeWebNetworkError') }));
    } finally {
      clearTimeout(timer);
      setKimiLaunching(false);
    }
  };

  // 打开 DeepSeek Harness：与 enterKimiCodeWeb 同款流程（空白页句柄 +
  // 后端转发 launcher），dsh 冷启动数秒、launcher 端整体超时 60s
  const enterDsh = async () => {
    if (dshLaunching) return;
    const win = window.open('about:blank', '_blank');
    setDshLaunching(true);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 65000);
    try {
      const data = await launchDsh(controller.signal);
      if (data.status === 'ok' && data.url) {
        if (win) {
          win.location.href = data.url;
        } else {
          window.open(data.url, '_blank', 'noopener,noreferrer');
        }
      } else {
        win?.close();
        alert(t('common.enterButtons.dshFailed', { message: data.error || t('common.unknownError') }));
      }
    } catch {
      win?.close();
      alert(t('common.enterButtons.dshFailed', { message: t('common.enterButtons.dshNetworkError') }));
    } finally {
      clearTimeout(timer);
      setDshLaunching(false);
    }
  };

  // h-[34px] 与 LanguageSwitcher 整体高度一致（内部键 24px + 外壳 p-1×2 + border×2）
  const cls = `flex items-center bg-[#5cc8ff] text-[#061019] border border-[#5cc8ff] font-extrabold text-[11px] px-2.5 h-[34px] rounded-full leading-none transition-colors ${isLight ? 'hover:bg-[#3eb6f0]' : 'hover:bg-[#8bdcff]'} cursor-pointer whitespace-nowrap`;

  const kimiButton = (
    <button type="button" onClick={enterKimiCodeWeb} disabled={kimiLaunching} title={t('common.enterButtons.kimiCodeWebTitle')} className={kimiLaunching ? `${cls} opacity-60 cursor-wait` : cls}>
      {kimiLaunching ? t('common.enterButtons.kimiCodeWebStarting') : t('common.enterButtons.kimiCodeWeb')}
    </button>
  );
  const dshButton = (
    <button type="button" onClick={enterDsh} disabled={dshLaunching} title={t('common.enterButtons.dshTitle')} className={dshLaunching ? `${cls} opacity-60 cursor-wait` : cls}>
      {dshLaunching ? t('common.enterButtons.dshStarting') : t('common.enterButtons.dsh')}
    </button>
  );
  const consoleButton = (
    <button type="button" onClick={enterDrifterConsole} disabled={scanning} title={t('common.enterButtons.drifterConsoleTitle')} className={scanning ? `${cls} opacity-60 cursor-wait` : cls}>
      {scanning ? t('common.enterButtons.scanning') : t('common.enterButtons.drifterConsole')}
    </button>
  );

  return (
    <div className="flex items-center gap-2">
      {consoleFirst ? (
        <>
          {consoleButton}
          {kimiButton}
          {dshButton}
        </>
      ) : (
        <>
          {kimiButton}
          {dshButton}
          {consoleButton}
        </>
      )}
    </div>
  );
};
