import '@testing-library/jest-dom/vitest';
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SidePanel } from './SidePanel';
import { useStore } from '../store/useStore';

// 移除 DD 页面手动 TubLoader：Tub 全部自动选择，加载器抽屉里消费者只需要
// 配置加载器；Tub 加载器标题、Tub 路径输入框和手动加载按钮不应再出现。
// 挂载即渲染真实 SidePanel 及其子组件——组件挂载不触发 API
// （自动加载已在 App 级 useConfigAutoLoad），无需 mock 外部 API。

beforeEach(() => {
  useStore.setState({
    activeDrawer: 'loaders',
    config: null,
    configPath: '',
    tubPath: '',
    records: [],
    totalRecords: 0,
    fields: [],
    isLoading: false,
    error: null,
  });
});

describe('SidePanel loaders drawer without manual TubLoader', () => {
  it('still offers the config loader when the loaders drawer is open', () => {
    render(<SidePanel />);

    expect(screen.getByText('配置加载器')).toBeInTheDocument();
    expect(screen.getByLabelText('配置路径输入框')).toBeInTheDocument();
  });

  it('hides the Tub loader title, Tub path input and manual load button', () => {
    render(<SidePanel />);

    expect(screen.queryByText('Tub 加载器')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Tub 路径输入框')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '加载 Tub' })).not.toBeInTheDocument();
  });
});
