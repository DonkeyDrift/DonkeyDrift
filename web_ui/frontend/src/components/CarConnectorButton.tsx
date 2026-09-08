import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Settings } from 'lucide-react';
import { useTranslation } from '@/i18n';

// Car Connector（/connector）顶栏图标入口（Issue #406）：原导航行「齿轮 + Car Connector
// 文字」改为右侧控制区里的纯图标按钮。样式与旁边的静音按钮（ConsoleMuteButton）逐类
// 一致——相同尺寸/圆角/边框/悬停；激活态（位于 /connector）整框蓝化：浅蓝底 + 蓝边框
// + 蓝图标（bg-[#5cc8ff]/10 border-[#5cc8ff]/60 text-[#5cc8ff]），与静音键的激活态
// 同款，而不是只把图标染蓝、框仍是灰色。文字语义由 aria-label / title 保留
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
      className={`car-connector-btn flex items-center justify-center w-8 h-8 rounded-full border transition-colors ${
        active
          ? 'bg-[#5cc8ff]/10 border-[#5cc8ff]/60 text-[#5cc8ff]'
          : 'bg-zinc-800 border-zinc-700 text-zinc-300 hover:text-zinc-100'
      }`}
    >
      <Settings className="w-4 h-4" />
    </Link>
  );
};
