import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AdvancedOptions } from './AdvancedOptions';

const renderOptions = (props: { defaultOpen?: boolean; externalOpen?: boolean } = {}) =>
  render(
    <AdvancedOptions icon={<span>icon</span>} title="高级选项" {...props}>
      <div>折叠内容</div>
    </AdvancedOptions>,
  );

describe('AdvancedOptions', () => {
  it('默认收起：aria-expanded=false 且内容不可见；点击后展开', () => {
    renderOptions();

    const toggle = screen.getByRole('button', { name: /高级选项/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    const content = screen.getByTestId('advanced-options-content');
    expect(content).not.toBeVisible();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(content).toBeVisible();
  });

  it('externalOpen 从 false 变 true 时自动展开', () => {
    const { rerender } = render(
      <AdvancedOptions icon={<span>icon</span>} title="高级选项" externalOpen={false}>
        <div>折叠内容</div>
      </AdvancedOptions>,
    );
    const toggle = screen.getByRole('button', { name: /高级选项/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    rerender(
      <AdvancedOptions icon={<span>icon</span>} title="高级选项" externalOpen={true}>
        <div>折叠内容</div>
      </AdvancedOptions>,
    );
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('advanced-options-content')).toBeVisible();
  });
});
