import React from 'react';
import { getDonkeyUrl } from '../services/api';
import { useTranslation } from '@/i18n';

/** Donkey 菜单内嵌页：把 launcher(:8090) 的 Donkey 菜单页以 iframe 嵌入当前
 *  标签页，点击顶栏 Donkey 入口不再新开标签页，与 Drifter Console 的
 *  /console 内嵌路由体验一致。launcher 页面未设置 X-Frame-Options/CSP，
 *  允许被跨端口 iframe 嵌入。页面铺满顶栏以下的全部可视区域，不再叠加
 *  DD 侧标题栏，用户看到的是与真实 Donkey 启动页（8090）一致的完整界面。 */
export const DonkeyMenuPage: React.FC = () => {
  const { t } = useTranslation();
  return (
    <div className="h-[calc(100vh-3.5rem)]">
      <iframe
        src={getDonkeyUrl()}
        title={t('common.enterButtons.donkeyTitle')}
        className="h-full w-full border-0 bg-zinc-950"
      />
    </div>
  );
};
