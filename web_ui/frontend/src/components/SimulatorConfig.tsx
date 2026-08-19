import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader } from './ui/Card';
import { SectionCardTitle } from './ui/SectionCardTitle';
import { Button } from './ui/Button';
import { Input } from './ui/Input';
import { useStore } from '../store/useStore';
import {
  discoverSimulator,
  saveSimulatorConfig,
  getApiErrorMessage,
  type SimulatorHost,
} from '../services/api';
import { useTranslation } from '@/i18n';
import {
  Gamepad2,
  Search,
  Save,
  Wifi,
  WifiOff,
  Loader2,
  CheckCircle2,
  X,
  AlertCircle,
  Info,
} from 'lucide-react';

type ToastType = 'success' | 'error' | 'info';

interface ToastItem {
  id: number;
  message: string;
  type: ToastType;
}

export const SimulatorConfig: React.FC = () => {
  const { t } = useTranslation();
  const { config, configPath, setLoading, isLoading } = useStore();

  const [simHost, setSimHost] = useState('');
  const [donkeyGym, setDonkeyGym] = useState(false);
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [foundHosts, setFoundHosts] = useState<SimulatorHost[]>([]);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  // Sync with loaded config
  useEffect(() => {
    if (config) {
      const host = config.SIM_HOST;
      if (typeof host === 'string') {
        setSimHost(host);
      }
      const gym = config.DONKEY_GYM;
      if (typeof gym === 'boolean') {
        setDonkeyGym(gym);
      }
    }
  }, [config]);

  const pushToast = useCallback((message: string, type: ToastType = 'info') => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((toast) => toast.id !== id));
    }, 5000);
  }, []);

  const handleDiscover = useCallback(async () => {
    setIsDiscovering(true);
    setFoundHosts([]);
    setSaveSuccess(false);
    pushToast(t('tub.scanningToast'), 'info');
    try {
      const data = await discoverSimulator(configPath || undefined);
      if (data.found && data.found.length > 0) {
        setFoundHosts(data.found);
        const best = data.found[0];
        setSimHost(best.ip);
        pushToast(
          t('tub.foundToast', { count: data.found.length, scanned: data.scanned, ip: best.ip }),
          'success'
        );
      } else {
        pushToast(
          `${data.message}`,
          'error'
        );
      }
    } catch (err: unknown) {
      const msg = getApiErrorMessage(err, t('tub.discoverFailed'));
      pushToast(msg, 'error');
    } finally {
      setIsDiscovering(false);
    }
  }, [configPath, pushToast, t]);

  const handleSelectHost = (host: SimulatorHost) => {
    setSimHost(host.ip);
    setSaveSuccess(false);
    pushToast(t('tub.selectHostToast', { ip: host.ip }), 'info');
  };

  const handleSave = useCallback(async () => {
    if (!configPath) {
      pushToast(t('tub.loadConfigDirFirstToast'), 'error');
      return;
    }
    setLoading(true);
    setSaveSuccess(false);
    try {
      await saveSimulatorConfig({
        path: configPath,
        config: {
          SIM_HOST: simHost,
          DONKEY_GYM: donkeyGym,
        },
      });
      setSaveSuccess(true);
      pushToast(t('tub.savedToast'), 'success');
      if (config) {
        useStore.setState({
          config: { ...config, SIM_HOST: simHost, DONKEY_GYM: donkeyGym },
        });
      }
    } catch (err: unknown) {
      const msg = getApiErrorMessage(err, t('tub.saveFailed'));
      pushToast(msg, 'error');
    } finally {
      setLoading(false);
    }
  }, [configPath, simHost, donkeyGym, config, pushToast, setLoading, t]);

  const toastIcon = (type: ToastType) => {
    switch (type) {
      case 'success':
        return <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />;
      case 'error':
        return <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />;
      default:
        return <Info className="w-4 h-4 text-cyan-400 shrink-0" />;
    }
  };

  const toastBg = (type: ToastType) => {
    switch (type) {
      case 'success':
        return 'bg-emerald-950/90 border-emerald-700/50';
      case 'error':
        return 'bg-red-950/90 border-red-700/50';
      default:
        return 'bg-zinc-900/90 border-zinc-700/50';
    }
  };

  return (
    <Card>
      <CardHeader>
        <SectionCardTitle
          icon={<Gamepad2 className="w-5 h-5" />}
          title={t('tub.simTitle')}
          subtitle={t('tub.simHoverSubtitle')}
        />
        <p className="text-sm text-zinc-400">{t('tub.simSubtitle')}</p>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-4">
          {/* SIM_HOST input */}
          <div className="space-y-1">
            <label className="text-sm text-zinc-300 font-medium">{t('tub.simHostLabel')}</label>
            <Input
              placeholder={t('tub.simHostPlaceholder')}
              value={simHost}
              onChange={(e) => {
                setSimHost(e.target.value);
                setSaveSuccess(false);
              }}
              aria-label={t('tub.simHostAria')}
            />
          </div>

          {/* DONKEY_GYM toggle */}
          <div className="flex items-center justify-between">
            <label className="text-sm text-zinc-300 font-medium">{t('tub.simModeLabel')}</label>
            <button
              onClick={() => {
                setDonkeyGym((v) => !v);
                setSaveSuccess(false);
              }}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                donkeyGym ? 'bg-cyan-600' : 'bg-zinc-700'
              }`}
              aria-label={t('tub.simModeAria')}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  donkeyGym ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          {/* Discovery button */}
          <Button
            variant="secondary"
            onClick={handleDiscover}
            disabled={isDiscovering}
            className="w-full"
            aria-label={t('tub.discoverAria')}
          >
            {isDiscovering ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Search className="w-4 h-4" />
            )}
            {isDiscovering ? t('tub.scanning') : t('tub.discover')}
          </Button>

          {/* Found hosts list */}
          {foundHosts.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs text-zinc-400">{t('tub.foundHosts')}</p>
              <div className="max-h-40 overflow-y-auto space-y-1.5">
                {foundHosts.map((host) => (
                  <button
                    key={`${host.ip}:${host.port}`}
                    onClick={() => handleSelectHost(host)}
                    className={`w-full flex items-center justify-between rounded-md border px-3 py-2 text-left transition-colors ${
                      simHost === host.ip
                        ? 'border-cyan-500/50 bg-cyan-950/30'
                        : 'border-zinc-800 bg-zinc-800/50 hover:bg-zinc-800'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <Wifi className="w-4 h-4 text-emerald-400" />
                      <span className="text-sm text-zinc-100 font-mono">
                        {host.ip}:{host.port}
                      </span>
                    </div>
                    <span className="text-xs text-zinc-400">
                      {host.latency_ms}ms
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* No hosts hint */}
          {!isDiscovering && foundHosts.length === 0 && (
            <div className="flex items-center gap-2 text-xs text-zinc-500">
              <WifiOff className="w-3.5 h-3.5" />
              <span>{t('tub.scanHint')}</span>
            </div>
          )}

          {/* Save button */}
          <Button
            onClick={handleSave}
            disabled={isLoading || !configPath}
            className="w-full"
            aria-label={t('tub.saveAria')}
          >
            {saveSuccess ? (
              <CheckCircle2 className="w-4 h-4" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            {saveSuccess ? t('tub.saved') : t('tub.saveConfig')}
          </Button>
        </div>
      </CardContent>

      {/* Toast overlay */}
      <div className="fixed bottom-6 right-6 z-[100] flex flex-col gap-2 pointer-events-none">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`pointer-events-auto flex items-start gap-2 rounded-lg border px-4 py-3 shadow-lg backdrop-blur-sm text-sm text-zinc-100 max-w-sm animate-in fade-in slide-in-from-right-4 duration-300 ${toastBg(toast.type)}`}
          >
            {toastIcon(toast.type)}
            <span className="flex-1 leading-relaxed">{toast.message}</span>
            <button
              onClick={() => setToasts((prev) => prev.filter((x) => x.id !== toast.id))}
              aria-label={t('common.close')}
              className="shrink-0 text-zinc-400 hover:text-white transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
    </Card>
  );
};
