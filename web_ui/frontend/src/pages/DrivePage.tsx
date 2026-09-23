import React, { useEffect, useRef, useState, useCallback } from 'react';
import { VideoStream } from '../components/drive/VideoStream';
import { TelemetryChart, TelemetryLegend, curvesByGroup } from '../components/drive/TelemetryChart';
import { VirtualJoystick } from '../components/drive/VirtualJoystick';
import { ControlBars } from '../components/drive/ControlBars';
import { VerticalThrottleBar } from '../components/drive/VerticalThrottleBar';
import { DriveModeSelector, DriveMode, driveModeToRcMode, rcModeToDriveMode } from '../components/drive/DriveModeSelector';
import { useDriveWebsocket, type WebRtcSignal, type Telemetry } from '../hooks/useDriveWebsocket';
import { useDriveControlLoop } from '../hooks/useDriveControlLoop';
import { useKeyboardDrive } from '../hooks/useKeyboardDrive';
import { useDriveHotkeys } from '../hooks/useDriveHotkeys';
import { ProgrammableButtons } from '../components/drive/ProgrammableButtons';
import { ParameterPanel } from '../components/drive/ParameterPanel';
import { InputSourceSelector, InputSource } from '../components/drive/InputSourceSelector';
import { ModelSelector } from '../components/drive/ModelSelector';
import { SimCollectCard } from '../components/drive/SimCollectCard';
import { DriftCard } from '../components/drive/DriftCard';
import { useDriveStore } from '../store/useDriveStore';
import { useStore } from '../store/useStore';
import { useTelemetryStore } from '../store/useTelemetryStore';
import { createDriveClientId, listModels, loadModelToCar, getApiErrorMessage } from '../services/api';
import { useGamepadDrive } from '../hooks/useGamepadDrive';
import { useGyroDrive } from '../hooks/useGyroDrive';
import { useElementWidth, useElementHeight } from '../hooks/useElementWidth';
import { useTranslation } from '@/i18n';
import { cn } from '../lib/utils';
import { Circle, ChevronLeft, ChevronRight, Joystick, Maximize2, Minimize2 } from 'lucide-react';
import { SectionCardTitle } from '../components/ui/SectionCardTitle';

type DrivePageProps = {
  /** 该 section 是否在视口内：滚走后停用全局快捷键/键盘驾驶，避免误触（#178） */
  active?: boolean;
};

// ESP32 手柄输入源：rc 遥测断流判定阈值。车端正常按 100Hz 上行 rc 通道，
// 超过该间隔未收到数据（车离线/固件未上行）时输出 0，不沿用旧油门（#371）。
const ESP32_RC_STALE_MS = 500;

// 右侧摇杆抽屉「右缘常驻 + 连续缩放」布局（docs/issues/008）：窄屏不再折叠到视频下方。
// 抽屉（面板 + 把手）以 transform-origin:top right 随所在行宽连续缩放，负 margin-left 把
// 缩放省下的占位还给视频列；视频列保不住 DOCK_MIN_VIDEO_W 时切「悬浮模式」——
// 抽屉绝对定位吸附右缘、面板降为 DOCK_OVERLAY_OPACITY 半透明浮层浮于视频之上。
const DOCK_PANEL_W = 384; // 与面板 w-96（24rem）一致
const DOCK_CLUSTER_W = DOCK_PANEL_W + 8 + 30; // 设计基准：面板 + 簇内 gap-2 + 把手（zh 竖排）
const DOCK_MIN_SCALE = 0.62;
const DOCK_MIN_VIDEO_W = 320;
const DOCK_OVERLAY_OPACITY = 0.4; // 悬浮模式面板整体不透明度（设计方案确认值）

export const DrivePage = React.memo(function DrivePage({ active = true }: DrivePageProps) {
  const { t, lang } = useTranslation();
  const [webRtcSignal, setWebRtcSignal] = useState<WebRtcSignal | null>(null);
  const clientIdRef = useRef(createDriveClientId());
  // 100Hz 遥测走旁路 feed，不落本组件 state（#135 第八轮）：只把 rc_mode/rc_park
  // 这类低频字段在“值变化”时落一次 state，供驾驶模式跟随与 Park 锁定徽标使用。
  const lastRcModeRef = useRef<number | null>(null);
  const lastRcParkRef = useRef<number | null>(null);
  // ESP32 手柄输入源：缓存遥测 rc_steering/rc_throttle 最新值与到达时刻（断流安全判断用）
  const esp32Ref = useRef({ angle: 0, throttle: 0, updatedAt: 0 });
  // handleTelemetry/getCurrentControl 是稳定回调（不随输入源重建、避免 ws 重连），经 ref 读当前输入源
  const inputSourceRef = useRef<InputSource>('joystick');
  const [rcMode, setRcMode] = useState<number | null>(null);
  const [rcPark, setRcPark] = useState<number | null>(null);
  const [simConnected, setSimConnected] = useState(true);

  const handleTelemetry = useCallback((t: Telemetry) => {
    useTelemetryStore.getState().push(t);
    // ESP32 手柄输入源：缓存车端上行的 rc 通道最新值（值域 -1..1，固件 T 帧）
    if (typeof t.rc_steering === 'number' || typeof t.rc_throttle === 'number') {
      esp32Ref.current = {
        angle: typeof t.rc_steering === 'number' ? t.rc_steering : 0,
        throttle: typeof t.rc_throttle === 'number' ? t.rc_throttle : 0,
        updatedAt: Date.now(),
      };
    }
    if (typeof t.rc_mode === 'number' && t.rc_mode !== lastRcModeRef.current) {
      lastRcModeRef.current = t.rc_mode;
      setRcMode(t.rc_mode);
    }
    if (typeof t.rc_park === 'number' && t.rc_park !== lastRcParkRef.current) {
      lastRcParkRef.current = t.rc_park;
      setRcPark(t.rc_park);
    }
    if (typeof t.sim_connected === 'boolean') {
      setSimConnected(t.sim_connected);
    }
  }, []);

  const { connected, carState, send } = useDriveWebsocket({
    enabled: active,
    onWebRtcSignal: setWebRtcSignal,
    onTelemetry: handleTelemetry,
    clientId: clientIdRef.current,
  });

  // 输入合并：摇杆 + 键盘，后发生效
  const joystickRef = useRef({ angle: 0, throttle: 0 });
  const keyboardRef = useRef({ angle: 0, throttle: 0 });
  const lastInputType = useRef<'joystick' | 'keyboard' | 'gamepad' | 'gyro'>('joystick');

  const [angle, setAngle] = useState(0);
  const [throttle, setThrottle] = useState(0);
  const [mode, setMode] = useState<DriveMode>('user');
  const [recording, setRecording] = useState(false);
  const [recordStartTime, setRecordStartTime] = useState<number | null>(null);
  const [recordDuration, setRecordDuration] = useState(0);
  const [recordingLock, setRecordingLock] = useState(false);
  const recordingLockRef = useRef(false);
  const [currentModel, setCurrentModel] = useState<string>('');
  const [modelLoading, setModelLoading] = useState(false);
  const [modelNotice, setModelNotice] = useState<string | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [inputSource, setInputSource] = useState<InputSource>('joystick');
  useEffect(() => {
    inputSourceRef.current = inputSource;
  }, [inputSource]);
  const [joystickOpen, setJoystickOpen] = useState(false);
  // 摇杆抽屉布局：观测「视频 + 抽屉」行的实际宽度，驱动连续缩放与悬浮模式（docs/issues/008）。
  // 注意 main 用的是 Tailwind container（640/768/1024/1280 断点量化），行宽非连续变化属预期。
  const [dockRowRef, dockRowW] = useElementWidth<HTMLDivElement>();
  // 抽屉自然宽随语言（把手横/竖排）与展开态变化：实测值用于对齐（负 margin）与悬浮阈值；
  // 缩放分母用设计常量，保证缩放手感不随语言抖动
  const [dockAsideRef, dockAsideW] = useElementWidth<HTMLElement>(DOCK_CLUSTER_W);
  // 缩放分支内视频列恒剩 348px（320 底线 + 12 gap + 16 余量）
  const dockScale = Math.min(1, Math.max(DOCK_MIN_SCALE, (dockRowW - 360) / DOCK_CLUSTER_W));
  // 悬浮阈值按「展开态等效宽」判定（收起时 = 把手 + 面板 + gap，恰与展开自然宽相等），
  // 保证收起/展开切换时模式不跳变
  const dockOpenW = joystickOpen ? dockAsideW : dockAsideW + DOCK_PANEL_W + 8;
  const dockOverlay = dockRowW < DOCK_MIN_VIDEO_W + 12 + DOCK_MIN_SCALE * dockOpenW;
  // 悬浮模式下面板顶对齐视频顶：实测工具栏高度让过（工具栏 mb-4 = 16px 间距）
  const [driveToolbarRef, driveToolbarH] = useElementHeight<HTMLDivElement>();
  const [fullscreen, setFullscreen] = useState(false);
  const videoContainerRef = useRef<HTMLDivElement>(null);
  const [steeringVisibleKeys, setSteeringVisibleKeys] = useState<Set<string>>(
    () => new Set(curvesByGroup('steering').filter((c) => c.defaultOn).map((c) => c.key as string)),
  );
  const [throttleVisibleKeys, setThrottleVisibleKeys] = useState<Set<string>>(
    () => new Set(curvesByGroup('throttle').filter((c) => c.defaultOn).map((c) => c.key as string)),
  );
  const gamepadRef = useRef({ angle: 0, throttle: 0 });
  const gyroRef = useRef({ angle: 0, throttle: 0 });

  const toggleSteeringCurve = useCallback((key: string) => {
    setSteeringVisibleKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const toggleThrottleCurve = useCallback((key: string) => {
    setThrottleVisibleKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  // 全选/全不选：把整组曲线一次性设为显示或隐藏
  const setSteeringAll = useCallback((select: boolean) => {
    setSteeringVisibleKeys(select ? new Set(curvesByGroup('steering').map((c) => c.key as string)) : new Set());
  }, []);

  const setThrottleAll = useCallback((select: boolean) => {
    setThrottleVisibleKeys(select ? new Set(curvesByGroup('throttle').map((c) => c.key as string)) : new Set());
  }, []);

  const toggleFullscreen = useCallback(() => {
    const el = videoContainerRef.current;
    if (!el) return;
    if (document.fullscreenElement === el) {
      void document.exitFullscreen();
    } else {
      void el.requestFullscreen();
    }
  }, []);

  // 原生全屏状态随浏览器 fullscreenchange 同步（含 ESC 退出），驱动图标与曲线高度。
  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === videoContainerRef.current);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  const { params, loadFromServer } = useDriveStore();
  const { configPath } = useStore();

  // 页面加载时从服务端拉取参数
  useEffect(() => {
    loadFromServer();
  }, [loadFromServer]);

  // 从 Trainer 加载已训练模型列表
  useEffect(() => {
    if (!configPath) return;
    setModelsLoading(true);
    listModels(configPath)
      .then((data) => {
        const items = (data.models || []) as { name: string }[];
        setModels(items.map((m) => m.name));
      })
      .catch(() => {
        setModels([]);
      })
      .finally(() => {
        setModelsLoading(false);
      });
  }, [configPath]);

  useKeyboardDrive({
    enabled: active && inputSource === 'keyboard',
    params,
    onChange: (a, t) => {
      keyboardRef.current = { angle: a, throttle: t };
      lastInputType.current = 'keyboard';
    },
  });

  const { connected: gamepadConnected } = useGamepadDrive({
    enabled: active && inputSource === 'gamepad',
    onChange: (a, t) => {
      gamepadRef.current = { angle: a, throttle: t };
      lastInputType.current = 'gamepad';
    },
  });

  const { permissionState, requestPermission } = useGyroDrive({
    enabled: active && inputSource === 'gyro',
    onChange: (a, t) => {
      gyroRef.current = { angle: a, throttle: t };
      lastInputType.current = 'gyro';
    },
  });

  // 切换到陀螺仪时自动请求权限
  useEffect(() => {
    if (inputSource === 'gyro' && permissionState === 'prompt') {
      requestPermission();
    }
  }, [inputSource, permissionState, requestPermission]);

  const getCurrentControl = useCallback(() => {
    let a = 0, t = 0;
    // ESP32 手柄：选中即由车端 rc 通道唯一驱动（不与其它输入合并），
    // 透传回控制/录制链路；遥测断流超 ESP32_RC_STALE_MS 时输出 0，不沿用旧油门。
    if (inputSourceRef.current === 'esp32') {
      if (Date.now() - esp32Ref.current.updatedAt <= ESP32_RC_STALE_MS) {
        a = esp32Ref.current.angle;
        t = esp32Ref.current.throttle;
      }
      return { angle: a, throttle: t, drive_mode: mode };
    }
    switch (lastInputType.current) {
      case 'joystick':
        a = joystickRef.current.angle;
        t = joystickRef.current.throttle;
        break;
      case 'keyboard':
        a = keyboardRef.current.angle;
        t = keyboardRef.current.throttle;
        break;
      case 'gamepad':
        a = gamepadRef.current.angle;
        t = gamepadRef.current.throttle;
        break;
      case 'gyro':
        a = gyroRef.current.angle;
        t = gyroRef.current.throttle;
        break;
    }
    return { angle: a, throttle: t, drive_mode: mode };
  }, [mode]);

  // 控制循环：60Hz 持续发送完整控制状态，避免视频链路影响控制输出。
  useDriveControlLoop({
    connected,
    send,
    getControl: getCurrentControl,
  });

  // UI 显示无需驱动控制发送，按较低频率同步即可；section 滚走后停表（#178）。
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => {
      const control = getCurrentControl();
      setAngle(control.angle);
      setThrottle(control.throttle);
    }, 50);
    return () => clearInterval(timer);
  }, [getCurrentControl, active]);

  // 录制时长计时器
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    if (recording && recordStartTime) {
      timer = setInterval(() => {
        setRecordDuration(Math.floor((Date.now() - recordStartTime) / 1000));
      }, 1000);
    } else {
      setRecordDuration(0);
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [recording, recordStartTime]);

  // 同步车端模式
  useEffect(() => {
    setMode(carState.driveMode as DriveMode);
    setRecording(carState.recording);
    if (carState.recording && !recordStartTime) {
      setRecordStartTime(Date.now());
    }
    if (!carState.recording) {
      setRecordStartTime(null);
    }
  }, [carState.driveMode, carState.recording, recordStartTime]);

  // 车端真实模式（ESP32 rc_mode）变化时，选择器跟随（遥控器/DC 端切换）。
  // 仅接受 0/1/2；无遥测时由上面的 carState.driveMode 兜底。
  useEffect(() => {
    if (rcMode === 0 || rcMode === 1 || rcMode === 2) {
      setMode(rcModeToDriveMode(rcMode));
    }
  }, [rcMode]);

  const handleModeChange = useCallback((newMode: DriveMode) => {
    setMode(newMode);
    send({ drive_mode: newMode, car_mode: driveModeToRcMode(newMode) });
  }, [send]);

  const handleModelChange = useCallback((modelName: string) => {
    setCurrentModel(modelName);
    setModelNotice(null);
    // 「无模型」仅清空页面选择，不请求车端（车端暂无卸载通道）。
    if (!modelName || !configPath) return;
    // 选模型 = 请求车端运行期热加载（issue #003），无需重启车端进程。
    const modelPath = `./models/${modelName}`;
    setModelLoading(true);
    loadModelToCar(modelPath, configPath)
      .then((res) => {
        if (res?.success && !res?.restart_required) {
          setModelNotice(t('drive.modelLoaded'));
        } else if (res?.restart_required) {
          setModelNotice(t('drive.modelRestartRequired'));
        } else {
          setModelNotice(res?.message || t('drive.modelLoadFailed'));
        }
      })
      .catch((err) => {
        setModelNotice(`${t('drive.modelLoadFailed')}: ${getApiErrorMessage(err)}`);
      })
      .finally(() => setModelLoading(false));
  }, [configPath, t]);

  const cycleMode = useCallback(() => {
    const modes: DriveMode[] = ['user', 'local_angle', 'local'];
    const idx = modes.indexOf(mode);
    handleModeChange(modes[(idx + 1) % modes.length]);
  }, [handleModeChange, mode]);

  const toggleRecording = useCallback(() => {
    if (recordingLockRef.current) return;
    recordingLockRef.current = true;
    setRecordingLock(true);
    window.setTimeout(() => {
      recordingLockRef.current = false;
      setRecordingLock(false);
    }, 800);

    const next = !recording;
    setRecording(next);
    send({ recording: next });
    if (next) {
      setRecordStartTime(Date.now());
    } else {
      setRecordStartTime(null);
    }
  }, [recording, send]);

  // 快捷键（仅在 drive section 可见时启用，避免流程页其它区域误触 #178）
  useDriveHotkeys({
    enabled: active,
    onToggleRecording: toggleRecording,
    onCycleMode: cycleMode,
    onSetModeUser: () => handleModeChange('user'),
    onSetModeAutoSteer: () => handleModeChange('local_angle'),
    onSetModeFullAuto: () => handleModeChange('local'),
  });

  const formatDuration = (s: number) => {
    const min = Math.floor(s / 60);
    const sec = s % 60;
    return `${min}:${sec.toString().padStart(2, '0')}`;
  };

  return (
    <div className="space-y-4">
      <DriftCard />
      <SimCollectCard />
      {/* 视频 + 遥测 | 右侧抽屉：任何屏宽保持左右并排，抽屉右缘常驻、随宽度连续缩放（008）；
          窄屏抽屉转悬浮半透明浮层，不再折叠到视频下方 */}
      <div ref={dockRowRef} className="relative flex flex-row items-start gap-3">
        {/* 左：视频 + 遥测（顶部工具栏与视频同列，右边缘与视频画面右边界对齐） */}
        <div className="flex-1 min-w-0 flex flex-col lg:h-[calc(100vh-9rem)]">
          <div ref={driveToolbarRef} className="flex flex-wrap items-center justify-between gap-2 mb-4 shrink-0">
            {/* 左：Park 状态 + 驾驶模式 + 模型 */}
            <div className="flex flex-wrap items-center gap-2 lg:gap-3">
              {rcPark === 1 && (
                <span
                  className="inline-flex items-center px-3 py-1.5 rounded-lg border border-red-500/30 bg-red-500/20 text-red-400 text-xs font-medium whitespace-nowrap"
                  data-rc-park={rcPark}
                >
                  {t('drive.parkLocked')}
                </span>
              )}
              {simConnected === false && (
                <span
                  className="inline-flex items-center px-3 py-1.5 rounded-lg border border-amber-500/30 bg-amber-500/20 text-amber-400 text-xs font-medium whitespace-nowrap"
                  data-sim-connected={simConnected}
                >
                  {t('drive.simOfflineReconnecting')}
                </span>
              )}
              <DriveModeSelector value={mode} onChange={handleModeChange} disabled={!carState.online} />
              <ModelSelector
                value={currentModel}
                options={models}
                onChange={handleModelChange}
                disabled={!carState.online || modelsLoading || modelLoading}
              />
              {modelLoading && (
                <span
                  className="inline-flex items-center px-3 py-1.5 rounded-lg border border-cyan-500/30 bg-cyan-500/20 text-cyan-400 text-xs font-medium whitespace-nowrap animate-pulse"
                  data-model-loading="true"
                >
                  {t('drive.modelLoading')}
                </span>
              )}
              {!modelLoading && modelNotice && (
                <span
                  className="inline-flex items-center px-3 py-1.5 rounded-lg border border-amber-500/30 bg-amber-500/20 text-amber-400 text-xs font-medium whitespace-nowrap"
                  data-model-notice="true"
                  role="status"
                >
                  {modelNotice}
                </span>
              )}
            </div>
            {/* 右：已录制条数 + 录制 */}
            <div className="flex flex-wrap items-center gap-2 lg:gap-3">
              <span className="text-xs text-zinc-500 whitespace-nowrap">
                {t('drive.recordedCount', { count: carState.numRecords })}
              </span>
              <button
                onClick={toggleRecording}
                disabled={!carState.online || recordingLock}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
                  ${recording
                    ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
                    : 'bg-zinc-800 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700'
                  }
                  ${!carState.online || recordingLock ? 'opacity-50 cursor-not-allowed' : ''}
                `}
              >
                {recording ? (
                  <Circle className="w-3.5 h-3.5 fill-current animate-pulse text-red-400" />
                ) : (
                  <Circle className="w-3.5 h-3.5" />
                )}
                {recording ? t('drive.recording', { duration: formatDuration(recordDuration) }) : t('drive.record')}
              </button>
            </div>
          </div>

          {/* 摄像头：填满剩余空间并裁边放大；遥测曲线左右分栏覆盖在画面下方；右下角为原生全屏放大 */}
          <div
            ref={videoContainerRef}
            className={cn(
              'relative flex-1 min-h-0 aspect-video lg:aspect-auto bg-black',
              !fullscreen && 'rounded-lg overflow-hidden',
            )}
          >
            {active ? (
              <VideoStream className="w-full h-full" objectFit="cover" incomingSignal={webRtcSignal} clientId={clientIdRef.current} />
            ) : (
              <div className="w-full h-full bg-zinc-950 border border-zinc-800 rounded-lg" />
            )}
            <div className="absolute inset-x-3 bottom-3 z-20 grid grid-cols-1 md:grid-cols-2 gap-3">
              <TelemetryChart
                active={active}
                overlay
                title="driveViz.chartTitleSteering"
                group="steering"
                visibleKeys={steeringVisibleKeys}
                onToggleCurve={toggleSteeringCurve}
                chartHeightClassName={fullscreen ? 'h-44' : undefined}
              />
              <TelemetryChart
                active={active}
                overlay
                title="driveViz.chartTitleThrottle"
                group="throttle"
                visibleKeys={throttleVisibleKeys}
                onToggleCurve={toggleThrottleCurve}
                chartHeightClassName={fullscreen ? 'h-44' : undefined}
              />
            </div>
            {/* 全屏/放大：整个视频画面右下角（与遥测浮层同 inset，叠在曲线之上 z-30） */}
            <button
              type="button"
              onClick={toggleFullscreen}
              title={fullscreen ? t('driveViz.exitFullscreen') : t('driveViz.fullscreen')}
              aria-label={fullscreen ? t('driveViz.exitFullscreen') : t('driveViz.fullscreen')}
              className="dd-overlay absolute right-3 bottom-3 z-30 p-2 rounded-lg bg-slate-950/60 backdrop-blur-sm border border-white/10 text-slate-200 hover:text-white hover:bg-slate-900/70 transition-colors"
            >
              {fullscreen ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
            </button>
          </div>
          {/* 曲线显隐图例：分左右两组放在视频画面外部（下方），不再遮挡画面；每组左侧带「全选」 */}
          <div className="mt-3 shrink-0 grid grid-cols-1 md:grid-cols-2 gap-3">
            <TelemetryLegend group="steering" visibleKeys={steeringVisibleKeys} onToggle={toggleSteeringCurve} onToggleAll={setSteeringAll} />
            <TelemetryLegend group="throttle" visibleKeys={throttleVisibleKeys} onToggle={toggleThrottleCurve} onToggleAll={setThrottleAll} />
          </div>
        </div>

        {/* 右：摇杆抽屉（面板 + 把手）——右缘常驻（008）：贴地时以负 margin-left 把缩放省出的
            占位还给视频列（负左边距使抽屉整体左移、右缘仍齐容器右缘），悬浮模式绝对定位
            吸附右缘浮于视频之上；缩放锚定右上角，sticky 行为在贴地分支保持不变 */}
        <aside
          ref={dockAsideRef}
          className={cn(
            'z-40 shrink-0 transition-[margin,transform] duration-300 ease-in-out will-change-transform',
            dockOverlay ? 'absolute right-2.5' : 'lg:sticky lg:top-16',
          )}
          style={{
            transform: `scale(${dockScale})`,
            transformOrigin: 'top right',
            top: dockOverlay ? driveToolbarH + 16 : undefined,
            marginLeft: dockOverlay ? undefined : -Math.round(dockAsideW * (1 - dockScale)),
          }}
        >
          <div className="flex items-start gap-2">
            {/* 面板内容：夹在视频画面与把手（展开开关）之间；宽度固定自然宽，缩放交给 transform */}
            <div
              className={`${joystickOpen ? 'w-96 border' : 'w-0 border-0'} max-h-[calc(100vh-143px)] lg:max-h-[calc(100vh-4rem)] bg-zinc-900 border-zinc-800 shadow-2xl overflow-y-auto overflow-x-hidden rounded-lg will-change-[width,opacity] transition-[width,opacity] duration-300 ease-in-out ${
                joystickOpen && dockOverlay ? 'border-cyan-500/30 backdrop-blur-[2px]' : ''
              }`}
              style={joystickOpen && dockOverlay ? { opacity: DOCK_OVERLAY_OPACITY } : undefined}
            >
              <div className={`p-4 space-y-4 transition-opacity duration-300 ${joystickOpen ? 'opacity-100' : 'opacity-0'}`}>
                <div className="flex items-center justify-between gap-2">
                  <SectionCardTitle
                    icon={<Joystick className="w-5 h-5" />}
                    title={t('drive.virtualJoystick')}
                  />
                  <InputSourceSelector
                    value={inputSource}
                    onChange={setInputSource}
                    gamepadConnected={gamepadConnected}
                    gyroAvailable={permissionState !== 'unsupported'}
                  />
                </div>
                <div className="flex flex-col items-center gap-4">
                  <div className="grid grid-cols-[auto_220px] gap-6">
                    <VerticalThrottleBar throttle={throttle} className="h-[220px]" />
                    <div className="flex flex-col items-center gap-2 w-[220px]">
                      <VirtualJoystick
                        scale={dockScale}
                        onChange={(a, t) => {
                          joystickRef.current = { angle: a, throttle: t };
                          lastInputType.current = 'joystick';
                        }}
                        size={220}
                      />
                      <ControlBars angle={angle} className="w-full" />
                    </div>
                  </div>
                  <ProgrammableButtons className="w-full max-w-[240px]" />
                  <ParameterPanel className="w-full max-w-[360px]" />
                  <div className="text-[10px] text-zinc-500 text-center">
                    {t('drive.hotkeysLine1')}<br />
                    {t('drive.hotkeysLine2')}
                  </div>
                </div>
              </div>
            </div>

            {/* 浮动触发把手：抽屉收起/展开开关；中文竖排、英文横排两行 */}
            <button
              onClick={() => setJoystickOpen(!joystickOpen)}
              title={joystickOpen ? t('drive.collapseJoystick') : t('drive.expandJoystick')}
              className="shrink-0 border rounded-lg transition-all duration-300 shadow-lg flex flex-col items-center gap-1 px-1.5 py-2 bg-zinc-900 text-zinc-400 border-zinc-800 hover:bg-zinc-800 hover:text-white"
            >
              {joystickOpen ? <ChevronRight className="w-4 h-4 shrink-0" /> : <ChevronLeft className="w-4 h-4 shrink-0" />}
              {lang === 'en' ? (
                <span className="flex flex-col items-center leading-none text-xs font-medium tracking-wide">
                  {t('drive.virtualJoystick').split(' ').map((word) => (
                    <span key={word}>{word}</span>
                  ))}
                </span>
              ) : (
                <span className="text-xs font-medium [writing-mode:vertical-rl] tracking-wider leading-none">
                  {t('drive.virtualJoystick')}
                </span>
              )}
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
});
