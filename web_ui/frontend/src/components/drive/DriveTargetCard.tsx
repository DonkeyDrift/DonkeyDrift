import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Crosshair, Loader2, RotateCcw, Wifi, WifiOff } from 'lucide-react';
import { Card, CardContent, CardHeader } from '../ui/Card';
import { SectionCardTitle } from '../ui/SectionCardTitle';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';
import { useStore } from '../../store/useStore';
import {
  discoverSimulator,
  getApiErrorMessage,
  restartDriving,
  saveSimulatorConfig,
  type SimulatorHost,
} from '../../services/api';
import { useTranslation } from '@/i18n';

/** 驾驶目标：真车 / 模拟器 / 未知（无遥测且配置未加载时）。 */
export type DriveTarget = 'car' | 'sim' | 'unknown';

interface DriveTargetCardProps {
  /** 当前派生目标（DrivePage 由遥测/配置/手动选择派生） */
  target: DriveTarget;
  /** 车端驾驶进程是否在线 */
  carOnline: boolean;
  /** 模拟器连接状态（遥测 sim_connected；null 表示未见过该字段） */
  simConnected: boolean | null;
  /** 保存新目标成功后回调（DrivePage 置 manualTarget 并切换模式卡渲染） */
  onSelectTarget: (t: 'car' | 'sim') => void;
}

/** 行内提示类型：错误红、成功绿、信息青。 */
interface Notice {
  type: 'info' | 'success' | 'error';
  message: string;
}

/**
 * 「驾驶目标」卡片：展示当前驾驶目标（真车/模拟器）与车端在线状态，
 * 分段按钮切换目标——本质是改 myconfig.py 的 DONKEY_GYM（切模拟器时
 * 保留/发现 SIM_HOST），保存后需重启本机 manage.py drive 进程生效，
 * 重启走 launcher 的 /api/launch/drive（先杀旧进程再起新的、重读配置）。
 *
 * 模拟器目标（target === 'sim'）时，卡片内以 border-t 展开内嵌模拟器选择区
 * （替代原 Connectors 抽屉的 SimulatorConfig）：进入即自动扫描局域网模拟器、
 * 点选 IP 或手动输入即自动保存，全程无「发现/保存」按钮。
 */
export const DriveTargetCard: React.FC<DriveTargetCardProps> = ({
  target,
  carOnline,
  simConnected,
  onSelectTarget,
}) => {
  const { t } = useTranslation();
  const { config, configPath } = useStore();

  const [saving, setSaving] = useState(false);
  const [restarting, setRestarting] = useState(false);
  // 保存成功待重启：显示琥珀提示 + 「重启驾驶生效」主按钮
  const [pendingRestart, setPendingRestart] = useState(false);
  // 重启失败：除红色错误外，给出 /donkey 降级指引（手动启动驾驶）
  const [restartFailed, setRestartFailed] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  // 模拟器选择区（仅 sim 目标渲染）：扫描 idle（未开始/首帧）→ scanning → done
  const [scanState, setScanState] = useState<'idle' | 'scanning' | 'done'>('idle');
  const [foundHosts, setFoundHosts] = useState<SimulatorHost[]>([]);
  // SIM_HOST 手动输入兜底（自动发现失败时无处点选），保存成功后与配置同步
  const [simHostInput, setSimHostInput] = useState(() =>
    typeof config?.SIM_HOST === 'string' ? config.SIM_HOST : '',
  );

  // 当前已保存的模拟器地址（点选去重与列表高亮的判断基准）
  const currentSimHost = typeof config?.SIM_HOST === 'string' ? config.SIM_HOST : '';

  // 配置中的 SIM_HOST 变化（点选/手动输入保存成功同步、重载配置）时刷新输入框
  useEffect(() => {
    if (typeof config?.SIM_HOST === 'string') setSimHostInput(config.SIM_HOST);
  }, [config?.SIM_HOST]);

  // target 变为 'sim' 时自动扫一次局域网（无按钮）：同次停留不重扫，
  // 切走再切回会重新扫描；发现接口失败视同未发现，由 WifiOff 提示 + 手动输入兜底。
  useEffect(() => {
    if (target !== 'sim') return;
    let cancelled = false;
    setScanState('scanning');
    setFoundHosts([]);
    discoverSimulator(configPath || undefined)
      .then((data) => {
        if (!cancelled) setFoundHosts(data.found ?? []);
      })
      .catch(() => {
        if (!cancelled) setFoundHosts([]);
      })
      .finally(() => {
        if (!cancelled) setScanState('done');
      });
    return () => {
      cancelled = true;
    };
  }, [target, configPath]);

  const targetLabel =
    target === 'car'
      ? t('drive.targetCar')
      : target === 'sim'
        ? t('drive.targetSim')
        : t('drive.targetUnknown');

  // 点分段按钮切换目标：翻转 DONKEY_GYM 写入 myconfig.py。
  // SIM_HOST 保留配置现值；切模拟器且现值为空时先局域网发现 DonkeySim，
  // 找不到则提示手动配置、不保存。
  const handleSelect = useCallback(
    async (next: 'car' | 'sim') => {
      if (next === target || saving || restarting) return;
      setNotice(null);
      setRestartFailed(false);
      if (!configPath) {
        setNotice({ type: 'error', message: t('drive.targetLoadConfigFirst') });
        return;
      }
      const donkeyGym = next === 'sim';
      let simHost = typeof config?.SIM_HOST === 'string' ? config.SIM_HOST : '';
      setSaving(true);
      try {
        if (donkeyGym && !simHost) {
          const data = await discoverSimulator(configPath);
          if (data.found && data.found.length > 0) {
            simHost = data.found[0].ip;
          } else {
            setNotice({ type: 'error', message: t('drive.targetSimNotFound') });
            return;
          }
        }
        await saveSimulatorConfig({
          path: configPath,
          config: { SIM_HOST: simHost, DONKEY_GYM: donkeyGym },
        });
        // 同步全局配置（与点选 IP 保存一致）
        if (config) {
          useStore.setState({
            config: { ...config, SIM_HOST: simHost, DONKEY_GYM: donkeyGym },
          });
        }
        onSelectTarget(next);
        setPendingRestart(true);
      } catch (err: unknown) {
        setNotice({
          type: 'error',
          message: getApiErrorMessage(err, t('drive.targetSaveFailed')),
        });
      } finally {
        setSaving(false);
      }
    },
    [target, saving, restarting, configPath, config, onSelectTarget, t],
  );

  // 保存模拟器地址（点选列表 / 手动输入共用）：写 myconfig.py 的 SIM_HOST +
  // DONKEY_GYM=true 并同步全局配置；目标已是 sim，无需再调 onSelectTarget，
  // 成功后仅置待重启 + 行内 notice，失败走红色错误提示。
  const saveSimHost = useCallback(
    async (ip: string) => {
      if (!configPath) {
        setNotice({ type: 'error', message: t('drive.targetLoadConfigFirst') });
        return;
      }
      setSaving(true);
      try {
        await saveSimulatorConfig({
          path: configPath,
          config: { SIM_HOST: ip, DONKEY_GYM: true },
        });
        if (config) {
          useStore.setState({ config: { ...config, SIM_HOST: ip, DONKEY_GYM: true } });
        }
        setPendingRestart(true);
        setNotice({ type: 'success', message: t('drive.simHostSelected', { ip }) });
      } catch (err: unknown) {
        setNotice({
          type: 'error',
          message: getApiErrorMessage(err, t('drive.targetSaveFailed')),
        });
      } finally {
        setSaving(false);
      }
    },
    [configPath, config, t],
  );

  // 点选发现列表 IP：立即自动保存；点当前已选中的 IP 不重复保存
  const handlePickHost = useCallback(
    (host: SimulatorHost) => {
      if (host.ip === currentSimHost || saving || restarting) return;
      void saveSimHost(host.ip);
    },
    [currentSimHost, saving, restarting, saveSimHost],
  );

  // 手动输入提交（失焦或回车）：trim 非空且与当前值不同才保存
  const commitSimHostInput = useCallback(() => {
    const trimmed = simHostInput.trim();
    if (trimmed && trimmed !== currentSimHost) {
      void saveSimHost(trimmed);
    }
  }, [simHostInput, currentSimHost, saveSimHost]);

  // 「重启驾驶生效」：经后端转发调 launcher 重启 manage.py drive（重读配置）。
  const handleRestart = useCallback(async () => {
    setRestarting(true);
    setNotice(null);
    setRestartFailed(false);
    try {
      const res = await restartDriving();
      if (res?.status === 'launched') {
        setPendingRestart(false);
        setNotice({ type: 'success', message: t('drive.targetRestartedWaiting') });
      } else {
        setRestartFailed(true);
        setNotice({
          type: 'error',
          message: res?.error || t('drive.targetRestartFailed'),
        });
      }
    } catch (err: unknown) {
      setRestartFailed(true);
      setNotice({
        type: 'error',
        message: getApiErrorMessage(err, t('drive.targetRestartFailed')),
      });
    } finally {
      setRestarting(false);
    }
  }, [t]);

  return (
    <Card>
      <CardHeader>
        <SectionCardTitle
          icon={<Crosshair className="w-5 h-5" />}
          title={t('drive.targetTitle')}
          subtitle={t('drive.targetSubtitle')}
        />
      </CardHeader>
      <CardContent className="space-y-3">
        {/* 状态行：当前目标 + 车端在线状态点 + 模拟器离线重连徽标 */}
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-zinc-400">{t('drive.targetCurrent')}</span>
          <span className="text-zinc-100 font-medium">{targetLabel}</span>
          <span className="inline-flex items-center gap-1.5 text-xs text-zinc-400">
            <span
              className={`w-2 h-2 rounded-full ${carOnline ? 'bg-emerald-400' : 'bg-zinc-600'}`}
            />
            {carOnline ? t('drive.targetCarOnline') : t('drive.targetCarOffline')}
          </span>
          {simConnected === false && (
            <span className="inline-flex items-center gap-1 text-amber-400 text-xs font-medium whitespace-nowrap">
              <WifiOff className="w-3.5 h-3.5" aria-hidden />
              {t('drive.simOfflineReconnecting')}
            </span>
          )}
        </div>

        {/* 分段切换：真车 | 模拟器（当前目标高亮） */}
        <div
          className="inline-flex rounded-lg border border-zinc-700 bg-zinc-800/60 p-1 gap-1"
          role="group"
          aria-label={t('drive.targetSwitchAria')}
        >
          {(['car', 'sim'] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => void handleSelect(option)}
              disabled={saving}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                target === option
                  ? 'bg-cyan-600 text-white'
                  : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700'
              } ${saving ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              {option === 'car' ? t('drive.targetCar') : t('drive.targetSim')}
            </button>
          ))}
        </div>

        {/* 已保存待重启：琥珀提示（样式对齐 DrivePage 的 modelRestartRequired 徽章）+ 重启主按钮 */}
        {pendingRestart && (
          <div className="flex flex-wrap items-center gap-2">
            <span
              className="inline-flex items-center px-3 py-1.5 rounded-lg border border-amber-500/30 bg-amber-500/20 text-amber-400 text-xs font-medium whitespace-nowrap"
              role="status"
            >
              {t('drive.targetSavedNeedRestart')}
            </span>
            <Button size="sm" onClick={() => void handleRestart()} disabled={restarting}>
              {restarting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RotateCcw className="w-4 h-4" />
              )}
              {t('drive.targetRestartButton')}
            </Button>
          </div>
        )}

        {/* 行内提示：保存/重启结果（成功绿、失败红） */}
        {notice && (
          <div
            className={`text-xs leading-relaxed ${
              notice.type === 'success'
                ? 'text-emerald-400'
                : notice.type === 'error'
                  ? 'text-red-400'
                  : 'text-cyan-400'
            }`}
            role="status"
          >
            {notice.message}
          </div>
        )}

        {/* 重启失败降级指引：打开 Donkey 菜单手动启动驾驶 */}
        {restartFailed && (
          <Link
            to="/donkey"
            className="inline-block text-xs text-cyan-400 hover:text-cyan-300 underline"
          >
            {t('drive.targetRestartFallbackLink')}
          </Link>
        )}

        {/* 模拟器选择区：仅 sim 目标展开（border-t 分隔）——进入即自动扫描、
            点选 IP 或手动输入即自动保存，无发现/保存按钮（替代原 Connectors 抽屉） */}
        {target === 'sim' && (
          <div className="border-t border-zinc-800 pt-3 space-y-2">
            {/* 扫描中：spinner + 文案 */}
            {scanState === 'scanning' && (
              <div className="flex items-center gap-2 text-xs text-zinc-400" role="status">
                <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />
                {t('drive.simScanning')}
              </div>
            )}

            {/* 扫描完成：发现列表（样式对齐原 SimulatorConfig，当前已选项高亮）或未发现提示 */}
            {scanState === 'done' &&
              (foundHosts.length > 0 ? (
                <div className="space-y-1.5">
                  <p className="text-xs text-zinc-400">{t('drive.simFoundTitle')}</p>
                  <div className="max-h-40 overflow-y-auto space-y-1.5">
                    {foundHosts.map((host) => (
                      <button
                        key={`${host.ip}:${host.port}`}
                        type="button"
                        onClick={() => handlePickHost(host)}
                        disabled={saving}
                        className={`w-full flex items-center justify-between rounded-md border px-3 py-2 text-left transition-colors ${
                          currentSimHost === host.ip
                            ? 'border-cyan-500/50 bg-cyan-950/30'
                            : 'border-zinc-800 bg-zinc-800/50 hover:bg-zinc-800'
                        } ${saving ? 'cursor-not-allowed' : ''}`}
                      >
                        <div className="flex items-center gap-2">
                          <Wifi className="w-4 h-4 text-emerald-400" aria-hidden />
                          <span className="text-sm text-zinc-100 font-mono">
                            {host.ip}:{host.port}
                          </span>
                        </div>
                        <span className="text-xs text-zinc-400">{host.latency_ms}ms</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-2 text-xs text-zinc-500">
                  <WifiOff className="w-3.5 h-3.5" aria-hidden />
                  <span>{t('drive.simNotFoundHint')}</span>
                </div>
              ))}

            {/* SIM_HOST 手动输入兜底：自动发现失败时可手填，失焦或回车自动保存 */}
            <div className="flex items-center gap-2">
              <label htmlFor="drive-sim-host" className="text-xs text-zinc-400 whitespace-nowrap">
                {t('drive.simHostLabel')}
              </label>
              <Input
                id="drive-sim-host"
                value={simHostInput}
                onChange={(e) => setSimHostInput(e.target.value)}
                onBlur={commitSimHostInput}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitSimHostInput();
                }}
                placeholder={t('drive.simHostPlaceholder')}
                className="h-7 w-44 px-2 py-1 text-xs font-mono"
                disabled={saving}
              />
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
