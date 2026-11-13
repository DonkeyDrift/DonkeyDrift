import { useEffect, useRef } from 'react';
import { useStore } from '../store/useStore';
import { loadConfig, loadTub, discoverProjects, listChildTubs, getApiErrorMessage } from '../services/api';
import { useTranslation } from '@/i18n';

/**
 * 车端配置的自动加载（App 级,随应用常驻）:
 * 1) 持久化的 configPath(localStorage)存在而 config 为空 → 延迟 500ms 恢复加载;
 * 2) 连 configPath 都没有 → 自动发现 mycar 项目(唯一项目或上次项目)并加载。
 *
 * 此前这两个逻辑只挂在「加载器」抽屉的 ConfigLoader 里——用户刷新后直接
 * 打开「连接器」便签页时 ConfigLoader 未挂载,config 恒为 null,连接器
 * 表单永远显示未配置(实际 myconfig.py 已保存成功)。
 */

let latestTubLoadRequest = 0;

/**
 * 尝试加载 tubPath 下最新的子 tub（新版滚动录制按 tub_序号_日期 把真实录制
 * 放在子目录里，listChildTubs 已按 last_modified 降序，第一条即最新）。
 * 成功加载并 setTub 返回 true；无子 tub 或发现/加载失败返回 false。
 */
async function loadNewestChildTub(
  tubPath: string,
  reason: string,
  requestId: number,
): Promise<boolean> {
  try {
    const childData = await listChildTubs(tubPath);
    if (requestId !== latestTubLoadRequest) return false;
    const newest = childData.child_tubs?.[0];
    if (!newest) return false;
    console.warn(`${reason}; falling back to newest child tub: ${newest.path}`);
    const childTubData = await loadTub(newest.path);
    if (requestId !== latestTubLoadRequest) return false;
    useStore
      .getState()
      .setTub(
        childTubData.path,
        childTubData.records || [],
        childTubData.fields || [],
        childTubData.total_physical_records,
        childTubData.deleted_indexes,
      );
    return true;
  } catch {
    // 子 tub 发现/加载失败由调用方决定是否保留原有数据
    return false;
  }
}

export async function autoLoadTubFor(carPath: string) {
  const requestId = ++latestTubLoadRequest;
  const tubPath =
    carPath.endsWith('/') || carPath.endsWith('\\') ? `${carPath}data` : `${carPath}/data`;
  const persistedTubPath = useStore.getState().tubPath;

  if (persistedTubPath && persistedTubPath !== tubPath) {
    try {
      const data = await loadTub(persistedTubPath);
      if (requestId !== latestTubLoadRequest) return;
      useStore
        .getState()
        .setTub(
          data.path,
          data.records || [],
          data.fields || [],
          data.total_physical_records,
          data.deleted_indexes,
        );
      return;
    } catch {
      if (requestId !== latestTubLoadRequest) return;
    }
  }

  try {
    const data = await loadTub(tubPath);
    if (requestId !== latestTubLoadRequest) return;
    if (!data.records || data.records.length === 0) {
      // <car>/data 是合法 tub 但记录全空（常见：deleted_indexes 覆盖全部索引）
      // 时，真实录制在子目录的子 tub 里：自动切到最新的子 tub，避免录制视频
      // 库显示「暂无录制」
      const fellBack = await loadNewestChildTub(
        tubPath,
        `Tub ${tubPath} has no live records`,
        requestId,
      );
      if (requestId !== latestTubLoadRequest) return;
      if (fellBack) return;
    }
    // 无子 tub 可回退时维持现状：按原空 data 正常 setTub
    if (requestId !== latestTubLoadRequest) return;
    useStore
      .getState()
      .setTub(
        data.path,
        data.records || [],
        data.fields || [],
        data.total_physical_records,
        data.deleted_indexes,
      );
  } catch {
    if (requestId !== latestTubLoadRequest) return;
    // ./data 本身加载失败（如只是普通目录、并非合法 tub）：同样回退到最新的
    // 子 tub；仍失败时清空上一配置残留的 Tub 数据
    const fellBack = await loadNewestChildTub(tubPath, `Tub ${tubPath} failed to load`, requestId);
    if (requestId !== latestTubLoadRequest) return;
    if (!fellBack) {
      useStore.getState().clearTub();
      console.warn(`Auto-loading tub from ${tubPath} and its child tubs both failed.`);
    }
  }
}

async function loadProject(path: string, t: (key: string) => string) {
  const { setConfig, setError, setLoading } = useStore.getState();
  setLoading(true);
  try {
    const data = await loadConfig(path);
    setConfig(data.config, path);
    await autoLoadTubFor(path);
  } catch (err: unknown) {
    setError(getApiErrorMessage(err, t('common.configLoader.failedToLoad')));
  } finally {
    setLoading(false);
  }
}

export function useConfigAutoLoad() {
  const { t } = useTranslation();
  const config = useStore((s) => s.config);
  const configPath = useStore((s) => s.configPath);
  const autoDiscoverTried = useRef(false);

  // 1) 从持久化的 configPath 恢复(configAutoLoadTried 防止 ConfigLoader 重试)
  useEffect(() => {
    if (!config && configPath && !useStore.getState().configAutoLoadTried) {
      useStore.getState().setError(null);
      const timer = setTimeout(() => {
        useStore.setState({ configAutoLoadTried: true });
        loadProject(configPath, t);
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [config, configPath, t]);

  // 2) 无 configPath 时自动发现 mycar(唯一项目→直接加载;多个→上次项目)
  useEffect(() => {
    if (config || configPath || autoDiscoverTried.current) return;
    autoDiscoverTried.current = true;
    let cancelled = false;
    (async () => {
      try {
        const data = await discoverProjects();
        if (cancelled) return;
        if (data.count === 1 && data.projects[0]) {
          await loadProject(data.projects[0], t);
        } else if (data.last_project && data.projects.includes(data.last_project)) {
          await loadProject(data.last_project, t);
        }
      } catch {
        // 自动发现失败时保持现状,用户手动 Browse 选择
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [config, configPath, t]);
}
