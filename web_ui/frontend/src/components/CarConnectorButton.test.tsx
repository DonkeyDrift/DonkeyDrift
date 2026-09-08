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

  it('highlights the whole frame (bg + border + icon) in cyan when on /connector', () => {
    renderAt('/connector');
    const link = screen.getByRole('link', { name: 'common.nav.carConnector' });
    expect(link.className).toContain('bg-[#5cc8ff]/10');
    expect(link.className).toContain('border-[#5cc8ff]/60');
    expect(link.className).toContain('text-[#5cc8ff]');
    expect(link).toHaveAttribute('aria-current', 'page');
  });

  it('uses the neutral zinc frame (same as mute/theme/language) on other routes', () => {
    renderAt('/drive');
    const link = screen.getByRole('link', { name: 'common.nav.carConnector' });
    expect(link.className).not.toContain('border-[#5cc8ff]/60');
    expect(link.className).toContain('bg-zinc-800');
    expect(link.className).toContain('border-zinc-700');
    expect(link).not.toHaveAttribute('aria-current');
  });
});
