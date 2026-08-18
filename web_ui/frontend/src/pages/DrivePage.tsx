import React, { useEffect, useRef, useState, useCallback } from 'react';
import { VideoStream } from '../components/drive/VideoStream';
import { TelemetryChart } from '../components/drive/TelemetryChart';
import { VirtualJoystick } from '../components/drive/VirtualJoystick';
import { ControlBars } from '../components/drive/ControlBars';
import { VerticalThrottleBar } from '../components/drive/VerticalThrottleBar';
import { DriveModeSelector, DriveMode } from '../components/drive/DriveModeSelector';
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
import { Circle, ChevronDown, ChevronUp } from 'lucide-react';

type DrivePageProps = {
  /** 该 section 是否在视口内：滚走后停用全局快捷键/键盘驾驶，避免误触（#178） */
  active?: boolean;
};

export const DrivePage: React.FC<DrivePageProps> = ({ active = true }) => {
  const { t } = useTranslation();
  const [webRtcSignal, setWebRtcSignal] = useState<WebRtcSignal | null>(null);
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  const clientIdRef = useRef(createDriveClientId());
  const { connected, carState, send } = useDriveWebsocket({
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
  const [joystickOpen, setJoystickOpen] = useState(true);
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
    enabled: inputSource === 'gamepad',
    onChange: (a, t) => {
      gamepadRef.current = { angle: a, throttle: t };
      lastInputType.current = 'gamepad';
    },
  });

  const { permissionState, requestPermission } = useGyroDrive({
    enabled: inputSource === 'gyro',
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

  // UI 显示无需驱动控制发送，按较低频率同步即可。
  useEffect(() => {
    const timer = setInterval(() => {
      const control = getCurrentControl();
      setAngle(control.angle);
      setThrottle(control.throttle);
    }, 50);
    return () => clearInterval(timer);
  }, [getCurrentControl]);

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

  const handleModeChange = useCallback((newMode: DriveMode) => {
    setMode(newMode);
    send({ drive_mode: newMode });
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
      {/* 顶部工具栏：窄屏允许换行，避免一排溢出（页内标题已上移到 section 头 #178） */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 lg:gap-3">
          <DriveModeSelector value={mode} onChange={handleModeChange} disabled={!carState.online} />
          <ModelSelector
            value={currentModel}
            options={models}
            onChange={handleModelChange}
            disabled={!carState.online || modelsLoading}
          />
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
          <span className="text-xs text-zinc-500 whitespace-nowrap">
            {t('drive.recordedCount', { count: carState.numRecords })}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* 摄像头回传区 */}
        <div className="lg:col-span-2">
          <VideoStream className="w-full" incomingSignal={webRtcSignal} clientId={clientIdRef.current} />
          {/* 固件模式 / Park 状态徽标（来自 ESP32 M<m>:P<p> 帧遥测） */}
          {(telemetry?.rc_mode !== undefined || telemetry?.rc_park !== undefined) && (
            <div className="mt-2 flex items-center gap-2 text-xs">
              {telemetry?.rc_mode !== undefined && (
                <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-400" data-rc-mode={telemetry.rc_mode}>
                  {t('drive.firmwareMode', {
                    mode: [t('drive.modeUser'), t('drive.modeSemiAuto'), t('drive.modeFullAuto')][telemetry.rc_mode]
                      ?? t('drive.unknownMode', { code: telemetry.rc_mode }),
                  })}
                </span>
              )}
              {telemetry?.rc_park === 1 && (
                <span className="px-2 py-0.5 rounded bg-red-500/20 text-red-400 font-medium">
                  {t('drive.parkLocked')}
                </span>
              )}
            </div>
          )}
          <TelemetryChart telemetry={telemetry} className="mt-4" />
        </div>

        {/* 控制区 */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 flex flex-col self-start">
          {/* 标题栏：虚拟摇杆折叠开关（展开时右显输入源选择，折叠后仅剩标题一行） */}
          <div
            className={`text-sm text-zinc-400 flex items-center justify-between gap-2 ${
              joystickOpen ? 'mb-4' : 'mb-0'
            }`}
          >
            <button
              onClick={() => setJoystickOpen(!joystickOpen)}
              className="flex items-center gap-1 hover:text-zinc-200 transition-colors"
              title={joystickOpen ? t('drive.collapseJoystick') : t('drive.expandJoystick')}
            >
              <span className="font-medium">{t('drive.virtualJoystick')}</span>
              {joystickOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>
            {joystickOpen && (
              <InputSourceSelector
                value={inputSource}
                onChange={setInputSource}
                gamepadConnected={gamepadConnected}
                gyroAvailable={permissionState !== 'unsupported'}
              />
            )}
          </div>
          {joystickOpen && (
          <div className="flex-1 flex flex-col items-center gap-4">
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
          )}
        </div>
      </div>

    </div>
  );
};
