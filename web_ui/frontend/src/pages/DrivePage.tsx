import React from 'react';
import { VideoStream } from '../components/drive/VideoStream';
import { useDriveWebsocket } from '../hooks/useDriveWebsocket';

export const DrivePage: React.FC = () => {
  const { connected, carState } = useDriveWebsocket();

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-zinc-200">驾驶控制台</h2>
        <span className="text-xs text-zinc-500">
          {connected ? 'WebSocket 已连接' : 'WebSocket 连接中...'}
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* 摄像头回传区 */}
        <div className="lg:col-span-2">
          <VideoStream className="min-h-[360px]" />
        </div>

        {/* 控制区 - 占位 */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 min-h-[360px] flex flex-col">
          <div className="text-sm text-zinc-400 mb-4">虚拟摇杆</div>
          <div className="flex-1 flex items-center justify-center text-zinc-600">
            <div className="text-center">
              <div className="text-sm mb-1">控制区</div>
              <div className="text-xs">M3 版本实现</div>
            </div>
          </div>
        </div>
      </div>

      {/* 状态卡片 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
          <div className="text-xs text-zinc-500 mb-1">车端连接</div>
          <div className={`text-sm font-medium ${carState.online ? 'text-emerald-400' : 'text-red-400'}`}>
            {carState.online ? '在线' : '离线'}
          </div>
        </div>
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
          <div className="text-xs text-zinc-500 mb-1">驾驶模式</div>
          <div className="text-sm text-zinc-300 font-medium capitalize">
            {carState.driveMode}
          </div>
        </div>
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
          <div className="text-xs text-zinc-500 mb-1">录制状态</div>
          <div className={`text-sm font-medium ${carState.recording ? 'text-cyan-400' : 'text-zinc-400'}`}>
            {carState.recording ? '录制中' : '关闭'}
          </div>
        </div>
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
          <div className="text-xs text-zinc-500 mb-1">已录制条数</div>
          <div className="text-sm text-zinc-300 font-medium">
            {carState.numRecords}
          </div>
        </div>
      </div>
    </div>
  );
};
