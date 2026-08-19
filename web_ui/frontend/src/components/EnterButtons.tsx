import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { FlaskConical, Menu, Sparkles, SquareTerminal } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { launchDsh, launchKimiCodeWeb } from '@/services/api';

// 启动 launcher 侧服务（kimi / dsh）并在新标签页打开目标 URL：
// 点击同步上下文先开空白页拿句柄，等异步拿到 URL 再 window.open 会被弹窗拦截
const useLauncherEntry = (
  launch: (signal: AbortSignal) => Promise<{ status: string; url?: string; error?: string }>,
  opts: { startingKey: string; failedKey: string; networkKey: string; timeoutMs: number },
) => {
  const { t } = useTranslation();
  const [launching, setLaunching] = useState(false);
  const enter = async () => {
    if (launching) return;
    const win = window.open('about:blank', '_blank');
    setLaunching(true);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), opts.timeoutMs);
    try {
      const data = await launch(controller.signal);
      if (data.status === 'ok' && data.url) {
        if (win) {
          win.location.href = data.url;
        } else {
          window.open(data.url, '_blank', 'noopener,noreferrer');
        }
      } else {
        win?.close();
        alert(t(opts.failedKey, { message: data.error || t('common.unknownError') }));
      }
    } catch {
      win?.close();
      alert(t(opts.failedKey, { message: t(opts.networkKey) }));
    } finally {
      clearTimeout(timer);
      setLaunching(false);
    }
  };
  return { launching, enter };
};

// 高级入口的导航链接样式（Issue #175）：融入导航行、去掉胶囊外壳，但用
// 更小字号 + 更淡颜色 + 图标做弱化处理，一眼可辨为不常用的高级选项；
// 外链入口不做路由激活态；Car Connector 复用同一样式（见 Layout.tsx）。
export const entryLinkCls =
  'flex items-center gap-1 text-xs font-medium text-zinc-500 hover:text-zinc-300 transition-colors whitespace-nowrap cursor-pointer py-2.5';

export const DonkeyEntryLink: React.FC = () => {
  const { t } = useTranslation();
  // Donkey 菜单（launcher :8090）改为在当前标签页内嵌显示，与 Drifter Console 一致。
  return (
    <Link
      to="/donkey"
      title={t('common.enterButtons.donkeyTitle')}
      className={entryLinkCls}
    >
      <Menu className="w-3.5 h-3.5 shrink-0" />
      {t('common.enterButtons.donkey')}
    </Link>
  );
};

export const DrifterConsoleEntryLink: React.FC = () => {
  const { t } = useTranslation();
  // Issue #234：改为在当前标签页内进入 DD 内嵌 Drifter Console 页面，不再跳新标签页。
  return (
    <Link
      to="/console"
      title={t('common.enterButtons.drifterConsoleTitle')}
      className={entryLinkCls}
    >
      <SquareTerminal className="w-3.5 h-3.5 shrink-0" />
      {t('common.enterButtons.drifterConsole')}
    </Link>
  );
};

export const KimiCodeWebEntryLink: React.FC = () => {
  const { t } = useTranslation();
  // kimi 冷启动可达数十秒，launcher 端整体超时 120s，客户端超时留足余量
  const { launching, enter } = useLauncherEntry(launchKimiCodeWeb, {
    startingKey: 'common.enterButtons.kimiCodeWebStarting',
    failedKey: 'common.enterButtons.kimiCodeWebFailed',
    networkKey: 'common.enterButtons.kimiCodeWebNetworkError',
    timeoutMs: 125000,
  });
  return (
    <button
      type="button"
      onClick={enter}
      disabled={launching}
      title={t('common.enterButtons.kimiCodeWebTitle')}
      className={launching ? `${entryLinkCls} opacity-60 cursor-wait` : entryLinkCls}
    >
      <Sparkles className="w-3.5 h-3.5 shrink-0" />
      {launching ? t('common.enterButtons.kimiCodeWebStarting') : t('common.enterButtons.kimiCodeWeb')}
    </button>
  );
};

export const DshEntryLink: React.FC = () => {
  const { t } = useTranslation();
  // dsh 冷启动数秒、launcher 端整体超时 60s
  const { launching, enter } = useLauncherEntry(launchDsh, {
    startingKey: 'common.enterButtons.dshStarting',
    failedKey: 'common.enterButtons.dshFailed',
    networkKey: 'common.enterButtons.dshNetworkError',
    timeoutMs: 65000,
  });
  return (
    <button
      type="button"
      onClick={enter}
      disabled={launching}
      title={t('common.enterButtons.dshTitle')}
      className={launching ? `${entryLinkCls} opacity-60 cursor-wait` : entryLinkCls}
    >
      <FlaskConical className="w-3.5 h-3.5 shrink-0" />
      {launching ? t('common.enterButtons.dshStarting') : t('common.enterButtons.dsh')}
    </button>
  );
};
