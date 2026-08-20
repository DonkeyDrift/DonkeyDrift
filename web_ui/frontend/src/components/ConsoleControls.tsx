import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Volume2, VolumeX, X } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { useConsoleDevice } from '../hooks/useConsoleDevice';
import { consoleGetJson, consolePostForm, consolePostText } from '../services/console';
import { Button } from './ui/Button';

// Drifter Console（ESP32）顶栏快捷控件：静音 / OTA / DEV。
// 复用 Issue #234 已有的 /api/console/proxy 同源代理与 services/console，
// 与内嵌 Drifter Console 页面共享同一车端数据源，实现两端状态同步。
// 样式沿用 DD 顶栏现有「静音式单按钮」圆形胶囊 + cyan 强调色。

const POLL_MS = 5000;

// DEV 开关成功切换后广播该事件，内嵌 Drifter Console 页面监听后重载 iframe，
// 让车端原版页面立刻反映最新 dev_mode，不必等 DC 自己的 5s 轮询或手动刷新。
export const DEV_MODE_CHANGED_EVENT = 'dd-console-devmode-changed';

// 静音成功切换后广播该事件，内嵌 Drifter Console 页面监听后直接 postMessage 到 DC，
// 让车端原版页面立刻更新静音图标，不重载 iframe（静音是高频轻量操作，重载会丢曲线/终端状态）。
export const MUTE_CHANGED_EVENT = 'dd-console-mute-changed';

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
    const next = muted ? 0 : 1;
    setBusy(true);
    try {
      await consolePostForm(
        ip,
        'api/mute',
        new URLSearchParams({ muted: String(next) }),
      );
      await fetchMute();
      window.dispatchEvent(
        new CustomEvent(MUTE_CHANGED_EVENT, { detail: { muted: next === 1 } }),
      );
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

/** OTA 按钮：在当前页面弹出上传框，经同源代理 POST /update 上传固件（不再跳转新页）。 */
export const ConsoleOtaButton: React.FC = () => {
  const { t } = useTranslation();
  const { ip } = useConsoleDevice();
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState<{ kind: 'idle' | 'error' | 'success'; text: string }>({
    kind: 'idle',
    text: '',
  });
  const fileRef = useRef<HTMLInputElement>(null);

  const unreachable = !ip;
  const cls =
    'console-ota-btn inline-flex items-center justify-center h-8 px-3 rounded-full border text-xs font-semibold transition-colors';

  const close = useCallback(() => {
    if (uploading) return;
    setOpen(false);
    setFile(null);
    setStatus({ kind: 'idle', text: '' });
  }, [uploading]);

  const upload = async () => {
    if (!ip || !file) {
      setStatus({ kind: 'error', text: t('console.otaNoFile') });
      return;
    }
    setUploading(true);
    setStatus({ kind: 'idle', text: '' });
    try {
      const form = new FormData();
      form.append('update', file);
      await consolePostForm(ip, 'update', form);
      setStatus({ kind: 'success', text: t('console.otaSuccess') });
    } catch (err) {
      setStatus({
        kind: 'error',
        text: t('console.otaFailed', {
          message: err instanceof Error ? err.message : String(err),
        }),
      });
    } finally {
      setUploading(false);
    }
  };

  return (
    <>
      <button
        type="button"
        disabled={unreachable}
        onClick={() => setOpen(true)}
        title={unreachable ? t('console.unreachable') : t('console.otaOpen')}
        className={`${cls} ${
          unreachable
            ? 'bg-zinc-800 border-zinc-700 text-zinc-500 cursor-not-allowed'
            : 'bg-zinc-800 border-zinc-700 text-zinc-300 hover:text-cyan-400 hover:border-cyan-500/50'
        }`}
      >
        OTA
      </button>

      {open && ip && (
        <div className="fixed inset-0 bg-black/60 z-[100] flex items-center justify-center p-4">
          <div className="bg-zinc-900 border border-zinc-800 rounded-lg shadow-xl w-full max-w-md flex flex-col overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-zinc-800 bg-zinc-900/50">
              <h2 className="text-base font-semibold text-zinc-100">{t('console.otaTitle')}</h2>
              <button
                type="button"
                onClick={close}
                disabled={uploading}
                aria-label={t('common.close')}
                className="p-1 hover:bg-zinc-800 rounded text-zinc-400 hover:text-zinc-100 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4 space-y-4">
              <input
                ref={fileRef}
                type="file"
                accept=".bin"
                aria-label={t('console.otaChooseFile')}
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null);
                  setStatus({ kind: 'idle', text: '' });
                }}
                className="block w-full text-sm text-zinc-300 file:mr-3 file:rounded file:border-0 file:bg-zinc-800 file:px-3 file:py-2 file:text-sm file:text-zinc-200 hover:file:bg-zinc-700"
              />
              {status.kind !== 'idle' && (
                <p
                  className={`text-sm ${
                    status.kind === 'success' ? 'text-emerald-400' : 'text-red-400'
                  }`}
                >
                  {status.text}
                </p>
              )}
            </div>
            <div className="p-4 border-t border-zinc-800 bg-zinc-900/50 flex justify-end gap-3">
              <Button variant="secondary" onClick={close} disabled={uploading}>
                {t('console.cancel')}
              </Button>
              <Button onClick={upload} disabled={uploading || !file}>
                {uploading ? t('console.otaUploading') : t('console.otaUpload')}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

/** DEV 开关：与 OTA 同款文字胶囊按钮，开启时 cyan 高亮；每 5s 轮询同步。
 *  开启（当前为关）时先弹「开启开发模式」确认框，关闭则直接生效（对齐 DC 行为）。 */
export const ConsoleDevToggle: React.FC = () => {
  const { t } = useTranslation();
  const { ip } = useConsoleDevice();
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

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

  const applyToggle = async (value: '0' | '1') => {
    if (!ip || busy) return;
    setBusy(true);
    try {
      await consolePostText(ip, 'api/devmode', value, 'text/plain;charset=UTF-8');
      await fetchDevMode();
      window.dispatchEvent(new Event(DEV_MODE_CHANGED_EVENT));
    } catch {
      setEnabled(null);
    } finally {
      setBusy(false);
    }
  };

  const toggle = () => {
    if (!ip || enabled === null || busy) return;
    if (enabled) {
      void applyToggle('0');
    } else {
      setConfirmOpen(true);
    }
  };

  const confirm = () => {
    setConfirmOpen(false);
    void applyToggle('1');
  };

  const unreachable = !ip;
  const cls =
    'console-dev-toggle inline-flex items-center justify-center h-8 px-3 rounded-full border text-xs font-semibold transition-colors disabled:opacity-50 disabled:cursor-not-allowed';
  return (
    <>
      <span className="relative group inline-flex">
        <button
          type="button"
          role="switch"
          aria-checked={!!enabled}
          aria-label={t('console.devModeTitle')}
          disabled={unreachable || busy}
          onClick={toggle}
          title={unreachable ? t('console.unreachable') : undefined}
          className={`${cls} ${
            enabled
              ? 'bg-[#5cc8ff]/25 border-[#5cc8ff] text-[#5cc8ff] shadow-[inset_0_0_0_1px_#5cc8ff]'
              : 'bg-zinc-800 border-zinc-700 text-zinc-300 hover:text-cyan-400 hover:border-cyan-500/50'
          }`}
        >
          DEV
        </button>
        {!unreachable && (
          <span className="pointer-events-none absolute right-0 top-full mt-2 w-72 rounded-lg border border-[#5cc8ff] bg-[#111820] px-2.5 py-2 text-xs font-semibold leading-relaxed text-[#dbeafe] opacity-0 transition-opacity group-hover:opacity-100 z-50">
            {t('console.devHint')}
          </span>
        )}
      </span>

      {confirmOpen && (
        <div className="fixed inset-0 bg-black/60 z-[100] flex items-center justify-center p-4">
          <div className="bg-zinc-900 border border-zinc-800 rounded-lg shadow-xl w-full max-w-md flex flex-col overflow-hidden">
            <div className="p-4 border-b border-zinc-800 bg-zinc-900/50">
              <h2 className="text-base font-semibold text-zinc-100">{t('console.devTitle')}</h2>
            </div>
            <div className="p-4 text-sm text-zinc-300 leading-relaxed">{t('console.devBody')}</div>
            <div className="p-4 border-t border-zinc-800 bg-zinc-900/50 flex justify-end gap-3">
              <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
                {t('console.cancel')}
              </Button>
              <Button onClick={confirm}>{t('console.devConfirm')}</Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
