import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { VersionBadge } from './VersionBadge';

vi.mock('@/services/api', () => ({
  getVersion: vi.fn(),
}));

const { getVersion } = await import('@/services/api');

describe('VersionBadge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the version with a v prefix', async () => {
    vi.mocked(getVersion).mockResolvedValue('0.1.2');
    render(<VersionBadge />);
    await waitFor(() => {
      expect(screen.getByText('v0.1.2')).toBeInTheDocument();
    });
  });

  it('renders nothing while loading', () => {
    vi.mocked(getVersion).mockReturnValue(new Promise(() => {}));
    const { container } = render(<VersionBadge />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing on error', async () => {
    vi.mocked(getVersion).mockRejectedValue(new Error('network'));
    const { container } = render(<VersionBadge />);
    await waitFor(() => {
      expect(getVersion).toHaveBeenCalled();
    });
    expect(container).toBeEmptyDOMElement();
  });
});
