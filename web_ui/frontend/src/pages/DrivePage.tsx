import React, { useEffect, useRef, useState, useCallback } from 'react';
import { VideoStream } from '../components/drive/VideoStream';
import { TelemetryChart } from '../components/drive/TelemetryChart';
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
import { useDriveStore } from '../store/useDriveStore';
import { useStore } from '../store/useStore';
import { createDriveClientId, listModels, loadModelToCar, getApiErrorMessage } from '../services/api';
import { useGamepadDrive } from '../hooks/useGamepadDrive';
import { useGyroDrive } from '../hooks/useGyroDrive';
import { useTranslation } from '@/i18n';
import { Circle, ChevronLeft, ChevronRight, Joystick } from 'lucide-react';
import { SectionCardTitle } from '../components/ui/SectionCardTitle';

type DrivePageProps = {
  /** 该 section 是否在视口内：滚走后停用全局快捷键/键盘驾驶，避免误触（#178） */
  active?: boolean;
};

export const DrivePage = React.memo(function DrivePage({ active = true }: DrivePageProps) {
  const { t } = useTranslation();
  const [webRtcSignal, setWebRtcSignal] = useState<WebRtcSignal | null>(null);
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const clientIdRef = useRef(createDriveClientId());
  const { connected, carState, send } = useDriveWebsocket({
    enabled: active,
    onWebRtcSignal: setWebRtcSignal,
    onTelemetry: setTelemetry,
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
  const [models, setModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [inputSource, setInputSource] = useState<InputSource>('joystick');
  const [joystickOpen, setJoystickOpen] = useState(false);
  const gamepadRef = useRef({ angle: 0, throttle: 0 });
  const gyroRef = useRef({ angle: 0, throttle: 0 });

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
    if (typeof telemetry?.rc_mode === 'number') {
      const rcMode = telemetry.rc_mode;
      if (rcMode === 0 || rcMode === 1 || rcMode === 2) {
        setMode(rcModeToDriveMode(rcMode));
      }
    }
  }, [telemetry?.rc_mode]);

  const handleModeChange = useCallback((newMode: DriveMode) => {
    setMode(newMode);
    send({ drive_mode: newMode, car_mode: driveModeToRcMode(newMode) });
  }, [send]);

  const handleModelChange = useCallback((modelName: string) => {
    setCurrentModel(modelName);
    if (modelName && configPath) {
      const modelPath = `./models/${modelName}`;
      loadModelToCar(modelPath, configPath).catch((err) => {
        console.warn('加载模型到车端失败:', getApiErrorMessage(err));
      });
    }
  }, [configPath]);

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
      {/* 视频 + 遥测 | 右侧抽屉：桌面端左右并排，抽屉 sticky 顶部对齐视频、滚动时留在顶部不跟走 */}
      <div className="flex flex-col lg:flex-row lg:items-start lg:gap-3">
        {/* 左：视频 + 遥测（顶部工具栏与视频同列，右边缘与视频画面右边界对齐） */}
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
            {/* 左：Park 状态 + 驾驶模式 + 模型 */}
            <div className="flex flex-wrap items-center gap-2 lg:gap-3">
              {telemetry?.rc_park === 1 && (
                <span
                  className="inline-flex items-center px-3 py-1.5 rounded-lg border border-red-500/30 bg-red-500/20 text-red-400 text-xs font-medium whitespace-nowrap"
                  data-rc-park={telemetry.rc_park}
                >
                  {t('drive.parkLocked')}
                </span>
              )}
              <DriveModeSelector value={mode} onChange={handleModeChange} disabled={!carState.online} />
              <ModelSelector
                value={currentModel}
                options={models}
                onChange={handleModelChange}
                disabled={!carState.online || modelsLoading}
              />
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

          {active ? (
            <VideoStream className="w-full" incomingSignal={webRtcSignal} clientId={clientIdRef.current} />
          ) : (
            <div className="w-full aspect-video bg-zinc-950 border border-zinc-800 rounded-lg" />
          )}
          <TelemetryChart telemetry={telemetry} className="mt-4" active={active} />
        </div>

        {/* 右：抽屉（sticky 顶部对齐视频，滚动时留在顶部不跟走；四角圆角对齐视频边框） */}
        <aside className="z-40 lg:sticky lg:top-16 lg:shrink-0">
          <div className="flex items-start gap-2">
            {/* 面板内容：夹在视频画面与把手（展开开关）之间 */}
            <div className={`${joystickOpen ? 'w-[min(24rem,calc(100vw-3.5rem))] border' : 'w-0 border-0'} max-h-[calc(100vh-143px)] lg:max-h-[calc(100vh-4rem)] bg-zinc-900 border-zinc-800 shadow-2xl overflow-y-auto overflow-x-hidden rounded-lg will-change-[width] transition-[width] duration-300 ease-in-out`}>
              <div className={`p-4 space-y-4 transition-opacity duration-300 ${joystickOpen ? 'opacity-100' : 'opacity-0'}`}>
                <div className="flex items-center justify-between gap-2">
                  <SectionCardTitle
                    icon={<Joystick className="w-5 h-5" />}
                    title={t('drive.virtualJoystick')}
                    subtitle={t('drive.virtualJoystickSubtitle')}
                    subtitleMarquee
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

            {/* 浮动触发把手：抽屉收起/展开开关；「虚拟摇杆」竖排书写 */}
            <button
              onClick={() => setJoystickOpen(!joystickOpen)}
              title={joystickOpen ? t('drive.collapseJoystick') : t('drive.expandJoystick')}
              className="shrink-0 border rounded-lg transition-all duration-300 shadow-lg flex flex-col items-center gap-1 px-1.5 py-2 bg-zinc-900 text-zinc-400 border-zinc-800 hover:bg-zinc-800 hover:text-white"
            >
              {joystickOpen ? <ChevronRight className="w-4 h-4 shrink-0" /> : <ChevronLeft className="w-4 h-4 shrink-0" />}
              <span className="text-xs font-medium [writing-mode:vertical-rl] tracking-wider leading-none">
                {t('drive.virtualJoystick')}
              </span>
            </button>
          </div>
        </aside>
      </div>

    </div>
  );
});
