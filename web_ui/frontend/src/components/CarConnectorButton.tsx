import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Settings } from 'lucide-react';
import { useTranslation } from '@/i18n';

// Car Connector（/connector）顶栏图标入口（Issue #406）：原导航行「齿轮 + Car Connector
// 文字」改为右侧控制区里的纯图标按钮。样式与旁边的静音按钮（ConsoleMuteButton）逐类
// 一致——相同尺寸/圆角/边框/悬停；激活态（位于 /connector）整框蓝化，直接复用静音键
// 激活态的语义 cyan 类（bg-cyan-500/20 border-cyan-500/60 text-cyan-400），顶栏不再
// 出现第二种硬编码蓝。浅色主题在 themes/theme-light.css 里有同款覆盖
//（以 [aria-current="page"] 为激活态标记，与静音键 [aria-pressed="true"] 对应）。
// 文字语义由 aria-label / title 保留
//（复用 common.nav.carConnector）。
export const CarConnectorButton: React.FC = () => {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const active = pathname === '/connector';
  return (
    <Link
      to="/connector"
      aria-label={t('common.nav.carConnector')}
      title={t('common.nav.carConnector')}
      aria-current={active ? 'page' : undefined}
      className={`car-connector-btn hit-44 flex items-center justify-center w-8 h-8 rounded-full border transition-colors ${
        active
          ? 'bg-cyan-500/20 border-cyan-500/60 text-cyan-400'
          : 'bg-zinc-800 border-zinc-700 text-zinc-300 hover:text-zinc-100'
      }`}
    >
      <Settings className="w-4 h-4" />
    </Link>
  );
};
