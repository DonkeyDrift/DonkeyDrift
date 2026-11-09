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

describe('useStore activeTraining（刷新后恢复训练进度）', () => {
  beforeEach(() => {
    useStore.setState({ activeTraining: null, trainingJob: null });
  });

  it('setActiveTraining 记录正在训练的任务 id 与模式', () => {
    useStore.getState().setActiveTraining('job-1', 'mypc');
    expect(useStore.getState().activeTraining).toEqual({ id: 'job-1', mode: 'mypc' });
  });

  it('clearActiveTraining 清空任务标记', () => {
    useStore.getState().setActiveTraining('job-1', 'local');
    useStore.getState().clearActiveTraining();
    expect(useStore.getState().activeTraining).toBeNull();
  });

  it('finishTrainingJob 在任务终态时同步清空 activeTraining', () => {
    useStore.setState({
      activeTraining: { id: 'job-1', mode: 'local' },
      trainingJob: {
        id: 'job-1',
        mode: 'local',
        status: 'running',
        progress: { currentEpoch: 0, totalEpochs: 0, currentStep: 0, totalSteps: 0, loss: null, globalPercent: 0 },
        logs: [],
        startedAt: new Date().toISOString(),
      },
    });
    useStore.getState().finishTrainingJob('completed');
    expect(useStore.getState().trainingJob?.status).toBe('completed');
    expect(useStore.getState().activeTraining).toBeNull();
  });
});

// 默认连接（配置加载后指向 <car>/data）：只落输入框路径并标记「已处理」，
// 同时清掉旧 tub 的残留记录，data 缺失时保持默认路径等待首次录制。
describe('useStore setDefaultTubPath 默认连接', () => {
  beforeEach(() => {
    useStore.setState({
      tubPath: '/old/data',
      loadedTubPath: '/old/data',
      records: [{ _index: 0, _timestamp_ms: 0 }],
      originalRecords: [{ _index: 0, _timestamp_ms: 0 }],
      totalRecords: 1,
      tubTotalRecords: 1,
      totalPhysicalRecords: 1,
      deletedIndexes: [2],
      fields: ['cam/image_array'],
      activeSessionId: 's1',
      activeSessionRecords: [{ _index: 0, _timestamp_ms: 0 }],
      activeSessionIds: ['s1'],
      activeSessionCrossTub: true,
      isPlaying: true,
    });
  });

  it('落默认路径并清空旧 tub 残留，loadedTubPath 同步标记已处理', () => {
    useStore.getState().setDefaultTubPath('/new/data');
    const state = useStore.getState();
    expect(state.tubPath).toBe('/new/data');
    expect(state.loadedTubPath).toBe('/new/data');
    expect(state.records).toEqual([]);
    expect(state.originalRecords).toEqual([]);
    expect(state.totalRecords).toBe(0);
    expect(state.tubTotalRecords).toBe(0);
    expect(state.totalPhysicalRecords).toBe(0);
    expect(state.deletedIndexes).toEqual([]);
    expect(state.fields).toEqual([]);
    expect(state.activeSessionId).toBeNull();
    expect(state.activeSessionRecords).toEqual([]);
    expect(state.activeSessionIds).toEqual([]);
    expect(state.activeSessionCrossTub).toBe(false);
    expect(state.isPlaying).toBe(false);
  });
});

// 多选会话筛选（家族视图）：setActiveSession 第三参 sessionIds 缺省时从
// sessionId 派生（向后兼容，所有既有调用点行为不变）；显式传入则保留集合。
describe('useStore setActiveSession 多选集合派生', () => {
  beforeEach(() => {
    useStore.setState({ activeSessionId: null, activeSessionRecords: [], activeSessionIds: [] });
  });

  it('第三参缺省时，sessionId 非空派生为单元素数组', () => {
    useStore.getState().setActiveSession('s1', []);
    expect(useStore.getState().activeSessionIds).toEqual(['s1']);
  });

  it('第三参缺省时，sessionId 为 null 派生为空数组', () => {
    useStore.getState().setActiveSession(null, []);
    expect(useStore.getState().activeSessionIds).toEqual([]);
  });

  it('显式传入 sessionIds 时原样保留（多选聚合写回）', () => {
    useStore.getState().setActiveSession('s2', [], ['s1', 's2']);
    expect(useStore.getState().activeSessionId).toBe('s2');
    expect(useStore.getState().activeSessionIds).toEqual(['s1', 's2']);
  });

  it('setTub 切换 tub 时清空多选集合', () => {
    useStore.getState().setActiveSession('s2', [], ['s1', 's2']);
    useStore.getState().setTub('/tmp/tub2', [], ['cam/image_array']);
    expect(useStore.getState().activeSessionIds).toEqual([]);
    expect(useStore.getState().activeSessionId).toBeNull();
  });
});
