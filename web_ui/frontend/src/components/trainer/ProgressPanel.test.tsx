import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { LanguageProvider } from '@/i18n';
import { ProgressPanel } from './ProgressPanel';
import { TrainingJob } from '../../store/useStore';

const renderPanel = (job: TrainingJob | null) =>
  render(
    <LanguageProvider>
      <ProgressPanel job={job} />
    </LanguageProvider>,
  );

describe('ProgressPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('updates duration display as ticker ticks', () => {
    const now = Date.now();
    const job: TrainingJob = {
      id: 'test-1',
      mode: 'mypc',
      status: 'running',
      progress: {
        currentEpoch: 0,
        totalEpochs: 10,
        currentStep: 0,
        totalSteps: 100,
        loss: null,
        globalPercent: 0,
      },
      logs: [],
      startedAt: new Date(now - 10000).toISOString(),
    };

    renderPanel(job);

    // flush useEffect so the interval timer is registered
    act(() => {
      vi.advanceTimersByTime(0);
    });

    // Initial duration should be 10 seconds
    expect(screen.getByText('0m 10s')).toBeInTheDocument();

    // Advance 3 seconds — ticker fires, duration should update
    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(screen.getByText('0m 13s')).toBeInTheDocument();
  });

  it('shows initializing pulse when running with zero totalSteps', () => {
    const job: TrainingJob = {
      id: 'test-2',
      mode: 'mypc',
      status: 'running',
      progress: {
        currentEpoch: 0,
        totalEpochs: 10,
        currentStep: 0,
        totalSteps: 0,
        loss: null,
        globalPercent: 0,
      },
      logs: [],
      startedAt: new Date().toISOString(),
    };

    renderPanel(job);

    expect(screen.getByText(/Initializing training environment/)).toBeInTheDocument();
  });
});
