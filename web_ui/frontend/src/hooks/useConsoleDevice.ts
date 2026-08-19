import { useEffect, useState } from 'react';
import { discoverConnectorConsoles } from '../services/api';

// 顶栏静音 / OTA / DEV 三个控件都需要车端 Drifter Console 的 IP，
// 但各自挂载会触发三次局域网扫描。这里用一个模块级 Promise 去重，
// 并把结果缓存在 sessionStorage，避免每次刷新都重新扫网。

const STORAGE_KEY = 'donkeydrifter.console.ip';

let cachedIp: string | null | undefined = undefined; // undefined = 尚未尝试
let inFlight: Promise<string | null> | null = null;

async function resolveConsoleIp(): Promise<string | null> {
  if (cachedIp !== undefined) return cachedIp;
  if (inFlight) return inFlight;

  inFlight = (async () => {
    try {
      const stored = window.sessionStorage.getItem(STORAGE_KEY);
      if (stored) {
        cachedIp = stored;
        return stored;
      }
      const result = await discoverConnectorConsoles();
      const ip = result.found?.[0]?.ip ?? null;
      cachedIp = ip;
      if (ip) window.sessionStorage.setItem(STORAGE_KEY, ip);
      return ip;
    } catch {
      cachedIp = null;
      return null;
    } finally {
      inFlight = null;
    }
  })();

  return inFlight;
}

export const useConsoleDevice = () => {
  const [ip, setIp] = useState<string | null>(cachedIp ?? null);
  const [resolving, setResolving] = useState(cachedIp === undefined);

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
  }, []);

  return { ip, resolving };
};
