import React from 'react';
import { CarSettingsPanel } from '../components/CarSettingsPanel';

// Car Connector = 真车设置中心：SSH 管线（连接配置/拉取 Tub/推送 Pilots/远程驾驶）已按实际使用情况移除
// （实证从未使用：连接器配置从未保存、数据流全走模拟器；后端 /connector/* 接口保留，需要时从历史恢复）
export const CarConnectorPage: React.FC = () => {
  return (
    <div className="space-y-6">
      <CarSettingsPanel />
    </div>
  );
};
