import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { CarConnectorButton } from './CarConnectorButton';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <CarConnectorButton />
    </MemoryRouter>,
  );

describe('CarConnectorButton（Issue #406 顶栏图标入口）', () => {
  it('links to /connector and keeps the Car Connector accessible name', () => {
    renderAt('/');
    const link = screen.getByRole('link', { name: 'common.nav.carConnector' });
    expect(link).toHaveAttribute('href', '/connector');
    expect(link).toHaveAttribute('title', 'common.nav.carConnector');
    expect(link.querySelector('svg.lucide-settings')).not.toBeNull();
  });

  it('renders the icon without the Car Connector text', () => {
    renderAt('/');
    expect(screen.queryByText('common.nav.carConnector')).toBeNull();
    expect(screen.getByRole('link', { name: 'common.nav.carConnector' }).textContent).toBe('');
  });

  it('highlights the gear when on /connector', () => {
    renderAt('/connector');
    expect(screen.getByRole('link', { name: 'common.nav.carConnector' }).className).toContain('text-cyan-400');
  });

  it('does not highlight the gear on other routes', () => {
    renderAt('/drive');
    expect(screen.getByRole('link', { name: 'common.nav.carConnector' }).className).not.toContain('text-cyan-400');
  });
});
