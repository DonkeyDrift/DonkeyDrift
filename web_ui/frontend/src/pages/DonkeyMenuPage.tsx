import React from 'react';
import { getDonkeyUrl } from '../services/api';
import { useTranslation } from '@/i18n';

/** Donkey 菜单内嵌页：把 launcher(:8090) 的 Donkey 菜单页以 iframe 嵌入当前
 *  标签页，点击顶栏 Donkey 入口不再新开标签页，与 Drifter Console 的
 *  /console 内嵌路由体验一致。launcher 页面未设置 X-Frame-Options/CSP，
 *  允许被跨端口 iframe 嵌入。页面铺满顶栏以下的全部可视区域，不再叠加
 *  DD 侧标题栏，用户看到的是与真实 Donkey 启动页（8090）一致的完整界面。
 *
 *  语言同步：launcher 与 DD 跨源（:8090 vs :8000），localStorage 各自独立，
 *  因此把 DD 当前语言经 iframe src 的 `?lang=` 参数传入；DD 切换语言时
 *  src 变化触发 iframe 重载，内嵌 Donkey 菜单随之切换，不会出现“DD 已是
 *  英文、Donkey 菜单仍是中文”的错位。
 *
 *  `?embedded=1` 标记当前为 DD 内嵌模式：launcher 据此把与 DD 顶栏重复的
 *  7/11/12（Drifter Console / Kimi Code Web / DeepSeek Harness）渲染为置灰
 *  占位行；单独打开 Donkey（:8090）时无此参数，仍保留完整可点击入口。 */
export const DonkeyMenuPage: React.FC = () => {
  const { t, lang } = useTranslation();
  return (
    <div className="h-[calc(100vh-3.5rem)]">
      <iframe
        src={`${getDonkeyUrl()}?embedded=1&lang=${lang}`}
        title={t('common.enterButtons.donkeyTitle')}
        className="h-full w-full border-0 bg-zinc-950"
      />
    </div>
  );
};
