import { useEffect } from 'react';
import { TubEditor } from '../components/TubEditor';
import { TubLibrary } from '../components/TubLibrary';
import { useStore } from '../store/useStore';
import { getApiErrorMessage, loadTub } from '../services/api';
import { useTranslation } from '@/i18n';

/** Tub Manager 页面本体（TubLibrary + TubEditor），从 App.tsx 迁出（#178） */
export function TubManagerPage() {
  const { t } = useTranslation();
  const { isLoading, error, tubPath, setTub, setLoading, setError } = useStore();
  const loadedTubPath = useStore((state) => state.loadedTubPath);
  const tubRefreshToken = useStore((state) => state.tubRefreshToken);

  useEffect(() => {
    // 仅在 tub 首次加载（含刷新页面后恢复持久化 tubPath）或手动刷新时全量拉取；
    // 顶部导航来回切换不再重新下载整个 tub，避免每次切换都全量重拉导致卡顿（#135）
    if (!tubPath || tubPath === loadedTubPath) return;

    let cancelled = false;
    const loadCurrentTub = async () => {
      setLoading(true);
      try {
        const data = await loadTub(tubPath);
        if (cancelled) return;
        setTub(
          data.path,
          data.records || [],
          data.fields || [],
          data.total_physical_records,
          data.deleted_indexes,
        );
      } catch (err: unknown) {
        if (!cancelled) {
          setError(getApiErrorMessage(err, t('common.app.failedToRefreshTub')));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    loadCurrentTub();
    return () => {
      cancelled = true;
    };
  }, [tubPath, loadedTubPath, tubRefreshToken, setTub, setLoading, setError, t]);

  return (
    <>
      {error && (
        <div className="bg-red-900/50 border border-red-800 text-red-200 px-4 py-3 rounded-md mb-4">
          {t('common.app.errorPrefix', { message: error })}
        </div>
      )}

      {isLoading && (
        <div className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center">
          <div className="flex flex-col items-center gap-3">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-500" />
            <div className="text-sm text-zinc-200">{t('common.loading')}</div>
          </div>
        </div>
      )}

      <div className="space-y-6">
        <TubLibrary />
        <TubEditor />
      </div>
    </>
  );
}
