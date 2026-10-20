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

async function autoLoadTubFor(carPath: string) {
  const tubPath =
    carPath.endsWith('/') || carPath.endsWith('\\') ? `${carPath}data` : `${carPath}/data`;
  try {
    const data = await loadTub(tubPath);
    if (data.records && data.records.length === 0) {
      // <car>/data 是合法 tub 但记录全空（常见：deleted_indexes 覆盖全部索引）
      // 时，真实录制在子目录的子 tub 里（新版滚动录制按 tub_序号_日期 建子
      // 目录）：自动切到最新的子 tub，避免录制视频库显示「暂无录制」
      try {
        const childData = await listChildTubs(tubPath);
        const newest = childData.child_tubs?.[0];
        if (newest) {
          console.warn(
            `Tub ${tubPath} has no live records; falling back to newest child tub: ${newest.path}`,
          );
          const childTubData = await loadTub(newest.path);
          useStore
            .getState()
            .setTub(
              childTubData.path,
              childTubData.records || [],
              childTubData.fields || [],
              childTubData.total_physical_records,
              childTubData.deleted_indexes,
            );
          return;
        }
      } catch {
        // 子 tub 发现/加载失败维持现状：按原空 data 正常 setTub
      }
    }
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
    console.warn('Auto-loading tub from ./data failed, user might need to select manually.');
  }
}

async function loadProject(path: string, t: (key: string) => string) {
  const { setConfig, setError, setLoading } = useStore.getState();
  setLoading(true);
  try {
    const data = await loadConfig(path);
    setConfig(data.config, path);

    // 已持久化过别的 tub 路径时优先恢复它,否则回退自动加载 ./data
    const currentTubPath = useStore.getState().tubPath;
    if (
      currentTubPath &&
      currentTubPath !== path + '/data' &&
      currentTubPath !== path.replace(/\/$/, '') + '/data'
    ) {
      try {
        const tubData = await loadTub(currentTubPath);
        useStore
          .getState()
          .setTub(
            tubData.path,
            tubData.records || [],
            tubData.fields || [],
            tubData.total_physical_records,
            tubData.deleted_indexes
          );
      } catch {
        await autoLoadTubFor(path);
      }
    } else {
      await autoLoadTubFor(path);
    }
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
