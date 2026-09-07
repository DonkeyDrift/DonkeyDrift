import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, _vars?: Record<string, unknown>) => key,
    lang: 'zh',
  }),
}));

vi.mock('@/lib/theme', () => ({
  useResolvedTheme: () => 'dark',
}));

import { TubEditorAiCleanModal } from './TubEditorAiCleanModal';

const makeSegment = (start: number, end: number, code = 'stop_then_reverse') => ({
  start_index: start,
  end_index: end,
  frame_count: end - start + 1,
  indexes: Array.from({ length: end - start + 1 }, (_, i) => start + i),
  reason_code: code,
  detail: { collision_index: start + 2, reverse_frames: 3 },
});

describe('TubEditorAiCleanModal', () => {
  it('列出待删片段清单并回调确认/取消', () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(
      <TubEditorAiCleanModal
        segments={[makeSegment(3, 5), makeSegment(20, 22, 'plunge_reverse')]}
        busy={false}
        onClose={onClose}
        onConfirm={onConfirm}
      />,
    );

    expect(screen.getByText('tubEditor.aiFilterTitle')).toBeInTheDocument();
    expect(screen.getAllByText('tubEditor.aiFilterSegmentRange')).toHaveLength(2);
    expect(screen.getByText('tubEditor.aiFilterSummary')).toBeInTheDocument();

    fireEvent.click(screen.getByText('tubEditor.aiFilterConfirm'));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText('tubEditor.aiFilterCancel'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('删除进行中禁用确认按钮', () => {
    render(
      <TubEditorAiCleanModal
        segments={[makeSegment(3, 5)]}
        busy
        onClose={() => {}}
        onConfirm={() => {}}
      />,
    );
    expect(screen.getByText('tubEditor.aiFilterDeleting')).toBeInTheDocument();
    expect(screen.getByText('tubEditor.aiFilterDeleting').closest('button')).toBeDisabled();
  });
});
