import React from 'react';
import { AutoSyncPanel } from '../components/AutoSyncPanel';
import { CarSettingsPanel } from '../components/CarSettingsPanel';

// Car Connector = 真车设置中心：SSH 管线（连接配置/拉取 Tub/推送 Pilots/远程驾驶）已按实际使用情况移除
// （实证从未使用：连接器配置从未保存、数据流全走模拟器；后端 /connector/* 接口保留，需要时从历史恢复）。
// 自动同步 Tub 数据（#167 精简风格）：仅保留精简的自动同步开关 + 最近同步展示（AutoSyncPanel）
export const CarConnectorPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <AutoSyncPanel />
      <CarSettingsPanel />
    </div>
  );
};
