import React, { useEffect } from 'react';
import { Layout } from './components/Layout';
import { SidePanel } from './components/SidePanel';
import { TubNavigator } from './components/TubNavigator';
import { TubChart } from './components/TubChart';
import { DataCleaner } from './components/DataCleaner';
import { StatusBar } from './components/StatusBar';
import { useStore } from './store/useStore';

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

function App() {
  const { isLoading, error } = useStore();

  useEffect(() => {
    const root = document.getElementById('root');
    if (root && root.children.length === 0) {
      console.error('App failed to render');
    }
  }, []);

  return (
    <ErrorBoundary>
      <SidePanel />
      <Layout>
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
          <TubChart />
          <DataCleaner />
        </div>

        <StatusBar />
      </Layout>
    </ErrorBoundary>
  );
}

export default App;
