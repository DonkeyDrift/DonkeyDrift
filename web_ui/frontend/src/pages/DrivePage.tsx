import React from 'react';

export const DrivePage: React.FC = () => {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-zinc-200">驾驶控制台</h2>
        <span className="text-xs text-zinc-500">M1 骨架版本 - 功能开发中</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* 摄像头回传区 - 占位 */}
        <div className="lg:col-span-2 bg-zinc-900 border border-zinc-800 rounded-lg p-4 min-h-[360px] flex items-center justify-center">
          <div className="text-center text-zinc-600">
            <div className="text-sm mb-1">摄像头回传</div>
            <div className="text-xs">M2 版本实现</div>
          </div>
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

      {/* 状态区 - 占位 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: '连接状态', value: '未连接' },
          { label: '驾驶模式', value: 'User' },
          { label: '录制状态', value: '关闭' },
          { label: '已录制条数', value: '0' },
        ].map((item) => (
          <div key={item.label} className="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
            <div className="text-xs text-zinc-500 mb-1">{item.label}</div>
            <div className="text-sm text-zinc-300 font-medium">{item.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
};
