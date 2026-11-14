type RafCallback = (now: number) => void;

/**
 * 页面级共享 rAF 循环：所有常驻的高频重绘（遥测曲线等）订阅同一个循环，
 * 而不是各自 requestAnimationFrame——减少调度开销，也保证各消费者的
 * 脏检查集中在每个 vsync 开头完成。
 *
 * 循环懒启动：首个订阅者加入时开启；最后一个订阅者退订后的下一帧自然停止。
 * 回调收到的 now 为 rAF 时间戳（与 performance.now() 同时基）。
 */
const subscribers = new Set<RafCallback>();
let rafHandle: number | null = null;

const tick = (now: number) => {
  rafHandle = null;
  for (const cb of subscribers) cb(now);
  if (subscribers.size > 0 && rafHandle === null) {
    rafHandle = requestAnimationFrame(tick);
  }
};

/** 订阅共享 rAF 循环，返回退订函数。 */
export const subscribeRafLoop = (cb: RafCallback): (() => void) => {
  subscribers.add(cb);
  if (rafHandle === null) {
    rafHandle = requestAnimationFrame(tick);
  }
  return () => {
    subscribers.delete(cb);
  };
};
