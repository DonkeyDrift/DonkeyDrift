// Node >= 22 自带的实验性 localStorage（未传 --localstorage-file 时为 undefined）
// 遮蔽了 jsdom 的 window.localStorage，导致 zustand persist 在测试中拿不到存储。
// 这里统一提供内存版 localStorage，使依赖持久化的 store 在测试环境可用。

const data = new Map<string, string>();

const memoryStorage: Storage = {
  get length() {
    return data.size;
  },
  clear: () => data.clear(),
  getItem: (key: string) => (data.has(key) ? data.get(key)! : null),
  key: (index: number) => [...data.keys()][index] ?? null,
  removeItem: (key: string) => {
    data.delete(key);
  },
  setItem: (key: string, value: string) => {
    data.set(key, String(value));
  },
};

if (typeof globalThis.localStorage === 'undefined') {
  Object.defineProperty(globalThis, 'localStorage', {
    value: memoryStorage,
    configurable: true,
  });
}
if (typeof window !== 'undefined' && typeof window.localStorage === 'undefined') {
  Object.defineProperty(window, 'localStorage', {
    value: globalThis.localStorage,
    configurable: true,
  });
}
