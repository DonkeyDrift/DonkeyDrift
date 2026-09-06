import React, { useEffect, useRef } from 'react';
import { Satellite } from 'lucide-react';
import { useTranslation } from '@/i18n';
import { entryLinkCls } from './EnterButtons';

// ZCode 远程控制入口（与 Firmware Web Console 保持一致的统一交互规格）：
// 远程链接由 ZCode 桌面端生成、本身是凭证，只存浏览器 localStorage，绝不写入代码或入库；
// 单击打开（无存档则先 prompt 录入），双击重新录入更新链接。
export const ZCODE_REMOTE_STORAGE_KEY = 'zcodeRemoteUrl';

// 单击动作稍作延迟，等待可能到来的双击（系统双击间隔通常 ≤500ms），
// 避免双击更新时先触发一次"打开旧链接"
const CLICK_DELAY_MS = 300;

export const ZcodeRemoteLink: React.FC = () => {
  const { t } = useTranslation();
  const clickTimer = useRef<number | null>(null);

  // 卸载时清掉未触发的单击定时器
  useEffect(
    () => () => {
      if (clickTimer.current !== null) window.clearTimeout(clickTimer.current);
    },
    [],
  );

  // prompt 录入/更新链接：仅接受 https:// 开头，校验失败 alert 且不保存
  const promptForUrl = () => {
    const input = window.prompt(t('common.zcodeRemote.prompt'));
    if (input === null) return; // 用户取消
    const url = input.trim();
    if (!url.startsWith('https://')) {
      window.alert(t('common.zcodeRemote.invalid'));
      return;
    }
    localStorage.setItem(ZCODE_REMOTE_STORAGE_KEY, url);
    window.open(url, '_blank', 'noopener');
  };

  const openRemote = () => {
    const saved = localStorage.getItem(ZCODE_REMOTE_STORAGE_KEY);
    if (saved) {
      window.open(saved, '_blank', 'noopener');
    } else {
      promptForUrl();
    }
  };

  const handleClick = () => {
    if (clickTimer.current !== null) window.clearTimeout(clickTimer.current);
    clickTimer.current = window.setTimeout(() => {
      clickTimer.current = null;
      openRemote();
    }, CLICK_DELAY_MS);
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
      title={t('common.zcodeRemote.title')}
      className={entryLinkCls}
    >
      <Satellite className="w-3.5 h-3.5 shrink-0" />
      {t('common.zcodeRemote.label')}
    </button>
  );
};
