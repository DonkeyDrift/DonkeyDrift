import React, { useEffect } from 'react';
import { HashRouter, Routes, Route } from 'react-router-dom';
import { Layout } from './components/Layout';
import { SidePanel } from './components/SidePanel';
import { t as translate } from '@/i18n';

const FlowPage = React.lazy(() => import('./pages/FlowPage').then((module) => ({ default: module.FlowPage })));
const CarConnectorPage = React.lazy(() => import('./pages/CarConnectorPage').then((module) => ({ default: module.CarConnectorPage })));
const DrifterConsolePage = React.lazy(() => import('./pages/DrifterConsolePage').then((module) => ({ default: module.DrifterConsolePage })));
const DonkeyMenuPage = React.lazy(() => import('./pages/DonkeyMenuPage').then((module) => ({ default: module.DonkeyMenuPage })));

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

/** 空闲时预取懒加载页面 chunk，首次点击导航也不必现场下载+解析 */
function useIdlePrefetch() {
  useEffect(() => {
    let cancelled = false;
    const prefetch = () => {
      if (cancelled) return;
      void import('./pages/FlowPage');
      void import('./pages/CarConnectorPage');
      void import('./pages/DrifterConsolePage');
      void import('./pages/DonkeyMenuPage');
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

function PageLoading() {
  return <div className="text-sm text-zinc-400">{translate('common.loading')}</div>;
}

function AppShell() {
  useIdlePrefetch();
  return (
    <ErrorBoundary>
      <SidePanel />
      <Layout>
        <React.Suspense fallback={<PageLoading />}>
          <Routes>
            {/* 统一流程大页面（#178）：Drive/TM/Trainer/PA 同页纵向滚动，hash 深链定位。
                四个 path 共用同一条兜底路由，导航切换只改 pathname 不重挂载 FlowPage，
                保住 #135 的常驻保活效果；CC 保持独立路由。 */}
            <Route path="/connector" element={<CarConnectorPage />} />
            <Route path="/console" element={<DrifterConsolePage />} />
            <Route path="/donkey" element={<DonkeyMenuPage />} />
            <Route path="*" element={<FlowPage />} />
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
