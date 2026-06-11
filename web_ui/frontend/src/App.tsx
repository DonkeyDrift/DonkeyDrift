import React, { useEffect } from 'react';
import { HashRouter, Routes, Route, useLocation } from 'react-router-dom';
import { Layout } from './components/Layout';
import { SidePanel } from './components/SidePanel';
import { TubNavigator } from './components/TubNavigator';
import { TubEditor } from './components/TubEditor';
import { useStore } from './store/useStore';
import { getApiErrorMessage, loadTub } from './services/api';

const TrainerPage = React.lazy(() => import('./pages/TrainerPage').then((module) => ({ default: module.TrainerPage })));
const DrivePage = React.lazy(() => import('./pages/DrivePage').then((module) => ({ default: module.DrivePage })));
const CalibratePage = React.lazy(() => import('./pages/CalibratePage').then((module) => ({ default: module.CalibratePage })));
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
      return <div>Something went wrong.</div>;
    }
    return this.props.children;
  }
}

function TubManagerPage() {
  const { isLoading, error, tubPath, setTub, setLoading, setError } = useStore();
  const location = useLocation();

  useEffect(() => {
    const shouldRefreshTub = location.pathname === '/' && Boolean(tubPath);

    if (shouldRefreshTub) {
      const refreshCurrentTub = async () => {
        setLoading(true);
        try {
          const data = await loadTub(tubPath);
          setTub(
            data.path,
            data.records || [],
            data.fields || [],
            data.total_physical_records,
            data.deleted_indexes,
          );
        } catch (err: unknown) {
          setError(getApiErrorMessage(err, 'Failed to refresh tub'));
        } finally {
          setLoading(false);
        }
      };

      refreshCurrentTub();
    }
  }, [location.pathname, tubPath, setTub, setLoading, setError]);

  return (
    <>
      {error && (
        <div className="bg-red-900/50 border border-red-800 text-red-200 px-4 py-3 rounded-md mb-4">
          Error: {error}
        </div>
      )}
      
      {isLoading && (
        <div className="fixed inset-0 bg-black/50 z-[60] flex items-center justify-center">
          <div className="flex flex-col items-center gap-3">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-500" />
            <div className="text-sm text-zinc-200">Loading</div>
          </div>
        </div>
      )}

      <div className="space-y-6">
        <TubNavigator />
        <TubEditor />
      </div>
    </>
  );
}

function AppShell() {
  return (
    <ErrorBoundary>
      <SidePanel />
      <Layout>
        <React.Suspense fallback={<div className="text-sm text-zinc-400">Loading</div>}>
          <Routes>
            <Route path="/" element={<TubManagerPage />} />
            <Route path="/trainer" element={<TrainerPage />} />
            <Route path="/drive" element={<DrivePage />} />
            <Route path="/calibrate" element={<CalibratePage />} />
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
