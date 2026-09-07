import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Settings } from 'lucide-react';
import { useTranslation } from '@/i18n';

// Car Connector（/connector）顶栏图标入口（Issue #406）：原导航行「齿轮 + Car Connector
// 文字」改为右侧控制区里的纯图标圆形按钮，尺寸/间距/悬停样式与静音、主题、语言按钮
// 一致；文字语义由 aria-label / title 保留（复用 common.nav.carConnector）。
// 当前位于 /connector 时图标高亮（text-cyan-400），与原导航行激活态一致。
export const CarConnectorButton: React.FC = () => {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const active = pathname === '/connector';
  return (
    <Link
      to="/connector"
      aria-label={t('common.nav.carConnector')}
      title={t('common.nav.carConnector')}
      className={`car-connector-btn flex items-center justify-center w-8 h-8 rounded-full bg-zinc-800 border border-zinc-700 transition-colors ${
        active ? 'text-cyan-400' : 'text-zinc-300 hover:text-zinc-100'
      }`}
    >
      <Settings className="w-4 h-4" />
    </Link>
  );
};
