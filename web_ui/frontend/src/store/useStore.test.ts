import { describe, it, expect, beforeEach } from 'vitest';
import { useStore, type TubRecord } from './useStore';

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
    expect(useStore.getState().error).toBeNull();
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

// 回归（代码审查）：自动 Tub 全部失败后残留上一配置的数据；从浏览配置入口进入时
// 持久化 Tub 也不被恢复。需要 clearTub() 做完整重置：浏览态（tub 数据/计数/会话/
// 播放/拖动/选择历史）全部回到空初始态，但不触碰 config/configPath、isLooping 与 error。
// 期望值均取自 useStore 初始状态字面量，手工推导，不复用生产代码计算。
describe('useStore clearTub（Tub 浏览态完整重置）', () => {
  const seedLoadedTubBrowseState = () => {
    const records: TubRecord[] = [
      { _index: 0, _timestamp_ms: 1000, 'user/angle': 0.1 },
      { _index: 1, _timestamp_ms: 2000, 'user/angle': 0.2 },
    ];
    const state = useStore.getState();
    state.setTub('/tmp/tub-red', records, ['user/angle', 'cam/image_array'], 5, [3, 4]);
    state.setActiveSession('session-red', records);
    state.setCurrentIndex(1);
    state.setIsPlaying(true);
    state.setIsDragging(true);
    state.setSelectionRange(0, 2);
    state.setConfig({ drive_mode: 'manual' }, '/tmp/mycar/config-red.yml');
    state.setIsLooping(true);
    // setError 有抽屉联动副作用，error 用直接写入隔离（本组测试不关心 activeDrawer）
    useStore.setState({ error: '加载 Tub 失败-red' });
  };

  // clearTub 尚未实现时以断言失败（而非 TypeError）进入 RED：先取函数、断言存在、再调用
  const getClearTub = () =>
    (useStore.getState() as ReturnType<typeof useStore.getState> & { clearTub?: () => void })
      .clearTub;

  it('将 Tub 数据、计数、会话、播放、拖动与选择历史全部重置为空初始态', () => {
    seedLoadedTubBrowseState();
    const clearTub = getClearTub();
    expect(typeof clearTub).toBe('function');
    clearTub!();

    const s = useStore.getState();
    expect(s.tubPath).toBe('');
    expect(s.loadedTubPath).toBeNull();
    expect(s.records).toEqual([]);
    expect(s.originalRecords).toEqual([]);
    expect(s.totalRecords).toBe(0);
    expect(s.tubTotalRecords).toBe(0);
    expect(s.totalPhysicalRecords).toBe(0);
    expect(s.deletedIndexes).toEqual([]);
    expect(s.fields).toEqual([]);
    expect(s.currentIndex).toBe(0);
    expect(s.activeSessionId).toBeNull();
    expect(s.activeSessionRecords).toEqual([]);
    expect(s.isPlaying).toBe(false);
    expect(s.isDragging).toBe(false);
    expect(s.selectionStartIndex).toBeNull();
    expect(s.selectionEndIndex).toBeNull();
    expect(s.selectionHistory).toEqual([]);
    expect(s.selectionHistoryIndex).toBe(-1);
  });

  it('不误清 config/configPath、isLooping 与 error', () => {
    seedLoadedTubBrowseState();
    const clearTub = getClearTub();
    expect(typeof clearTub).toBe('function');
    clearTub!();

    const s = useStore.getState();
    expect(s.config).toEqual({ drive_mode: 'manual' });
    expect(s.configPath).toBe('/tmp/mycar/config-red.yml');
    expect(s.isLooping).toBe(true);
    expect(s.error).toBe('加载 Tub 失败-red');
  });
});
