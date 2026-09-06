import React, { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { discoverConnectorConsoles, getConnectorLocalIps } from '@/services/api';

/**
 * 「找小车」弹窗（局域网直连发现，无 token、无云端）：
 * 打开时并行调用后端两个既有端点——`/connector/local_ips`（本机 DD 的局域网 IPv4）
 * 与 `/connector/discover_console`（扫描 80 端口识别 ESP32 Drifter Console），
 * 把本机 DD 地址与小车 ESP32 地址以可点击链接列出，实现"点一下找到车"。
 */
export const FindCarModal: React.FC<{ open: boolean; onClose: () => void }> = ({ open, onClose }) => {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [ddIps, setDdIps] = useState<string[]>([]);
  const [esp32Ips, setEsp32Ips] = useState<string[]>([]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const scan = async () => {
      setLoading(true);
      try {
        const [local, consoles] = await Promise.all([
          getConnectorLocalIps(),
          discoverConnectorConsoles(),
        ]);
        if (cancelled) return;
        setDdIps((local.ips || []).map((x) => x.ip));
        setEsp32Ips((consoles.found || []).map((x) => x.ip));
      } catch {
        if (cancelled) return;
        setDdIps([]);
        setEsp32Ips([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void scan();
    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t('common.findCar.title')}
    >
      <div
        className="w-full max-w-md rounded-lg border border-zinc-700 bg-zinc-900 p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold text-zinc-100">{t('common.findCar.title')}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close')}
            className="text-zinc-400 hover:text-zinc-100 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {loading ? (
          <div className="py-8 text-center text-sm text-zinc-400">{t('common.findCar.scanning')}</div>
        ) : esp32Ips.length === 0 ? (
          <div className="py-8 text-center text-sm text-zinc-400">{t('common.findCar.notFound')}</div>
        ) : (
          <div className="space-y-4 text-sm">
            <div>
              <div className="mb-1 text-xs text-zinc-500">{t('common.findCar.ddLabel')}</div>
              {ddIps.length > 0 ? (
                ddIps.map((ip) => (
                  <a
                    key={`dd-${ip}`}
                    href={`http://${ip}:8000`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block text-cyan-400 hover:underline"
                  >
                    http://{ip}:8000
                  </a>
                ))
              ) : (
                <div className="text-zinc-400">—</div>
              )}
            </div>
            <div>
              <div className="mb-1 text-xs text-zinc-500">{t('common.findCar.esp32Label')}</div>
              {esp32Ips.map((ip) => (
                <a
                  key={`esp32-${ip}`}
                  href={`http://${ip}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block text-cyan-400 hover:underline"
                >
                  http://{ip}
                </a>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
