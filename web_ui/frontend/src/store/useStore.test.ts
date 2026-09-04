import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from './useStore';

// 回归（点击「加载器」没有反应）：setError(null) 不得联动关闭侧边抽屉。
// ConfigLoader 挂载时会 setError(null)，老用户（persist 了 configPath、全局 config 为 null）
// 每次打开抽屉都会触发该调用；若联动把 activeDrawer 置空，抽屉被瞬间关上且自动加载
// 定时器随组件卸载取消，config 永远加载不上，抽屉再也打不开。
describe('useStore.setError 与 activeDrawer 联动', () => {
  beforeEach(() => {
    useStore.setState({ error: null, activeDrawer: null });
  });

  it('setError(null) 仅清除错误，不改变 activeDrawer（loaders）', () => {
    useStore.setState({ activeDrawer: 'loaders' });
    useStore.getState().setError(null);
    expect(useStore.getState().error).toBeNull();
    expect(useStore.getState().activeDrawer).toBe('loaders');
  });

  it('setError(null) 在 connectors 抽屉打开时同样不联动', () => {
    useStore.setState({ activeDrawer: 'connectors' });
    useStore.getState().setError(null);
    expect(useStore.getState().activeDrawer).toBe('connectors');
  });

  it('路径类错误（含 not found / Failed）保持既有行为：打开 loaders 抽屉', () => {
    useStore.getState().setError('tub path not found');
    expect(useStore.getState().error).toBe('tub path not found');
    expect(useStore.getState().activeDrawer).toBe('loaders');

    useStore.setState({ error: null, activeDrawer: null });
    useStore.getState().setError('Failed to load config');
    expect(useStore.getState().activeDrawer).toBe('loaders');
  });

  it('其它非空错误保持既有行为：置 error 并关闭抽屉', () => {
    useStore.setState({ activeDrawer: 'loaders' });
    useStore.getState().setError('加载配置失败');
    expect(useStore.getState().error).toBe('加载配置失败');
    expect(useStore.getState().activeDrawer).toBeNull();
  });
});
