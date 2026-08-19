import React from 'react';
import { Menu } from 'lucide-react';
import { getDonkeyUrl } from '../services/api';
import { useTranslation } from '@/i18n';

/** Donkey 菜单内嵌页：把 launcher(:8090) 的 Donkey 菜单页以 iframe 嵌入当前
 *  标签页，点击顶栏 Donkey 入口不再新开标签页，与 Drifter Console 的
 *  /console 内嵌路由体验一致。launcher 页面未设置 X-Frame-Options/CSP，
 *  允许被跨端口 iframe 嵌入。 */
export const DonkeyMenuPage: React.FC = () => {
  const { t } = useTranslation();
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm font-medium text-zinc-200">
        <Menu className="w-4 h-4 text-cyan-400" />
        {t('common.enterButtons.donkey')}
      </div>
      <iframe
        src={getDonkeyUrl()}
        title={t('common.enterButtons.donkeyTitle')}
        className="w-full h-[calc(100vh-10rem)] min-h-[520px] rounded-lg border border-zinc-800 bg-zinc-950"
      />
    </div>
  );
};
