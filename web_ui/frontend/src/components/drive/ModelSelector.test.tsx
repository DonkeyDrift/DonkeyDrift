import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ModelSelector } from './ModelSelector';

describe('ModelSelector', () => {
  it('默认显示无模型', () => {
    render(<ModelSelector value="" options={[]} onChange={vi.fn()} />);

    expect(screen.getByText('无模型')).toBeInTheDocument();
  });

  it('显示当前选中的模型', () => {
    render(<ModelSelector value="pilot_123.h5" options={['pilot_123.h5']} onChange={vi.fn()} />);

    expect(screen.getByText('pilot_123.h5')).toBeInTheDocument();
  });

  it('鼠标悬浮时展开并显示模型选项', () => {
    render(<ModelSelector value="" options={['a.h5', 'b.h5']} onChange={vi.fn()} />);

    fireEvent.mouseEnter(screen.getByText('无模型'));

    expect(screen.getByText('a.h5')).toBeInTheDocument();
    expect(screen.getByText('b.h5')).toBeInTheDocument();
  });

  it('选择模型后触发 onChange 并收起抽屉', () => {
    const onChange = vi.fn();
    const { rerender } = render(<ModelSelector value="" options={['a.h5', 'b.h5']} onChange={onChange} />);

    fireEvent.mouseEnter(screen.getByText('无模型'));
    fireEvent.click(screen.getByText('a.h5'));

    expect(onChange).toHaveBeenCalledWith('a.h5');

    rerender(<ModelSelector value="a.h5" options={['a.h5', 'b.h5']} onChange={onChange} />);

    expect(screen.getByText('a.h5')).toBeInTheDocument();
    expect(screen.queryByText('无模型')).not.toBeInTheDocument();
  });

  it('禁用时不展开', () => {
    render(<ModelSelector value="" options={['a.h5']} onChange={vi.fn()} disabled />);

    fireEvent.mouseEnter(screen.getByText('无模型'));

    expect(screen.queryByText('a.h5')).not.toBeInTheDocument();
  });

  it('鼠标移出后收起抽屉', async () => {
    render(<ModelSelector value="" options={['a.h5']} onChange={vi.fn()} />);

    const container = screen.getByTestId('model-selector');
    fireEvent.mouseEnter(container);
    expect(screen.getByText('a.h5')).toBeInTheDocument();

    fireEvent.mouseLeave(container);

    await waitFor(() => {
      expect(screen.queryByText('a.h5')).not.toBeInTheDocument();
    });
  });
});
