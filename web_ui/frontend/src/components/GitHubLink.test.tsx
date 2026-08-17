import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { GitHubLink } from './GitHubLink';

describe('GitHubLink', () => {
  it('links to the DonkeyDrift GitHub repo in a new tab', () => {
    render(<GitHubLink />);
    const link = screen.getByRole('link', { name: 'DonkeyDrift GitHub 仓库' });
    expect(link).toHaveAttribute('href', 'https://github.com/DonkeyDrift/DonkeyDrift');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link.getAttribute('rel')).toContain('noopener');
  });

  it('renders the GitHub mark icon', () => {
    render(<GitHubLink />);
    const link = screen.getByRole('link', { name: 'DonkeyDrift GitHub 仓库' });
    const svg = link.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute('viewBox', '0 0 16 16');
  });
});
