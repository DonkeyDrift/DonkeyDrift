import React, { useEffect } from 'react';
import { HashRouter, Routes, Route, useLocation } from 'react-router-dom';
import { Layout } from './components/Layout';
import { SidePanel } from './components/SidePanel';
import { TubEditor } from './components/TubEditor';
import { TubLibrary } from './components/TubLibrary';
import { useStore } from './store/useStore';
import { getApiErrorMessage, loadTub } from './services/api';
import { useTranslation, t as translate } from '@/i18n';

const TrainerPage = React.lazy(() => import('./pages/TrainerPage').then((module) => ({ default: module.TrainerPage })));
const DrivePage = React.lazy(() => import('./pages/DrivePage').then((module) => ({ default: module.DrivePage })));
const PilotArenaPage = React.lazy(() => import('./pages/PilotArenaPage').then((module) => ({ default: module.PilotArenaPage })));
const CarConnectorPage = React.lazy(() => import('./pages/CarConnectorPage').then((module) => ({ default: module.CarConnectorPage })));

type ErrorBoundaryProps = {
  children?: React.ReactNode;
};

type ErrorBoundaryState = {
  hasError: boolean;
};

class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = {
    hasError: false,
  };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return <div>{translate('common.app.somethingWentWrong')}</div>;
    }
    return this.props.children;
  }
}

function TubManagerPage() {
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

/**
 * 常驻保活的 Tub Manager 视图：切走时仅隐藏（display:none）不卸载，
 * 切回时零重挂载成本。TubEditor 图表与 TubLibrary 会话列表都保持原状态，
 * 顶部导航来回切换不再卡顿（#135 三轮）。
 */
function KeepAliveTubManager() {
  const location = useLocation();
  const active = location.pathname === '/';
  return (
    <div data-tub-manager hidden={!active} aria-hidden={!active} className={active ? 'block' : 'hidden'}>
      <TubManagerPage />
    </div>
  );
}

/** 空闲时预取懒加载页面 chunk，首次点击导航也不必现场下载+解析 */
function useIdlePrefetch() {
  useEffect(() => {
    let cancelled = false;
    const prefetch = () => {
      if (cancelled) return;
      void import('./pages/TrainerPage');
      void import('./pages/DrivePage');
      void import('./pages/PilotArenaPage');
      void import('./pages/CarConnectorPage');
    };
    if ('requestIdleCallback' in window) {
      const idle = window as Window & {
        requestIdleCallback: (cb: () => void, opts?: { timeout: number }) => number;
        cancelIdleCallback: (id: number) => void;
      };
      const id = idle.requestIdleCallback(prefetch, { timeout: 3000 });
      return () => {
        cancelled = true;
        idle.cancelIdleCallback(id);
      };
    }
    const timer = globalThis.setTimeout(prefetch, 2000);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);
}

function AppShell() {
  const { t } = useTranslation();
  useIdlePrefetch();
  return (
    <ErrorBoundary>
      <SidePanel />
      <Layout>
        {/* Tub Manager 常驻保活：任何路由下都保持挂载，仅本路由可见 */}
        <KeepAliveTubManager />
        <React.Suspense fallback={<div className="text-sm text-zinc-400">{t('common.loading')}</div>}>
          <Routes>
            <Route path="/" element={null} />
            <Route path="/trainer" element={<TrainerPage />} />
            <Route path="/drive" element={<DrivePage />} />
            <Route path="/pilot" element={<PilotArenaPage />} />
            <Route path="/connector" element={<CarConnectorPage />} />
          </Routes>
        </React.Suspense>
      </Layout>
    </ErrorBoundary>
  );
}

function App() {
  useEffect(() => {
    const root = document.getElementById('root');
    if (root && root.children.length === 0) {
      console.error('App failed to render');
    }
  }, []);

  return (
    <HashRouter>
      <AppShell />
    </HashRouter>
  );
}

export default App;
