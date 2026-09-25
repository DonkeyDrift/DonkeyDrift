import React, { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { Crosshair, Loader2, RotateCcw } from 'lucide-react';
import { Card, CardContent, CardHeader } from '../ui/Card';
import { SectionCardTitle } from '../ui/SectionCardTitle';
import { Button } from '../ui/Button';
import { useStore } from '../../store/useStore';
import {
  discoverSimulator,
  getApiErrorMessage,
  restartDriving,
  saveSimulatorConfig,
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
        // 同步全局配置（与 SimulatorConfig 保存成功后一致）
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
            <span className="inline-flex items-center px-3 py-1.5 rounded-lg border border-amber-500/30 bg-amber-500/20 text-amber-400 text-xs font-medium whitespace-nowrap">
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
      </CardContent>
    </Card>
  );
};
