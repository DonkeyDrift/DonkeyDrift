// WebRTC 浏览器端闭环探针（Node + Playwright）。
//
// 以真实 Chromium 打开 Drive 页面（HashRouter 根路径即含 drive section），
// 挂 rVFC 采样渲染帧率与端到端时延（expectedDisplayTime − captureTime，
// 同处浏览器时钟域，无需跨机同步），从后端 stats 读取浏览器自报指标，
// 输出 JSON 报告；--gate-* 参数构成闭环门禁（不达标退出码 1）。
//
// 用法：
//   node e2e/webrtc-browser-probe.mjs --url http://127.0.0.1:8123/ --duration 12
//   node e2e/webrtc-browser-probe.mjs ... --gate-fps 59 --gate-e2e-ms 30
import { chromium } from 'playwright-core';

const parseArgs = () => {
  const args = process.argv.slice(2);
  const get = (name, fallback) => {
    const i = args.indexOf(name);
    return i >= 0 ? args[i + 1] : fallback;
  };
  const has = (name) => args.includes(name);
  return {
    url: get('--url', 'http://127.0.0.1:8001/'),
    duration: Number(get('--duration', '12000')),
    settleMs: Number(get('--settle', '6000')),
    gateFps: get('--gate-fps') ? Number(get('--gate-fps')) : null,
    gateE2eMs: get('--gate-e2e-ms') ? Number(get('--gate-e2e-ms')) : null,
    jsonOnly: has('--json'),
    headless: !has('--headed'),
  };
};

const percentile = (values, ratio) => {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * ratio) - 1));
  return sorted[index];
};

// 注意：本函数经 page.evaluate 序列化后在页面内执行，闭包变量不会随之
// 序列化——只能引用函数自身参数与页内局部定义（勿引用本模块 percentile）。
const sampleInPage = (durationMs) => new Promise((resolve) => {
  const video = document.querySelector('video');
  if (!video || !video.requestVideoFrameCallback) {
    resolve({ error: 'no-video-or-rvfc' });
    return;
  }
  const presentationTimes = [];
  const e2eDeltas = [];
  let rVfcCount = 0;
  const start = performance.now();
  const pctl = (values, ratio) => {
    if (values.length === 0) return 0;
    const sorted = [...values].sort((a, b) => a - b);
    const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * ratio) - 1));
    return sorted[index];
  };
  const step = (_now, meta) => {
    presentationTimes.push(meta.presentationTime);
    rVfcCount += 1;
    const captureTime = meta.captureTime;
    if (captureTime !== undefined && meta.expectedDisplayTime !== undefined) {
      const delta = meta.expectedDisplayTime - captureTime;
      if (delta >= 0 && delta <= 1000) e2eDeltas.push(delta);
    }
    if (performance.now() - start < durationMs) {
      video.requestVideoFrameCallback(step);
    } else {
      const intervals = presentationTimes.slice(1)
        .map((t, i) => t - presentationTimes[i]);
      resolve({
        rVfcCount,
        renderedFps: (rVfcCount * 1000) / (presentationTimes[presentationTimes.length - 1] - presentationTimes[0]),
        intervalP95Ms: pctl(intervals, 0.95),
        e2eP50Ms: pctl(e2eDeltas, 0.5),
        e2eP95Ms: pctl(e2eDeltas, 0.95),
        e2eSamples: e2eDeltas.length,
      });
    }
  };
  video.requestVideoFrameCallback(step);
});

const run = async () => {
  const cfg = parseArgs();
  const browser = await chromium.launch({
    headless: cfg.headless,
    args: [
      '--autoplay-policy=no-user-gesture-required',
      '--disable-background-timer-throttling',
      '--disable-renderer-backgrounding',
      '--disable-backgrounding-occluded-windows',
    ],
  });
  const report = { url: cfg.url, durationMs: cfg.duration };
  try {
    const page = await browser.newPage();
    await page.goto(cfg.url, { waitUntil: 'domcontentloaded', timeout: 20000 });
    // 等 WebRTC 出画：video 元素出现并产生首帧（settle 窗口内轮询渲染帧）。
    // 页面首次加载会有一次自动 reload（SW 安装/版本检查），轮询须容忍
    // evaluate 的 "Execution context was destroyed" 并继续等下一次。
    const isCtxDestroyed = (e) => String(e).includes('Execution context was destroyed');
    const deadline = Date.now() + cfg.settleMs + 15000;
    let framesStarted = false;
    while (Date.now() < deadline) {
      const hasFrames = await page.evaluate(() => {
        const video = document.querySelector('video');
        return Boolean(video && video.readyState >= 2 && video.getVideoPlaybackQuality().totalVideoFrames > 0);
      }).catch((e) => { if (!isCtxDestroyed(e)) throw e; return false; });
      if (hasFrames) { framesStarted = true; break; }
      await page.waitForTimeout(500);
    }
    if (!framesStarted) throw new Error('视频首帧未在限时内出现');
    // 正式采样：页面偶发 lazy-chunk 加载失败触发 react-router 整页 reload
    // （react-vendor 内置 location.reload()），会打断长采样。最多重试 3 次。
    const waitFrames = async () => {
      const dl = Date.now() + cfg.settleMs + 15000;
      while (Date.now() < dl) {
        const ok = await page.evaluate(() => {
          const video = document.querySelector('video');
          return Boolean(video && video.readyState >= 2 && video.getVideoPlaybackQuality().totalVideoFrames > 0);
        }).catch((e) => { if (!isCtxDestroyed(e)) throw e; return false; });
        if (ok) return true;
        await page.waitForTimeout(500);
      }
      return false;
    };
    let sampled = false;
    for (let attempt = 1; attempt <= 3 && !sampled; attempt++) {
      if (attempt > 1) {
        if (!(await waitFrames())) throw new Error('reload 后视频未恢复');
      }
      try {
        report.render = await page.evaluate(sampleInPage, cfg.duration);
        sampled = true;
      } catch (e) {
        if (!isCtxDestroyed(e) || attempt === 3) throw e;
      }
    }
    // 后端聚合 stats（浏览器 hook 每秒自报 + 车端 source/sent）
    const statsResponse = await page.request.get(new URL('/api/drive/webrtc/stats', cfg.url).href);
    report.backendStats = await statsResponse.json();
    report.render.renderedFps = Math.round(report.render.renderedFps * 100) / 100;
  } finally {
    await browser.close();
  }

  let failed = false;
  if (cfg.gateFps !== null) {
    report.gateFps = { threshold: cfg.gateFps, actual: report.render.renderedFps };
    if (report.render.renderedFps < cfg.gateFps) failed = true;
  }
  if (cfg.gateE2eMs !== null) {
    const actual = report.render.e2eP95Ms ?? null;
    report.gateE2e = { threshold: cfg.gateE2eMs, actual };
    if (actual === null || actual > cfg.gateE2eMs) failed = true;
  }
  report.pass = !failed;
  console.log(JSON.stringify(report, null, cfg.jsonOnly ? 0 : 2));
  return failed ? 1 : 0;
};

run().then((code) => process.exit(code)).catch((exc) => {
  console.error(JSON.stringify({ pass: false, error: String(exc), stack: exc && exc.stack ? exc.stack.split('\n').slice(0,6).join(' | ') : null }));
  process.exit(2);
});
