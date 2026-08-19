import React, { useCallback, useEffect, useState } from 'react';
import { Volume2, VolumeX } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { useConsoleDevice } from '../hooks/useConsoleDevice';
import { consoleGetJson, consolePostForm, consolePostText } from '../services/console';

// Drifter Console（ESP32）顶栏快捷控件：静音 / OTA / DEV。
// 复用 Issue #234 已有的 /api/console/proxy 同源代理与 services/console，
// 与内嵌 Drifter Console 页面共享同一车端数据源，实现两端状态同步。
// 样式沿用 DD 顶栏现有「静音式单按钮」圆形胶囊 + cyan 强调色。

const POLL_MS = 5000;

/** 静音按钮：位于 GitHub 图标右侧、主题切换左侧；每 5s 轮询以同步 DC 侧改动。 */
export const ConsoleMuteButton: React.FC = () => {
  const { t } = useTranslation();
  const { ip } = useConsoleDevice();
  const [muted, setMuted] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  const fetchMute = useCallback(async () => {
    if (!ip) return;
    try {
      const data = await consoleGetJson<{ muted?: number | boolean }>(ip, 'api/mute');
      setMuted(data.muted === 1 || data.muted === true);
    } catch {
      setMuted(null);
    }
  }, [ip]);

  useEffect(() => {
    fetchMute();
  }, [fetchMute]);

  useEffect(() => {
    if (!ip) return;
    const timer = window.setInterval(fetchMute, POLL_MS);
    return () => window.clearInterval(timer);
  }, [ip, fetchMute]);

  const toggle = async () => {
    if (!ip || muted === null || busy) return;
    setBusy(true);
    try {
      await consolePostForm(
        ip,
        'api/mute',
        new URLSearchParams({ muted: muted ? '0' : '1' }),
      );
      await fetchMute();
    } catch {
      setMuted(null);
    } finally {
      setBusy(false);
    }
  };

  const unreachable = !ip;
  const label = muted ? t('console.unmuteAria') : t('console.muteAria');
  return (
    <button
      type="button"
      onClick={toggle}
      disabled={unreachable || busy}
      aria-label={label}
      aria-pressed={muted === true}
      title={unreachable ? t('console.unreachable') : label}
      className={`console-mute-btn flex items-center justify-center w-8 h-8 rounded-full border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
        muted
          ? 'bg-[#5cc8ff]/10 border-[#5cc8ff]/60 text-[#5cc8ff]'
          : 'bg-zinc-800 border-zinc-700 text-zinc-300 hover:text-zinc-100'
      }`}
    >
      {muted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
    </button>
  );
};

/** OTA 按钮：打开车端 HTTP OTA 页面（新标签页）。 */
export const ConsoleOtaButton: React.FC = () => {
  const { t } = useTranslation();
  const { ip } = useConsoleDevice();
  const unreachable = !ip;
  const cls =
    'console-ota-btn inline-flex items-center justify-center h-8 px-3 rounded-full border text-xs font-semibold transition-colors';

  if (unreachable) {
    return (
      <button
        type="button"
        disabled
        title={t('console.unreachable')}
        className={`${cls} bg-zinc-800 border-zinc-700 text-zinc-500 cursor-not-allowed`}
      >
        OTA
      </button>
    );
  }

  return (
    <a
      href={`http://${ip}/update`}
      target="_blank"
      rel="noopener noreferrer"
      title={t('console.otaOpen')}
      className={`${cls} bg-zinc-800 border-zinc-700 text-zinc-300 hover:text-cyan-400 hover:border-cyan-500/50`}
    >
      OTA
    </a>
  );
};

/** DEV 开关：与 OTA 同款文字胶囊按钮，开启时 cyan 高亮；每 5s 轮询同步。 */
export const ConsoleDevToggle: React.FC = () => {
  const { t } = useTranslation();
  const { ip } = useConsoleDevice();
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  const fetchDevMode = useCallback(async () => {
    if (!ip) return;
    try {
      const data = await consoleGetJson<{ enabled?: boolean }>(ip, 'api/devmode');
      setEnabled(!!data.enabled);
    } catch {
      setEnabled(null);
    }
  }, [ip]);

  useEffect(() => {
    fetchDevMode();
  }, [fetchDevMode]);

  useEffect(() => {
    if (!ip) return;
    const timer = window.setInterval(fetchDevMode, POLL_MS);
    return () => window.clearInterval(timer);
  }, [ip, fetchDevMode]);

  const toggle = async () => {
    if (!ip || enabled === null || busy) return;
    setBusy(true);
    try {
      await consolePostText(
        ip,
        'api/devmode',
        enabled ? '0' : '1',
        'text/plain;charset=UTF-8',
      );
      await fetchDevMode();
    } catch {
      setEnabled(null);
    } finally {
      setBusy(false);
    }
  };

  const unreachable = !ip;
  const cls =
    'console-dev-toggle inline-flex items-center justify-center h-8 px-3 rounded-full border text-xs font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed';
  return (
    <button
      type="button"
      role="switch"
      aria-checked={!!enabled}
      aria-label={t('console.devModeTitle')}
      disabled={unreachable || busy}
      onClick={toggle}
      title={unreachable ? t('console.unreachable') : t('console.devModeTitle')}
      className={`${cls} ${
        enabled
          ? 'bg-cyan-500/25 border-cyan-500/60 text-cyan-400'
          : 'bg-zinc-800 border-zinc-700 text-zinc-300 hover:text-cyan-400 hover:border-cyan-500/50'
      }`}
    >
      DEV
    </button>
  );
};
