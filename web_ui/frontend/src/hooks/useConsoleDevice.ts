import { useCallback, useEffect, useState } from 'react';
import { discoverConnectorConsoles } from '../services/api';

// 顶栏静音 / OTA / DEV 三个控件都需要车端 Drifter Console 的 IP，
// 但各自挂载会触发三次局域网扫描。这里用一个模块级 Promise 去重，
// 并把结果缓存在 sessionStorage，避免每次刷新都重新扫网。
//
// 缓存的 IP 可能失效（车端切网 / DHCP 重租）：控件 fetch 失败时调用
// refresh() 使缓存失效并重新扫描；扫描不到（车离线）时保持慢速重试，
// 车重新上线后自动恢复。

const STORAGE_KEY = 'donkeydrifter.console.ip';

// 扫描不到车端时的重试间隔（毫秒）。比控件轮询慢，避免空扫过于频繁。
const RETRY_SCAN_MS = 10000;

let cachedIp: string | null | undefined = undefined; // undefined = 尚未尝试
let inFlight: Promise<string | null> | null = null;

/** 使缓存失效：清空 sessionStorage 与模块级缓存，下次 resolve 重新扫描。 */
export const invalidateConsoleDeviceCache = () => {
  cachedIp = undefined;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // sessionStorage 不可用（如隐私模式）时忽略
  }
};

async function resolveConsoleIp(): Promise<string | null> {
  if (cachedIp !== undefined) return cachedIp;
  if (inFlight) return inFlight;

  const pending = (async () => {
    let ip: string | null;
    try {
      const stored = window.sessionStorage.getItem(STORAGE_KEY);
      if (stored) {
        ip = stored;
      } else {
        const result = await discoverConnectorConsoles();
        ip = result.found?.[0]?.ip ?? null;
        if (ip) window.sessionStorage.setItem(STORAGE_KEY, ip);
      }
    } catch {
      ip = null;
    }
    cachedIp = ip;
    return ip;
  })();
  inFlight = pending;
  // 清 inFlight 的回调必须挂在 promise 上（微任务），不能放进 IIFE 的 finally：
  // 同步完成的路径（sessionStorage 命中、全程无 await）下 finally 会先于
  // `inFlight = pending` 赋值执行，导致 inFlight 永久卡住为已旧的 promise。
  void pending.finally(() => {
    if (inFlight === pending) inFlight = null;
  });
  return pending;
}

export const useConsoleDevice = () => {
  const [ip, setIp] = useState<string | null>(cachedIp ?? null);
  const [resolving, setResolving] = useState(cachedIp === undefined);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    resolveConsoleIp().then((value) => {
      if (!cancelled) {
        setIp(value);
        setResolving(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const refresh = useCallback(() => {
    invalidateConsoleDeviceCache();
    setResolving(true);
    setAttempt((n) => n + 1);
  }, []);

  // 扫描不到车端时慢速重试，车重新上线后控件自动恢复可用。
  useEffect(() => {
    if (ip !== null || resolving) return;
    const timer = window.setTimeout(refresh, RETRY_SCAN_MS);
    return () => window.clearTimeout(timer);
  }, [ip, resolving, refresh]);

  return { ip, resolving, refresh };
};
