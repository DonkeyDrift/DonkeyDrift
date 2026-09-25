import { useCallback, useEffect, useRef, useState } from 'react';
import { DriveMode, driveModeToRcMode } from '../components/drive/DriveModeSelector';

interface UseModelRestartOptions {
  /** 车端是否在线（carState.online） */
  online: boolean;
  /** 车端回报的模式（carState.driveMode，未经页面侧抑制） */
  reportedMode: DriveMode;
  /** 读取选择器当前最新模式（重启窗口内快捷键改模式也应生效） */
  getMode: () => DriveMode;
  send: (data: Record<string, unknown>) => boolean;
  onTimeout?: () => void;
  /** 整体超时：车端迟迟未恢复在线时放弃等待（默认 120s） */
  timeoutMs?: number;
  /** 补发后的收敛等待窗口：车端回报始终与当前模式一致（无变化事件）时兜底结束（默认 3s） */
  settleMs?: number;
}

/**
 * 选模型后的车端重启状态机（issue #003）。
 *
 * 后端确认「带模型重启」后调用 begin()：
 * 1. restarting=true（调用方据此抑制车端→页面的模式回同步、禁用切换控件）；
 * 2. 等车端掉线再上线后，主动补发当前模式 {drive_mode, car_mode}——
 *    车端进程重启后默认 user，不补发全自动/半自动就丢了；
 * 3. 车端回报与当前模式一致（收敛）或 settle 窗口结束 → restarting=false；
 * 4. 整体超时仍未恢复 → 结束并 onTimeout。
 */
export const useModelRestart = ({
  online,
  reportedMode,
  getMode,
  send,
  onTimeout,
  timeoutMs = 120_000,
  settleMs = 3_000,
}: UseModelRestartOptions) => {
  const [restarting, setRestarting] = useState(false);
  const seenOfflineRef = useRef(false);
  const restoredRef = useRef(false);
  const timeoutTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const settleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // begin() 是事件回调，需要通过 ref 读到调用时刻的 online
  const onlineRef = useRef(online);
  onlineRef.current = online;
  const onTimeoutRef = useRef(onTimeout);
  onTimeoutRef.current = onTimeout;

  const clearTimers = useCallback(() => {
    if (timeoutTimerRef.current) {
      clearTimeout(timeoutTimerRef.current);
      timeoutTimerRef.current = null;
    }
    if (settleTimerRef.current) {
      clearTimeout(settleTimerRef.current);
      settleTimerRef.current = null;
    }
  }, []);

  const finish = useCallback(() => {
    clearTimers();
    setRestarting(false);
  }, [clearTimers]);

  const begin = useCallback(() => {
    clearTimers();
    // 车当前已离线（进程没在跑）时无需再等掉线，上线即补发
    seenOfflineRef.current = !onlineRef.current;
    restoredRef.current = false;
    setRestarting(true);
    timeoutTimerRef.current = setTimeout(() => {
      timeoutTimerRef.current = null;
      setRestarting(false);
      onTimeoutRef.current?.();
    }, timeoutMs);
  }, [clearTimers, timeoutMs]);

  useEffect(() => {
    if (!restarting) return;
    if (!online) {
      seenOfflineRef.current = true;
      return;
    }
    if (!seenOfflineRef.current) return;
    if (!restoredRef.current) {
      restoredRef.current = true;
      const mode = getMode();
      send({ drive_mode: mode, car_mode: driveModeToRcMode(mode) });
      // 回报值可能与当前模式始终相等（前端对相同值去重、无变化事件），
      // 用 settle 窗口兜底结束；期间若车端先报了别的值再走收敛分支。
      settleTimerRef.current = setTimeout(finish, settleMs);
      return;
    }
    if (reportedMode === getMode()) {
      finish();
    }
  }, [restarting, online, reportedMode, getMode, send, finish, settleMs]);

  // 卸载时清理定时器
  useEffect(() => clearTimers, [clearTimers]);

  return { restarting, begin };
};
