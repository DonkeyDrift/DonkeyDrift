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

// 默认连接 <car>/data 并加载（含空 data 时回退最新子 tub）。
// 供 App 级自动加载与 ConfigLoader 手动加载共用；导出供回归测试直接调用。
//
// 异步写回前一律校验项目目录（configPath）是否仍是发起时的 carPath：
// 加载在途时用户又切了别的项目目录，本次结果整体作废——否则旧项目的
// tub 晚到写回会把 tubPath 掰回旧项目，与新项目的加载/轮询来回打架，
// 表现为录制列表在两个项目间来回闪动。
export async function autoLoadTubFor(carPath: string) {
  const tubPath =
    carPath.endsWith('/') || carPath.endsWith('\\') ? `${carPath}data` : `${carPath}/data`;
  // 先默认连接：Tub 加载器输入框指向 <car>/data。data 文件夹还没有（未录制
  // 过）时加载失败也保持该默认路径，静默等待用户首次录制，不报错。
  useStore.getState().setDefaultTubPath(tubPath);
  const isSuperseded = () => useStore.getState().configPath !== carPath;
  try {
    const data = await loadTub(tubPath);
    if (isSuperseded()) return;
    if (data.records && data.records.length === 0) {
      // <car>/data 是合法 tub 但记录全空（常见：deleted_indexes 覆盖全部索引）
      // 时，真实录制在子目录的子 tub 里（新版滚动录制按 tub_序号_日期 建子
      // 目录）：自动切到最新的子 tub，避免录制视频库显示「暂无录制」
      try {
        const childData = await listChildTubs(tubPath);
        if (isSuperseded()) return;
        const newest = childData.child_tubs?.[0];
        if (newest) {
          console.warn(
            `Tub ${tubPath} has no live records; falling back to newest child tub: ${newest.path}`,
          );
          const childTubData = await loadTub(newest.path);
          if (isSuperseded()) return;
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

// 加载一个 mycar 项目：config 落库 → 恢复本项目上次的 tub（仅同项目）→
// 否则默认连接 <car>/data。自动加载（App 级）与 ConfigLoader 手动加载共用。
export async function loadProject(path: string, t: (key: string) => string) {
  const { setConfig, setError, setLoading } = useStore.getState();
  setLoading(true);
  try {
    const data = await loadConfig(path);
    // loadConfig 在途期间可能已有别的项目加载完成：本次已过期，整体放弃
    if (useStore.getState().configPath !== path && useStore.getState().config) {
      return;
    }
    setConfig(data.config, path);

    // 已持久化的 tub 路径属于本项目（如 data/tub_7 子目录）时优先恢复它；
    // 属于别的项目则不带来——切换项目后默认连接新项目的 ./data，旧项目的
    // tub 不再被继续加载/轮询
    const currentTubPath = useStore.getState().tubPath;
    const projectRoot = path.replace(/\/$/, '');
    const sameProjectTub =
      currentTubPath !== `${projectRoot}/data` &&
      currentTubPath.startsWith(`${projectRoot}/`);
    if (currentTubPath && sameProjectTub) {
      try {
        const tubData = await loadTub(currentTubPath);
        // 恢复在途时用户又切了别的项目：放弃写回，交给新项目的加载流程
        if (useStore.getState().configPath !== path) return;
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
        if (useStore.getState().configPath === path) {
          await autoLoadTubFor(path);
        }
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
