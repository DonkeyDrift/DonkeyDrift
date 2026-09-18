import React, { useEffect, useState } from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { useTranslation } from '@/i18n';
import {
  dismissApiError,
  getApiHealth,
  retryApiRequests,
  subscribeApiHealth,
  type ApiHealthState,
} from '@/lib/apiHealth';

/**
 * 统一异步状态提示（apple 象限专用，最小可用版）：
 * - 首屏数据尚未回来时给一条骨架条（骨架本身遵守 prefers-reduced-motion，
 *   见 apple-deep.css 第 8/11 节：reduce 下动画时长收敛到 0.01ms）；
 * - 任一请求失败时给一条可关闭 + 可重试的错误条。
 *
 * 只做「提示」，不动数据流：重试 = 清标记 + 重新载入当前页（不重放请求、
 * 不臆造数据），错误文案为本地化固定文案，不回显后端原文。
 */
export const ApiStatusBar: React.FC = () => {
  const { t } = useTranslation();
  const [health, setHealth] = useState<ApiHealthState>(getApiHealth);

  useEffect(() => {
    setHealth(getApiHealth());
    return subscribeApiHealth(setHealth);
  }, []);

  if (health.lastErrorAt > 0) {
    return (
      <div
        role="alert"
        data-testid="api-error-bar"
        className="dd-errorbar flex items-center gap-2 rounded-md px-3 py-2 text-sm"
      >
        <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span className="flex-1">{t('common.dataState.error')}</span>
        <button
          type="button"
          onClick={retryApiRequests}
          className="inline-flex shrink-0 items-center gap-1 rounded-md border border-current px-2 py-1 text-xs font-medium"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
          {t('common.dataState.retry')}
        </button>
        <button
          type="button"
          onClick={dismissApiError}
          aria-label={t('common.close')}
          className="shrink-0 text-xs"
        >
          ✕
        </button>
      </div>
    );
  }

  if (health.pending > 0 && !health.sawSuccess) {
    return (
      <div data-testid="api-skeleton" aria-busy="true" className="space-y-2">
        <span className="sr-only">{t('common.loading')}</span>
        <div className="dd-skeleton h-4 w-1/3" />
        <div className="dd-skeleton h-4 w-2/3" />
      </div>
    );
  }

  return null;
};
