import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TubNavigator } from './TubNavigator';
import { useStore } from '../store/useStore';

// 回归测试（#135）：Tub Navigator 提供手动刷新按钮，点击后触发 store 的
// requestTubRefresh（清空已加载标记 + 递增令牌），而不是依赖导航切换重拉。

vi.mock('../services/api', () => ({
  getImageUrl: vi.fn((_path: string, tub: string) => `http://localhost/api/tub/${tub}/image`),
}));

describe('TubNavigator manual refresh (#135)', () => {
  beforeEach(() => {
    useStore.setState({
      tubPath: '/tmp/tub',
      loadedTubPath: '/tmp/tub',
      tubRefreshToken: 0,
      records: [
        { _index: 0, _timestamp_ms: 0, 'user/angle': 0.1, 'user/throttle': 0.2 },
        { _index: 1, _timestamp_ms: 100, 'user/angle': 0.3, 'user/throttle': 0.4 },
      ],
      totalRecords: 2,
      totalPhysicalRecords: 2,
      deletedIndexes: [],
      currentIndex: 0,
      isLoading: false,
      isPlaying: false,
      isLooping: false,
      isDragging: false,
      error: null,
    });
  });

  it('renders a refresh button that triggers requestTubRefresh', () => {
    render(<TubNavigator />);
    const button = screen.getByLabelText('Refresh tub records');
    expect(button).toBeInTheDocument();

    fireEvent.click(button);
    const state = useStore.getState();
    expect(state.tubRefreshToken).toBe(1);
    expect(state.loadedTubPath).toBeNull();
  });
});
