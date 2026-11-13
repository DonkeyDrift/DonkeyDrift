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
 *  占位行；单独打开 Donkey（:8090）时无此参数，仍保留完整可点击入口。
 *
 *  iframe 以 no-referrer 加载：launcher 回环鉴权（auth.py，2026-10-12）
 *  要求 Origin 干净（无 Origin/Referer 视为本机直连放行），而浏览器
 *  iframe 跨端口导航默认携带 Referer，DD(:5188) → launcher(:8090) 永远
 *  对不上，菜单会被 401 令牌页顶替；no-referrer 对齐本机直连信任级，
 *  不削弱 launcher 对恶意站点的 CSRF/DNS-rebinding 防线。
 *
 *  高度：铺满 DD 顶栏以下的可视区，扣减 Layout 经 ResizeObserver 发布的
 *  动态 --header-h（桌面单行 57px、移动端两行约 101px），不硬编码 3.5rem；
 *  支持 dvh 的浏览器用 100dvh 动态视口，避免移动端 100vh 被浏览器
 *  工具栏裁切导致外层出现双滚动。 */
export const DonkeyMenuPage: React.FC = () => {
  const { t, lang } = useTranslation();
  return (
    <div className="h-[calc(100vh-var(--header-h))] supports-[height:100dvh]:h-[calc(100dvh-var(--header-h))]">
      <iframe
        src={`${getDonkeyUrl()}?embedded=1&lang=${lang}`}
        title={t('common.enterButtons.donkeyTitle')}
        referrerPolicy="no-referrer"
        className="h-full w-full border-0 bg-zinc-950"
      />
    </div>
  );
};
