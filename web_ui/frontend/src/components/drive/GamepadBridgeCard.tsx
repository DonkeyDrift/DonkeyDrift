import React, { useCallback, useEffect, useState } from 'react';
import { Gamepad2, Loader2, RefreshCw, RotateCcw } from 'lucide-react';
import { Card, CardContent, CardHeader } from '../ui/Card';
import { SectionCardTitle } from '../ui/SectionCardTitle';
import { Button } from '../ui/Button';
import { Modal } from '../Modal';
import { useConsoleDevice, invalidateConsoleDeviceCache } from '../../hooks/useConsoleDevice';
import { consoleGetJson, consolePostText } from '../../services/console';
import { useTranslation } from '@/i18n';

// 「手柄桥模式」卡片：车上 ESP32 双启动槽位（车固件 / RC_BLE_Bridge 手柄桥固件）
// 的一键切换。两个固件在同一 IP:80 提供对称接口（Firmware MUS4_FW）：
//   GET  /api/slot-info   → {"app":"car"|"bridge","running":"app0|app1","other":"app1|app0","other_kind":"car|bridge|unknown|empty"}
//   POST /api/switch-slot → 200 ACK:SWITCHING 后立刻重启进对面槽位（约 10 秒）；对面空 → 400 NACK:NO_IMAGE
// 全部请求经 DD 后端 /api/console/proxy 同源代理转发（与顶栏静音/DEV 控件同款链路），
// 后端零改动。桥固件根页面同样含 "Drifter Console" 字样，useConsoleDevice 的局域网
// 发现在两种模式下都能认出设备。

/** /api/slot-info 响应（字段名与 WebConsoleServer.cpp / RC_BLE_Bridge.ino 对齐）。 */
export interface BridgeSlotInfo {
  app?: string;
  running?: string;
  other?: string;
  other_kind?: string;
}

// 切换后轮询节奏：设备重启约 10 秒，每 2 秒探一次 slot-info（重启期间请求失败属正常），
// 直到返回的 app 翻成目标值；总时长超过 SWITCH_TIMEOUT_MS 判定超时。
const SWITCH_POLL_MS = 2000;
const SWITCH_TIMEOUT_MS = 40000;

/**
 * 手柄桥模式卡片（无 props，内部用 useConsoleDevice 拿车端 IP）：
 * - 车模式 + 对槽已装桥（other_kind=bridge）：主按钮「切换到手柄桥」，确认后切换；
 * - 车模式 + 对槽未装桥（empty/unknown）：按钮禁用 + 补种指引；
 * - 桥模式（app=bridge）：绿色运行状态 + 「切回真车」；
 * - 切换中：琥珀提示 + 轮询等待 app 翻转，超时给红色兜底。
 */
export const GamepadBridgeCard: React.FC = () => {
  const { t } = useTranslation();
  const { ip, resolving, refresh } = useConsoleDevice();

  const [slotInfo, setSlotInfo] = useState<BridgeSlotInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  // 非 null 表示「切换中」：POST 已发出，正在轮询等待 app 翻成该值
  const [awaitingApp, setAwaitingApp] = useState<'car' | 'bridge' | null>(null);
  const [timedOut, setTimedOut] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 读取槽位信息；失败（多为缓存 IP 失效）时与 DEV 开关同款自愈：使缓存失效重扫，
  // ip 更新后下方 effect 会自动用新 IP 重取。成功返回数据，失败返回 null。
  const fetchSlotInfo = useCallback(async (): Promise<BridgeSlotInfo | null> => {
    if (!ip) return null;
    try {
      const data = await consoleGetJson<BridgeSlotInfo>(ip, 'api/slot-info');
      setSlotInfo(data);
      return data;
    } catch {
      refresh();
      return null;
    }
  }, [ip, refresh]);

  // 初次 / IP 变化时读取槽位信息。ip 为空（未发现设备）时 useConsoleDevice 会慢速
  // 重扫，扫到后 ip 更新、本 effect 自动重跑，无需手动兜底。
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setSlotInfo(null);
    setError(null);
    setTimedOut(false);
    void fetchSlotInfo().then((data) => {
      if (cancelled) return;
      if (!data) setSlotInfo(null);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [fetchSlotInfo]);

  // 切换中轮询：POST 成功后设备立刻重启，期间请求全断；每 2s 探一次直到 app 翻转。
  useEffect(() => {
    if (!awaitingApp || !ip) return;
    let cancelled = false;
    const started = Date.now();
    const poll = async () => {
      while (!cancelled && Date.now() - started < SWITCH_TIMEOUT_MS) {
        await new Promise((resolve) => window.setTimeout(resolve, SWITCH_POLL_MS));
        if (cancelled) return;
        try {
          const data = await consoleGetJson<BridgeSlotInfo>(ip, 'api/slot-info');
          if (cancelled) return;
          if (data?.app === awaitingApp) {
            setSlotInfo(data);
            setAwaitingApp(null);
            // 切回车固件后主动刷新控制台发现缓存（桥 → 车身份变化）
            if (awaitingApp === 'car') invalidateConsoleDeviceCache();
            return;
          }
        } catch {
          // 重启中断线属正常，忽略继续
        }
      }
      if (!cancelled) {
        setAwaitingApp(null);
        setTimedOut(true);
      }
    };
    void poll();
    return () => {
      cancelled = true;
    };
  }, [awaitingApp, ip]);

  const app = slotInfo?.app === 'bridge' ? 'bridge' : slotInfo?.app === 'car' ? 'car' : null;
  const bridgeSeeded = app === 'car' && slotInfo?.other_kind === 'bridge';
  const switching = awaitingApp !== null;

  // 确认切换：先发 POST，成功后进入「切换中」轮询；POST 本身失败（含 400 NACK:NO_IMAGE）
  // 不进入轮询，行内红字提示。
  const handleConfirm = useCallback(async () => {
    setConfirmOpen(false);
    if (!ip || !app || switching) return;
    setError(null);
    setTimedOut(false);
    try {
      await consolePostText(ip, 'api/switch-slot', '');
    } catch {
      setError(t('drive.bridgeSwitchFailed'));
      return;
    }
    setAwaitingApp(app === 'car' ? 'bridge' : 'car');
  }, [ip, app, switching, t]);

  const handleRetry = useCallback(async () => {
    setLoading(true);
    setError(null);
    const data = await fetchSlotInfo();
    if (!data) setSlotInfo(null);
    setLoading(false);
  }, [fetchSlotInfo]);

  const toBridge = app !== 'bridge';
  const confirmTitle = toBridge
    ? t('drive.bridgeConfirmToBridgeTitle')
    : t('drive.bridgeConfirmToCarTitle');
  const confirmBody = toBridge
    ? t('drive.bridgeConfirmToBridgeBody')
    : t('drive.bridgeConfirmToCarBody');

  return (
    <>
      <Card>
        <CardHeader>
          <SectionCardTitle
            icon={<Gamepad2 className="w-5 h-5" />}
            title={t('drive.bridgeTitle')}
            subtitle={t('drive.bridgeSubtitle')}
          />
        </CardHeader>
        <CardContent className="space-y-3">
          {/* 状态行：当前槽位模式（加载中 / 桥运行绿 / 车模式 / 不可达兜底） */}
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-zinc-400">{t('drive.bridgeStatus')}</span>
            {loading || (!ip && resolving) ? (
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-zinc-400">
                <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" aria-hidden />
                {t('drive.bridgeChecking')}
              </span>
            ) : app === 'bridge' ? (
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-400">
                <span className="w-2 h-2 rounded-full bg-emerald-400" />
                {t('drive.bridgeRunning')}
              </span>
            ) : app === 'car' ? (
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-zinc-100">
                <span
                  className={`w-2 h-2 rounded-full ${bridgeSeeded ? 'bg-cyan-400' : 'bg-zinc-600'}`}
                />
                {bridgeSeeded ? t('drive.bridgeReady') : t('drive.bridgeNotDetected')}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-zinc-400">
                <span className="w-2 h-2 rounded-full bg-zinc-600" />
                {t('drive.bridgeUnreachable')}
              </span>
            )}
            {/* 读取失败兜底：手动重试（ip 存在但请求失败时才出现；ip 缺失靠自动重扫） */}
            {!loading && ip && !slotInfo && (
              <Button size="sm" variant="secondary" onClick={() => void handleRetry()}>
                <RefreshCw className="w-4 h-4" aria-hidden />
                {t('drive.bridgeRetry')}
              </Button>
            )}
          </div>

          {/* 主按钮 + 切换中琥珀提示（样式对齐 DriveTargetCard 的 pendingRestart 行） */}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              onClick={() => setConfirmOpen(true)}
              disabled={switching || loading || !app || (toBridge && !bridgeSeeded)}
            >
              {switching ? (
                <Loader2 className="w-4 h-4 animate-spin" aria-hidden />
              ) : toBridge ? (
                <Gamepad2 className="w-4 h-4" aria-hidden />
              ) : (
                <RotateCcw className="w-4 h-4" aria-hidden />
              )}
              {toBridge ? t('drive.bridgeSwitchToBridge') : t('drive.bridgeSwitchToCar')}
            </Button>
            {switching && (
              <span
                className="inline-flex items-center px-3 py-1.5 rounded-lg border border-amber-500/30 bg-amber-500/20 text-amber-400 text-xs font-medium whitespace-nowrap"
                role="status"
              >
                {t('drive.bridgeSwitching')}
              </span>
            )}
          </div>

          {/* 未装桥：禁用按钮的补种指引 */}
          {app === 'car' && !bridgeSeeded && !loading && (
            <div className="text-xs leading-relaxed text-zinc-400">
              {t('drive.bridgeNotInstalled')}
            </div>
          )}

          {/* 行内提示：POST 失败 / 轮询超时（红） */}
          {error && (
            <div className="text-xs leading-relaxed text-red-400" role="status">
              {error}
            </div>
          )}
          {timedOut && (
            <div className="text-xs leading-relaxed text-red-400" role="status">
              {t('drive.bridgeTimeout')}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 切换确认框（模式同 ConsoleDevToggle）：说明重启约 10 秒、期间离线 */}
      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        label={confirmTitle}
        className="bg-zinc-900 border border-zinc-800 rounded-lg shadow-xl w-full max-w-md flex flex-col overflow-hidden"
      >
        <div className="p-4 border-b border-zinc-800 bg-zinc-900/50">
          <h2 className="text-base font-semibold text-zinc-100">{confirmTitle}</h2>
        </div>
        <div className="p-4 text-sm text-zinc-300 leading-relaxed">{confirmBody}</div>
        <div className="p-4 border-t border-zinc-800 bg-zinc-900/50 flex justify-end gap-3">
          <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
            {t('drive.bridgeCancel')}
          </Button>
          <Button onClick={() => void handleConfirm()}>{t('drive.bridgeConfirm')}</Button>
        </div>
      </Modal>
    </>
  );
};
