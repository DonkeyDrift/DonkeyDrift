import React, { useEffect, useRef, useState, useCallback } from 'react';
import { VideoStream } from '../components/drive/VideoStream';
import { VirtualJoystick } from '../components/drive/VirtualJoystick';
import { ControlBars } from '../components/drive/ControlBars';
import { DriveModeSelector, DriveMode } from '../components/drive/DriveModeSelector';
import { useDriveWebsocket } from '../hooks/useDriveWebsocket';
import { useKeyboardDrive } from '../hooks/useKeyboardDrive';
import { useDriveHotkeys } from '../hooks/useDriveHotkeys';
import { ProgrammableButtons } from '../components/drive/ProgrammableButtons';
import { ParameterPanel } from '../components/drive/ParameterPanel';
import { InputSourceSelector, InputSource } from '../components/drive/InputSourceSelector';
import { useDriveStore } from '../store/useDriveStore';
import { useGamepadDrive } from '../hooks/useGamepadDrive';
import { useGyroDrive } from '../hooks/useGyroDrive';
import { Circle, CirclePlay, Wifi, WifiOff } from 'lucide-react';

export const DrivePage: React.FC = () => {
  const { connected, carState, send } = useDriveWebsocket();

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
  const [currentModel] = useState<string>('未加载');
  const [inputSource, setInputSource] = useState<InputSource>('joystick');
  const gamepadRef = useRef({ angle: 0, throttle: 0 });
  const gyroRef = useRef({ angle: 0, throttle: 0 });

  const { params, loadFromServer } = useDriveStore();

  // 页面加载时从服务端拉取参数
  useEffect(() => {
    loadFromServer();
  }, [loadFromServer]);

  useKeyboardDrive({
    enabled: inputSource === 'keyboard',
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

  // 控制节流：50Hz 发送
  const sendTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    sendTimerRef.current = setInterval(() => {
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
      setAngle(a);
      setThrottle(t);

      if (connected && (Math.abs(a) > 0.01 || Math.abs(t) > 0.01)) {
        send({ angle: a, throttle: t });
      }
    }, 20);
    return () => {
      if (sendTimerRef.current) clearInterval(sendTimerRef.current);
    };
  }, [connected, send]);

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

  const cycleMode = useCallback(() => {
    const modes: DriveMode[] = ['user', 'local_angle', 'local'];
    const idx = modes.indexOf(mode);
    handleModeChange(modes[(idx + 1) % modes.length]);
  }, [handleModeChange, mode]);

  const toggleRecording = useCallback(() => {
    const next = !recording;
    setRecording(next);
    send({ recording: next });
    if (next) {
      setRecordStartTime(Date.now());
    } else {
      setRecordStartTime(null);
    }
  }, [recording, send]);

  // 快捷键
  useDriveHotkeys({
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
      {/* 顶部工具栏 */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-zinc-200">驾驶控制台</h2>
        <div className="flex items-center gap-3">
          <InputSourceSelector
            value={inputSource}
            onChange={setInputSource}
            gamepadConnected={gamepadConnected}
            gyroAvailable={permissionState !== 'unsupported'}
          />
          <DriveModeSelector value={mode} onChange={handleModeChange} disabled={!carState.online} />
          <button
            onClick={toggleRecording}
            disabled={!carState.online}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
              ${recording
                ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
                : 'bg-zinc-800 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700'
              }
              ${!carState.online ? 'opacity-50 cursor-not-allowed' : ''}
            `}
          >
            {recording ? (
              <CirclePlay className="w-3.5 h-3.5 fill-current animate-pulse" />
            ) : (
              <Circle className="w-3.5 h-3.5" />
            )}
            {recording ? `录制中 ${formatDuration(recordDuration)}` : '开始录制'}
          </button>
          <span className="text-xs text-zinc-500">
            {connected ? 'WebSocket 已连接' : 'WebSocket 连接中...'}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* 摄像头回传区 */}
        <div className="lg:col-span-2">
          <VideoStream className="min-h-[360px]" />
        </div>

        {/* 控制区 */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 flex flex-col">
          <div className="text-sm text-zinc-400 mb-4 flex items-center justify-between">
            <span>虚拟摇杆</span>
            <span className="text-[10px] text-zinc-500">支持鼠标 / 触屏</span>
          </div>
          <div className="flex-1 flex flex-col items-center gap-4">
            <VirtualJoystick
              onChange={(a, t) => {
                joystickRef.current = { angle: a, throttle: t };
                lastInputType.current = 'joystick';
              }}
              size={220}
            />
            <ControlBars angle={angle} throttle={throttle} className="w-full max-w-[240px]" />
            <ProgrammableButtons
              className="w-full max-w-[240px]"
              onClick={(id) => send({ buttons: { [id]: true } })}
            />
            <ParameterPanel className="w-full max-w-[240px]" />
            <div className="text-[10px] text-zinc-500 text-center">
              键盘快捷键: I 前进 · K 倒车 · J 左转 · L 右转<br />
              R 切换录制 · M 切换模式
            </div>
          </div>
        </div>
      </div>

      {/* 状态卡片 */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
          <div className="text-xs text-zinc-500 mb-1">车端连接</div>
          <div className={`text-sm font-medium flex items-center gap-1 ${carState.online ? 'text-emerald-400' : 'text-red-400'}`}>
            {carState.online ? <Wifi className="w-3.5 h-3.5" /> : <WifiOff className="w-3.5 h-3.5" />}
            {carState.online ? '在线' : '离线'}
          </div>
        </div>
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
          <div className="text-xs text-zinc-500 mb-1">驾驶模式</div>
          <div className="text-sm text-zinc-300 font-medium capitalize">
            {mode === 'user' ? '人工驾驶' : mode === 'local_angle' ? 'AI 转向' : '全自动'}
          </div>
        </div>
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
          <div className="text-xs text-zinc-500 mb-1">录制状态</div>
          <div className={`text-sm font-medium ${recording ? 'text-red-400' : 'text-zinc-400'}`}>
            {recording ? `录制中 (${formatDuration(recordDuration)})` : '关闭'}
          </div>
        </div>
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
          <div className="text-xs text-zinc-500 mb-1">已录制条数</div>
          <div className="text-sm text-zinc-300 font-medium">
            {carState.numRecords}
          </div>
        </div>
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
          <div className="text-xs text-zinc-500 mb-1">当前模型</div>
          <div className="text-sm text-zinc-300 font-medium truncate" title={currentModel}>
            {currentModel}
          </div>
        </div>
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
          <div className="text-xs text-zinc-500 mb-1">连接延迟</div>
          <div className="text-sm text-zinc-300 font-medium">
            {connected ? '~20ms' : '-'}
          </div>
        </div>
      </div>
    </div>
  );
};
