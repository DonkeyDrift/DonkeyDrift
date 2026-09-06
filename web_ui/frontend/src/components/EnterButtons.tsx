import React, { useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Code2, FlaskConical, Menu, Sparkles, SquareTerminal } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { launchDsh, launchKimiCodeWeb, launchZcodeRemote } from '@/services/api';

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
  const { pathname } = useLocation();
  const active = pathname === '/donkey';
  // Donkey 菜单（launcher :8090）改为在当前标签页内嵌显示，与 Drifter Console 一致；
  // 处于 /donkey 时按流程导航的激活态高亮蓝色（text-cyan-500）。
  return (
    <Link
      to="/donkey"
      title={t('common.enterButtons.donkeyTitle')}
      className={
        active
          ? 'flex items-center gap-1 text-xs font-medium text-cyan-500 hover:text-cyan-400 transition-colors whitespace-nowrap cursor-pointer py-2.5'
          : entryLinkCls
      }
    >
      <Menu className="w-3.5 h-3.5 shrink-0" />
      {t('common.enterButtons.donkey')}
    </Link>
  );
};

export const DrifterConsoleEntryLink: React.FC = () => {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const active = pathname === '/console';
  // Issue #234：改为在当前标签页内进入 DD 内嵌 Drifter Console 页面，不再跳新标签页；
  // 处于 /console 时按流程导航的激活态高亮蓝色（text-cyan-500）。
  return (
    <Link
      to="/console"
      title={t('common.enterButtons.drifterConsoleTitle')}
      className={
        active
          ? 'flex items-center gap-1 text-xs font-medium text-cyan-500 hover:text-cyan-400 transition-colors whitespace-nowrap cursor-pointer py-2.5'
          : entryLinkCls
      }
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

// ZCode 入口（远程控制链接，行为再变更）：单击用已存链接里的持久化 sid/hash
// 现拼一条带全新 t 时间戳的 URL（z.ai 远控页会拒绝 t 过旧的旧链接——
// "手机连接已失效"），复制到剪贴板后新标签直接打开、正常点击零弹框，
// 并后台唤醒 PC 上的 Z Code 桌面端（不在线则拉起，失败静默）。
// 无存档或存档缺 sid/hash（早期存的裸链接）时才 prompt 录入，双击重新录入。
// 远程链接由 ZCode 桌面端生成、本身是凭证，只存浏览器 localStorage，绝不入库；
export const ZCODE_REMOTE_STORAGE_KEY = 'zcodeRemoteUrl';

// 单击动作稍作延迟，等待可能到来的双击（系统双击间隔通常 ≤500ms），
// 避免双击更新时先触发一次"打开旧链接"
const ZCODE_CLICK_DELAY_MS = 300;

// 链接宽容归一化（与固件侧 zcodeRemoteNormalize 同语义）：trim + 去首尾引号
// （含「」“”‘’）；桌面端复制的链接参数可能跟在 # fragment 后——fragment 里
// 含 = 时把参数归并进 query（query 已有同名参数不覆盖）并清空 hash；
// 含 remoteControlToken 的链接原样返回；否则必须带 sid/hash（持久化设备凭证——
// 裸 /remote/v4 必然"手机连接已失效"），并把 t 刷成当前毫秒戳（远控页拒绝旧 t）
const normalizeRemoteUrl = (raw: string): string | null => {
  let u: URL;
  try {
    u = new URL(raw.trim().replace(/^["'“”‘’「」]+|["'“”‘’「」]+$/g, ''));
  } catch {
    return null;
  }
  if (u.protocol !== 'https:') return null;
  if (u.hash.length > 1) {
    let h = u.hash.slice(1);
    const q = h.indexOf('?');
    if (q >= 0) h = h.slice(q + 1);
    if (h.indexOf('=') > 0) {
      new URLSearchParams(h).forEach((v, k) => {
        if (!u.searchParams.get(k)) u.searchParams.set(k, v);
      });
    }
    u.hash = '';
  }
  if (u.searchParams.get('remoteControlToken')) return u.toString();
  if (!u.searchParams.get('sid') || !u.searchParams.get('hash')) return null;
  u.searchParams.set('t', String(Date.now()));
  return u.toString();
};

// 读取存档链接：浏览器存储不可用（隐私模式/用户禁用）时 getItem 可能直接
// 抛 SecurityError——按无存档处理走 prompt，不让点击整个失效（固件侧
// zcodeRemoteGet 同款容错）
const readStoredRemoteUrl = (): string => {
  try {
    return localStorage.getItem(ZCODE_REMOTE_STORAGE_KEY) ?? '';
  } catch {
    return '';
  }
};

// 复制到剪贴板（clipboard API + execCommand 降级），失败不阻塞跳转
const copyRemoteUrl = (url: string) => {
  const fallback = () => {
    try {
      const ta = document.createElement('textarea');
      ta.value = url;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    } catch {
      /* 复制失败不影响跳转 */
    }
  };
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(url).catch(fallback);
  } else {
    fallback();
  }
};

export const ZCodeEntryLink: React.FC = () => {
  const { t } = useTranslation();
  const clickTimer = useRef<number | null>(null);

  // 卸载时清掉未触发的单击定时器
  useEffect(
    () => () => {
      if (clickTimer.current !== null) window.clearTimeout(clickTimer.current);
    },
    [],
  );

  // 复制 + 新标签打开 + 后台唤醒桌面端（只有真正打开才向 Z Code 发请求）
  const openFresh = (url: string) => {
    copyRemoteUrl(url);
    window.open(url, '_blank', 'noopener');
    launchZcodeRemote().catch(() => {});
  };

  // 存档归一化有效就直接打开，无效（无存档/早期存的裸链接）才 prompt 录入
  const openRemote = () => {
    const saved = readStoredRemoteUrl();
    const fresh = saved ? normalizeRemoteUrl(saved) : null;
    if (!fresh) {
      promptForUrl();
      return;
    }
    openFresh(fresh);
  };

  // prompt 录入/更新链接：预填归一化后的存档（存档无效时预填空串，
  // 避免早期存的无效裸链接诱导直接回车）；输入经归一化，失败 alert
  // 且不保存；保存归一化后的值并立即按新链接打开一次。存储写入失败
  // （隐私模式/禁用）不阻塞本次打开——下次点击会再 prompt。
  const promptForUrl = () => {
    const saved = readStoredRemoteUrl();
    const input = window.prompt(
      t('common.enterButtons.zcodePrompt'),
      saved ? (normalizeRemoteUrl(saved) ?? '') : '',
    );
    if (input === null) return; // 用户取消
    const url = normalizeRemoteUrl(input);
    if (!url) {
      window.alert(t('common.enterButtons.zcodeInvalid'));
      return;
    }
    try {
      localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, url);
    } catch {
      /* 存储不可用：本次仍按手中链接打开 */
    }
    openFresh(url);
  };

  const handleClick = () => {
    if (clickTimer.current !== null) window.clearTimeout(clickTimer.current);
    clickTimer.current = window.setTimeout(() => {
      clickTimer.current = null;
      openRemote();
    }, ZCODE_CLICK_DELAY_MS);
  };

  const handleDoubleClick = () => {
    if (clickTimer.current !== null) {
      window.clearTimeout(clickTimer.current);
      clickTimer.current = null;
    }
    promptForUrl();
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      onDoubleClick={handleDoubleClick}
      title={t('common.enterButtons.zcodeTitle')}
      className={entryLinkCls}
    >
      <Code2 className="w-3.5 h-3.5 shrink-0" />
      {t('common.enterButtons.zcode')}
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
