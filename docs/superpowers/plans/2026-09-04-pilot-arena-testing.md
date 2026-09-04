# Pilot Arena 测试推进 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Pilot Arena 推理优化（config 缓存提速 + 模型贴合摘要）补齐分层测试：修复本机 4 例环境性失败、加后端性能回归护栏与真实模型集成测试、补前端组件测试、搭 Playwright 浏览器 E2E。

**Architecture:** 六层测试推进，逐层锁定已交付的优化：(1) 修测试基建 bug（drift_vision 替身依赖真库）；(2) 单元级回归护栏（predict 不重载 config）；(3) opt-in 真实模型集成测试（本机 mycar + DKG-1.tflite 实测时延/日志/缓存）；(4) 前端组件测试（摘要面板渲染）；(5) Playwright route-mocked E2E（真实 UI 流）；(6) 可选环境补齐与手工验收清单。每层独立可合并、可单独验证。

**Tech Stack:** pytest + FastAPI TestClient（后端）；vitest + @testing-library/react（前端）；@playwright/test 1.58（已装，浏览器需下载）；zustand store（测试中用 `useStore.setState` 注入状态）。

---

## 现状基线（本机实测，执行前对照）

- 后端：`cd web_ui/backend && python -m pytest tests/ -q` → **340 passed + 2 skipped + 4 failed**。4 例失败 = `tests/test_drift_vision.py::TestAdaptiveDetection`（4 个），根因见 Task 1。
- 前端：`cd web_ui/frontend && npx vitest run` → **158 passed**（27 文件）；无 `PilotArenaPage` 组件测试。
- E2E：`@playwright/test@1.58.2` 已装但无 `playwright.config`、无 `e2e/` 目录、浏览器未下载（`~/.cache/ms-playwright` 为空）。
- 本机存在真实工程 `/home/dkc/projects/mycar`（config.py + myconfig.py + `models/DKG-1.tflite`）→ 集成测试可直接跑真实模型。
- 本机 Python 3.11.14，无 `pupil_apriltags`（Windows 开发机已装）。

任务间相互独立，推荐顺序执行 1→2→3→4→5→6。

---

### Task 1: 修复 TestAdaptiveDetection 4 例失败（测试基建 bug，非产品 bug）

**Files:**
- Modify: `web_ui/backend/tests/test_drift_vision.py:302-320`

根因：`drift_vision.py:29-33` 的 `pupil_apriltags` 导入已有 try/except，缺库时模块**没有** `_PupilDetector` 属性；而 `TestAdaptiveDetection._fake_pupil` 用 `monkeypatch.setattr(drift_vision, "_PupilDetector", FakePupil)`（默认 `raising=True`）→ AttributeError。这 4 个测试本就该用假检测器跑、不需要真库；再补上 `_PUPIL_APRILTAGS_AVAILABLE = True` 以通过 `AprilTagDetector.__init__` 的可用性守卫（`drift_vision.py:431`）。

- [ ] **Step 1: 修改 `_fake_pupil`（替换 test_drift_vision.py:320 的单行 setattr）**

```python
        monkeypatch.setattr(drift_vision, "_PupilDetector", FakePupil, raising=False)
        monkeypatch.setattr(drift_vision, "_PUPIL_APRILTAGS_AVAILABLE", True)
```

- [ ] **Step 2: 运行 4 个测试验证通过**

Run: `cd web_ui/backend && python -m pytest tests/test_drift_vision.py::TestAdaptiveDetection -v`
Expected: `4 passed`

- [ ] **Step 3: 全量后端回归，确认失败清零**

Run: `cd web_ui/backend && python -m pytest tests/ -q`
Expected: `344 passed, 2 skipped in ...`（2 skipped = 真库才跑的 `test_apriltag_generator` 模块 + `test_downscale_keeps_fullres_coordinates`，均为既有 importorskip）

- [ ] **Step 4: Commit**

```bash
git add web_ui/backend/tests/test_drift_vision.py
git commit -m "test(drift-vision): 修复无 pupil_apriltags 环境下 TestAdaptiveDetection 替身注入失败"
```

---

### Task 2: 后端回归护栏——predict 逐帧不重编译 config

**Files:**
- Modify: `web_ui/backend/tests/test_arena.py`（文件末尾追加）

> **计划修订记录（执行期发现）：** 原版断言「predict 期间 `load_car_config` 只执行 1 次」是**错的**——`predict` 每帧调用 `load_car_config` 是设计使然（`routers/arena.py:324`，命中其内部 mtime 缓存、开销可忽略）。真正的回归对象是其内部昂贵的 `load_config`（≈75ms 编译）。已改为计数 `load_config`，并经变异测试验证（mtime 缓存失效 → 计数 4 → 断言失败）。

- [ ] **Step 1: 在 test_arena.py 末尾追加测试（完整代码，逐字复制）**

```python
def test_predict_does_not_reload_config_per_frame(monkeypatch, tmp_path):
    """config 按 mtime 缓存：predict 热路径不得逐帧重编译 car config（回归护栏）。

    注意：predict 每帧调用 load_car_config 是设计使然（命中 mtime 缓存、开销可忽略）；
    本测试锁的是其内部昂贵的 load_config 编译只发生一次。
    """
    (tmp_path / "config.py").write_text("IMAGE_H = 120\nIMAGE_W = 160\nIMAGE_DEPTH = 3\n")
    (tmp_path / "myconfig.py").write_text("")

    # make_client 会 reload 模块并 monkeypatch load_car_config；先捕获 reload 前的真函数
    arena_mod = importlib.import_module("routers.arena")
    real_load_car_config = arena_mod.load_car_config
    real_load_config = arena_mod.load_config

    client, arena = make_client(monkeypatch)
    monkeypatch.setattr(arena, "load_car_config", real_load_car_config)

    calls = {"count": 0}

    def counting_load_config(config_file):
        calls["count"] += 1
        return real_load_config(config_file)

    monkeypatch.setattr(arena, "load_config", counting_load_config)

    # 3 条记录、3 个不同 record_index：每次 predict 都走完整 config 路径
    monkeypatch.setattr(arena.tub_router, "current_records", [
        {"_index": i, "cam/image_array": f"{i}_cam_image_array_.jpg", "user/angle": 0.1, "user/throttle": 0.2}
        for i in range(3)
    ])

    model_path = tmp_path / "pilot.tflite"
    model_path.write_text("model")
    load_response = client.post(
        "/api/arena/pilots/load",
        json={
            "model_path": str(model_path),
            "model_type": "tflite_linear",
            "config_path": str(tmp_path),
        },
    )
    assert load_response.status_code == 200, load_response.text
    pilot_id = load_response.json()["pilot"]["id"]

    for record_index in range(3):
        response = client.post(
            f"/api/arena/pilots/{pilot_id}/predict",
            json={"record_index": record_index, "config_path": str(tmp_path)},
        )
        assert response.status_code == 200, response.text

    # load 时编译 1 次；三次 predict 全部命中 mtime 缓存，不得重复编译
    assert calls["count"] == 1, f"config 被重复编译 {calls['count']} 次"
```

- [ ] **Step 2: 运行新测试**

Run: `cd web_ui/backend && python -m pytest tests/test_arena.py::test_predict_does_not_reload_config_per_frame -v`
Expected: `1 passed`

- [ ] **Step 3: 运行整个 test_arena.py**

Run: `cd web_ui/backend && python -m pytest tests/test_arena.py -q`
Expected: 全绿（17 个既有测试 + 新 1 例 = 18 passed）

- [ ] **Step 4:（可选）变异验证护栏有效性**

临时把 `routers/arena.py` 的 mtime 缓存失效（如把 `_config_stamp` 改成每次不同），跑新测试应失败（`config 被重复编译 4 次`）；改回后跑绿再提交。生产文件用完必须 `git checkout` 还原。

- [ ] **Step 5: Commit**

```bash
git add web_ui/backend/tests/test_arena.py
git commit -m "test(arena): predict 逐帧不重编译 car config 的 API 级回归护栏"
```

---

### Task 3: 真实模型集成测试（opt-in，本机实测 DKG-1）

**Files:**
- Create: `web_ui/backend/tests/integration/test_arena_real_model.py`
- Create: `web_ui/backend/tests/integration/__init__.py`（空文件）

用本机真实工程 `/home/dkc/projects/mycar`（DKG-1.tflite）做三件事：①热缓存单帧 predict 时延 < 30ms 预算（实测基线 ~1.7ms，预算留 15× 余量防 CI 机器抖动）；②`load_config` 全程只执行 1 次；③预测阶段 `donkeycar.config` 无一条 "loading config" 日志（直接消灭用户看到的刷屏症状）。

opt-in 门控：`ARENA_INTEGRATION=1` 才运行，默认套件中显示 skipped、不污染常规基线。predict 缓存按 (pilot, record_index, options) 键控，故用 20 条假记录、测量阶段只遍历 index 3..19（预热用 0..2），保证每帧都是**真实模型 invoke** 而非缓存命中。

- [ ] **Step 1: 创建 `__init__.py`**

```bash
cd web_ui/backend && mkdir -p tests/integration && touch tests/integration/__init__.py
```

- [ ] **Step 2: 创建集成测试文件（完整内容，已按执行期修正同步：计数包装器必须先于预取安装——预取会填满模块级 mtime 缓存；循环断言带响应文本；尾部卸载 pilot）**

`web_ui/backend/tests/integration/test_arena_real_model.py`:

```python
"""真实模型集成测试（opt-in）：需要本机存在 mycar 工程与 DKG-1 模型。

运行方式（默认跳过，不污染常规套件）：
    cd web_ui/backend && ARENA_INTEGRATION=1 python -m pytest tests/integration/test_arena_real_model.py -v
"""
import importlib
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(
    os.environ.get("ARENA_INTEGRATION") != "1",
    reason="opt-in 集成测试：需真实 mycar 工程与 DKG-1 模型（ARENA_INTEGRATION=1 启用）",
)

MYCAR = Path(os.environ.get("MYCAR_DIR", "/home/dkc/projects/mycar"))
MODEL = MYCAR / "models" / "DKG-1.tflite"


def test_real_model_predict_latency_and_config_cache(caplog, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    arena = importlib.import_module("routers.arena")
    app = FastAPI()
    app.include_router(arena.router, prefix="/api/arena")
    client = TestClient(app)

    # 计数真实 load_config（必须先于预取安装：预取会填满模块级 mtime 缓存）
    real_load_config = arena.load_config
    calls = {"count": 0}

    def counting_load_config(config_file):
        calls["count"] += 1
        return real_load_config(config_file)

    monkeypatch.setattr(arena, "load_config", counting_load_config)

    cfg = arena.load_car_config(str(MYCAR))

    # 图像与记录用按配置形状的占位数据
    monkeypatch.setattr(
        arena,
        "load_record_image",
        lambda record: np.zeros(
            (cfg.IMAGE_H, cfg.IMAGE_W, getattr(cfg, "IMAGE_DEPTH", 3)), dtype=np.uint8
        ),
    )
    monkeypatch.setattr(
        arena.tub_router,
        "current_records",
        [
            {
                "_index": i,
                "cam/image_array": f"{i}_cam_image_array_.jpg",
                "user/angle": 0.0,
                "user/throttle": 0.0,
            }
            for i in range(20)
        ],
    )
    monkeypatch.setattr(arena.tub_router, "current_tub_path", str(MYCAR))

    load_response = client.post(
        "/api/arena/pilots/load",
        json={
            "model_path": str(MODEL),
            "model_type": "tflite_linear",
            "config_path": str(MYCAR),
        },
    )
    assert load_response.status_code == 200, load_response.text
    pilot_id = load_response.json()["pilot"]["id"]

    def predict(index):
        return client.post(
            f"/api/arena/pilots/{pilot_id}/predict",
            json={"record_index": index, "config_path": str(MYCAR)},
        )

    with caplog.at_level(logging.INFO, logger="donkeycar.config"):
        for i in range(3):  # 预热（index 0..2）
            response = predict(i)
            assert response.status_code == 200, response.text

        start = time.perf_counter()
        for i in range(3, 20):  # 测量段：index 3..19，每帧都是真实模型 invoke
            response = predict(i)
            assert response.status_code == 200, response.text
        mean_ms = (time.perf_counter() - start) / 17 * 1000

    config_log_lines = [r for r in caplog.records if "loading config" in r.getMessage()]
    assert config_log_lines == [], f"predict 期间 config 日志刷屏：{len(config_log_lines)} 条"
    assert calls["count"] == 1, f"load_config 实际执行 {calls['count']} 次（应为 1 次）"
    assert mean_ms < 30, f"热缓存单帧 predict {mean_ms:.1f}ms，超出 30ms 预算"

    # 测试卫生：卸载真实 pilot，避免模块级残留影响同进程其它测试
    assert client.delete(f"/api/arena/pilots/{pilot_id}").status_code == 200
```

- [ ] **Step 3: 默认套件确认门控生效（显示 skip）**

Run: `cd web_ui/backend && python -m pytest tests/ -q`
Expected: `345 passed, 3 skipped in ...`（2 既有 skip + 1 新 integration skip；345 = Task 1/2 后的基线）

- [ ] **Step 4: 开启门控运行，记录实测数字**

Run: `cd web_ui/backend && ARENA_INTEGRATION=1 python -m pytest tests/integration/test_arena_real_model.py -v`
Expected: `1 passed`；本机实测热缓存单帧 ~3.5ms（预算 30ms），将数字记入报告/提交信息。

- [ ] **Step 5: Commit**

```bash
git add web_ui/backend/tests/integration/
git commit -m "test(arena): opt-in 真实模型集成测试（DKG-1 时延<30ms、config 单次加载、无日志刷屏）"
```

---

### Task 4: 前端组件测试——摘要面板渲染

**Files:**
- Create: `web_ui/frontend/src/pages/PilotArenaPage.test.tsx`

测试真实渲染流：注入 store 记录 → mock api → 加载模型 → 生成曲线 → 断言摘要面板（`renderMetricSeries` 输出）。沿用仓库既有惯例（`DrifterConsolePage.test.tsx`：`vi.mock('@/i18n')` + `vi.mock('@/services/api')` + `fireEvent`，无 user-event 依赖）。i18n mock 的 `t` 做 `{v}/{n}` 插值，便于断言具体数值文本。

关键事实（已核实源码）：
- 模型选择器包在 `<label>` 里，可访问名 = `t('arena.modelFile')`；页面共 **4 个 combobox**（列数、模型类型、模型文件、曲线 pilot），其中曲线 pilot 选择器无 label，须按 option 文本定位（索引定位会因 DOM 顺序漂移）。
- 摘要面板渲染条件：`plotSummary && (plotSummary.angle || plotSummary.throttle)`（`PilotArenaPage.tsx:1160`）——两侧全 null 时整块不渲染；单侧 null 时该侧显示 `arena.metricNoData`。
- 需要 polyfill `requestAnimationFrame`（jsdom 默认无）；canvas 为 null ctx 时 `drawViewerFrame` 有守卫，无需 canvas mock。

- [ ] **Step 1: 创建测试文件（完整内容）**

`web_ui/frontend/src/pages/PilotArenaPage.test.tsx`:

```tsx
import '@testing-library/jest-dom/vitest';
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { PilotArenaPage } from './PilotArenaPage';

// mock chart.js 的 Chart 构造器：只记录 config，不真正渲染 canvas
// （jsdom 无 canvas 实现，真实 Chart 构造会非确定性地抛 "can't acquire context"）。
// 沿用 TelemetryChart.test.tsx 惯例；覆盖直接 import chart.js 的模块。
// 注意：本文件里真实 Chart 构造路径已被下面的 react-chartjs-2 mock 切断，
// 此 chart.js mock 属防御性兜底；但 react-chartjs-2 的 mock 不可删——
// 删除后真实 chart.js 会在 jsdom 下随机崩溃（flake 复发）。
vi.mock('chart.js', () => {
  class MockChart {
    static register = vi.fn();
    update = vi.fn();
    destroy = vi.fn();
    config: { data?: { labels?: unknown; datasets?: unknown[] }; options?: Record<string, unknown> };
    data: { labels?: unknown; datasets?: unknown[] } | undefined;
    options: Record<string, unknown>;
    constructor(_ctx: unknown, config: { data?: { labels?: unknown; datasets?: unknown[] }; options?: Record<string, unknown> }) {
      this.config = config;
      this.data = config.data;
      this.options = config.options ?? {};
    }
  }
  return {
    Chart: MockChart,
    LineController: class {}, BarController: class {}, RadarController: class {},
    DoughnutController: class {}, PolarAreaController: class {}, BubbleController: class {},
    PieController: class {}, ScatterController: class {},
    CategoryScale: {}, LinearScale: {}, PointElement: {}, LineElement: {},
    Title: {}, Legend: {}, Tooltip: {},
  };
});

// 关键：本页经 react-chartjs-2 渲染 <Line>。react-chartjs-2 是外部化依赖
// （vitest 默认 externalize node_modules），其内部 import 的 chart.js 不经过
// 上面的 vi.mock 注册表，真实 chart.js 仍会被加载并在 jsdom 下随机崩溃。
// 因此直接 mock react-chartjs-2：PilotArenaPage 只用到 Line 导出，
// 以返回 null 的组件替代，彻底绕开 canvas 渲染。
vi.mock('react-chartjs-2', () => ({
  Line: () => null,
}));

vi.mock('@/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${String(opts.v ?? opts.n ?? opts.value ?? '')}` : key,
    lang: 'zh',
  }),
}));
vi.mock('@/services/api', () => ({
  getArenaPredictions: vi.fn(),
  getImageUrl: vi.fn((path: string) => `http://localhost:5188/api/tub/image?path=${encodeURIComponent(path)}`),
  listArenaModels: vi.fn(),
  listArenaModelTypes: vi.fn(),
  loadArenaPilot: vi.fn(),
  predictArenaPilot: vi.fn(),
  unloadArenaPilot: vi.fn(() => Promise.resolve()),
  getApiErrorMessage: vi.fn((error: unknown) => String(error)),
}));
import * as api from '@/services/api';
import { useStore } from '../store/useStore';

const summaryFixture = {
  angle: { count: 1, mae: 0.15, rmse: 0.15, bias: 0.15, max_abs_error: 0.15 },
  throttle: { count: 1, mae: 0.3, rmse: 0.3, bias: 0.3, max_abs_error: 0.3 },
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal(
    'requestAnimationFrame',
    (cb: FrameRequestCallback) => window.setTimeout(() => cb(performance.now()), 0),
  );
  vi.stubGlobal('cancelAnimationFrame', (handle: number) => window.clearTimeout(handle));
  useStore.setState({
    configPath: '/tmp/tub',
    tubPath: '/tmp/tub',
    records: [
      { _index: 0, _timestamp_ms: 0, 'cam/image_array': '0_cam_image_array_.jpg', 'user/angle': 0.1, 'user/throttle': 0.2 },
    ],
    currentIndex: 0,
    config: null,
    isPlaying: false,
    isLooping: false,
  });
  vi.mocked(api.listArenaModelTypes).mockResolvedValue(['tflite_linear']);
  vi.mocked(api.listArenaModels).mockResolvedValue({
    models: [{ path: '/tmp/DKG-1.tflite', name: 'DKG-1.tflite' }],
  } as unknown as Awaited<ReturnType<typeof api.listArenaModels>>);
  vi.mocked(api.loadArenaPilot).mockResolvedValue({
    status: true,
    pilot: {
      id: 'pilot-1',
      name: 'DKG-1.tflite',
      model_path: '/tmp/DKG-1.tflite',
      model_type: 'tflite_linear',
      loaded_at: '2026-09-04T00:00:00Z',
    },
  } as unknown as Awaited<ReturnType<typeof api.loadArenaPilot>>);
  vi.mocked(api.predictArenaPilot).mockResolvedValue({
    status: true,
    record_index: 0,
    user: { angle: 0.1, throttle: 0.2 },
    pilot: { angle: 0.25, throttle: 0.5 },
  } as unknown as Awaited<ReturnType<typeof api.predictArenaPilot>>);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function loadPilotAndGeneratePlot() {
  render(<PilotArenaPage />);
  const loadButton = await screen.findByRole('button', { name: 'arena.loadAndPredict' });
  await waitFor(() => expect(loadButton).toBeEnabled());
  fireEvent.click(loadButton);
  await waitFor(() => expect(api.loadArenaPilot).toHaveBeenCalled());

  // 曲线 pilot 选择器无 label；页面有 4 个 combobox，按 option 文本稳健定位
  const plotSelect = screen.getAllByRole('combobox').find((select) =>
    within(select).queryByText('arena.selectLoadedPilot'),
  );
  if (!plotSelect) throw new Error('未找到曲线 pilot 选择器');
  fireEvent.change(plotSelect, { target: { value: 'pilot-1' } });
  fireEvent.click(screen.getByRole('button', { name: 'arena.generatePlot' }));
  await waitFor(() => expect(api.getArenaPredictions).toHaveBeenCalled());
}

describe('PilotArenaPage 模型贴合摘要', () => {
  it('生成曲线后渲染 angle/throttle 两侧误差指标', async () => {
    vi.mocked(api.getArenaPredictions).mockResolvedValue({
      points: [
        { index: 0, user_angle: 0.1, user_throttle: 0.2, pilot_angle: 0.25, pilot_throttle: 0.5 },
      ],
      summary: summaryFixture,
    } as unknown as Awaited<ReturnType<typeof api.getArenaPredictions>>);

    await loadPilotAndGeneratePlot();

    expect(api.getArenaPredictions).toHaveBeenCalledWith(
      'pilot-1',
      expect.objectContaining({ config_path: '/tmp/tub', limit: 200 }),
    );
    expect(await screen.findByText('arena.plotSummary')).toBeInTheDocument();
    expect(screen.getByText('arena.metricMae:0.150')).toBeInTheDocument();
    expect(screen.getByText('arena.metricMae:0.300')).toBeInTheDocument();
    expect(screen.getByText('arena.metricRmse:0.150')).toBeInTheDocument();
    expect(screen.getByText('arena.metricRmse:0.300')).toBeInTheDocument();
    expect(screen.getByText('arena.metricBias:+0.150')).toBeInTheDocument();
    expect(screen.getByText('arena.metricMaxErr:0.300')).toBeInTheDocument();
    expect(screen.getAllByText('arena.metricFrames:1')).toHaveLength(2);
  });

  it('单侧无数据时该侧显示无数据占位，另一侧正常展示', async () => {
    vi.mocked(api.getArenaPredictions).mockResolvedValue({
      points: [],
      summary: { angle: null, throttle: summaryFixture.throttle },
    } as unknown as Awaited<ReturnType<typeof api.getArenaPredictions>>);

    await loadPilotAndGeneratePlot();

    expect(await screen.findByText('arena.plotSummary')).toBeInTheDocument();
    expect(screen.getByText('arena.metricAngle: arena.metricNoData')).toBeInTheDocument();
    expect(screen.getByText('arena.metricMae:0.300')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 运行新测试（含稳定性复跑——本页有 chart.js flake 历史，必须连跑多轮全绿才算过）**

Run: `cd web_ui/frontend && npx vitest run src/pages/PilotArenaPage.test.tsx`
Expected: `2 passed`；再连跑 5–10 次（`for i in $(seq 1 10); do npx vitest run src/pages/PilotArenaPage.test.tsx 2>&1 | tail -2; done`）全部 `2 passed` 且无 "Failed to create chart"。

- [ ] **Step 3: 类型与静态检查**

Run: `cd web_ui/frontend && npm run check`
Expected: 无错误（若 store `records` 字面量与 `TubRecord` 类型不兼容——该类型必填 `_index`/`_timestamp_ms`——按 `npm run check` 报错在测试文件内调整，勿改生产代码）。注意：repo-wide `npm run lint` 有 2 个既有 error（`TubEditor.tsx:1538`、`SimCollectCard.test.tsx:28`），与本任务无关、不需修；只要求新文件零 lint 报错。

- [ ] **Step 4: 全量前端回归**

Run: `cd web_ui/frontend && npx vitest run`
Expected: `160 passed`（vitest 4 不支持 `-q` 参数）

- [ ] **Step 5: Commit**

```bash
git add web_ui/frontend/src/pages/PilotArenaPage.test.tsx
git commit -m "test(arena): PilotArenaPage 摘要面板组件测试（两侧指标 + 单侧无数据）"
```

---

### Task 5: Playwright 浏览器 E2E（route-mocked 真实 UI 流）

**Files:**
- Create: `web_ui/frontend/playwright.config.ts`
- Create: `web_ui/frontend/e2e/pilot-arena.spec.ts`

E2E 覆盖真实浏览器中的完整 UI 流：加载配置 → SidePanel 加载 Tub → 选模型 → 加载并预测 → 生成曲线 → 摘要面板可见。后端用 `page.route('**/api/**')` 全量 stub（真实 i18n，配置 `locale: 'zh-CN'` 锁定中文文案）。

执行期修正（均已落库）：
- **config 前置**：`加载 Tub` 按钮 `disabled={!config}`（TubLoader.tsx:92），须先 mock `/config/load` 并走「配置路径输入框 → 加载配置」流程。
- **`/drift/state` mock**：DriftCard 以 10Hz 轮询，空对象会使 `state.events.length`（DriftCard.tsx:442）抛 TypeError → ErrorBoundary 全页崩溃「出错了。」。
- **`/arena/models` 返回 2 个模型**：页面 auto-load 仅在 `models.length === 1` 时触发（PilotArenaPage.tsx:638-645），双模型跳过 auto-load，使「加载并预测」点击成为真实因果步骤。
- **未命中端点 404 响亮失败**：fallback 返回 404 + `unmocked endpoint`，契约漂移不再被静默吞掉。
- **vitest 隔离**：`vite.config.ts` test 块需 `exclude: [...configDefaults.exclude, 'e2e/**']`（覆盖默认值会导致收集 node_modules），见 Step 5。

已核实：`loadTub` = `POST /tub/load`；PilotArenaPage 由 FlowPage 无条件渲染，FlowPage 挂在兜底路由 `path="*"`（`App.tsx:89`）；SidePanel 挂载于 `App.tsx:79`。

风险与回退：`npx playwright install chromium` 需下载 ~170MB；若网络/系统库不可用导致启动失败，**标记本任务 blocked**，回退依赖 Task 3 的实测时延 + Task 6 手工清单，不阻塞整体交付。

- [ ] **Step 1: 下载 Chromium**

Run: `cd web_ui/frontend && npx playwright install chromium`
Expected: 下载完成、无报错。失败则回退（见上）。

- [ ] **Step 2: 创建 `playwright.config.ts`（完整内容）**

```ts
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: 'http://localhost:5188',
    locale: 'zh-CN',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5188',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
```

- [ ] **Step 3: 创建 `e2e/pilot-arena.spec.ts`（完整内容）**

```ts
import { test, expect } from '@playwright/test';

const tubResponse = {
  path: '/tmp/tub',
  records: [
    { _index: 0, _timestamp_ms: 0, 'cam/image_array': '0_cam_image_array_.jpg', 'user/angle': 0.1, 'user/throttle': 0.2 },
  ],
  fields: ['cam/image_array', 'user/angle', 'user/throttle'],
  total_physical_records: 1,
};

const summary = {
  angle: { count: 1, mae: 0.15, rmse: 0.15, bias: 0.15, max_abs_error: 0.15 },
  throttle: { count: 1, mae: 0.3, rmse: 0.3, bias: 0.3, max_abs_error: 0.3 },
};

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    let body: unknown;
    if (pathname.endsWith('/tub/load') || pathname.endsWith('/tub/records')) {
      body = tubResponse;
    } else if (pathname.endsWith('/config/load')) {
      body = { config: { DRIVE_LOOP_HZ: 60 } };
    } else if (pathname.endsWith('/drift/state')) {
      // Drive 区的 DriftCard 以 10Hz 轮询此端点并在 state.events 上取 .length
      // （DriftCard.tsx:442）；空对象会令整个 App 崩进 ErrorBoundary，必须给合法空闲态。
      body = {
        state: 'idle',
        calibration_ready: false,
        camera_running: false,
        beta_deg: null,
        pose: null,
        telemetry_count: 0,
        camera_fps: 0,
        frames_written: 0,
        events: [],
        config: {},
      };
    } else if (pathname.endsWith('/arena/model-types')) {
      body = { model_types: ['tflite_linear', 'linear'] };
    } else if (pathname.endsWith('/arena/models')) {
      // 返回 2 个模型：PilotArenaPage 的 auto-load 只在 models.length === 1 时触发
      // （PilotArenaPage.tsx:638-645），双模型让它跳过自动加载，
      // 『加载并预测』点击成为真实因果步骤。
      body = {
        models: [
          { path: '/tmp/DKG-1.tflite', name: 'DKG-1.tflite' },
          { path: '/tmp/DKG-2.tflite', name: 'DKG-2.tflite' },
        ],
      };
    } else if (pathname.endsWith('/arena/pilots/load')) {
      body = {
        pilot: {
          id: 'pilot-1',
          name: 'DKG-1.tflite',
          model_path: '/tmp/DKG-1.tflite',
          model_type: 'tflite_linear',
          loaded_at: '2026-09-04T00:00:00Z',
        },
      };
    } else if (/\/arena\/pilots\/pilot-1\/predict$/.test(pathname)) {
      body = {
        status: true,
        record_index: 0,
        user: { angle: 0.1, throttle: 0.2 },
        pilot: { angle: 0.25, throttle: 0.5 },
      };
    } else if (pathname.endsWith('/arena/pilots/pilot-1/predictions')) {
      body = {
        points: [
          { index: 0, user_angle: 0.1, user_throttle: 0.2, pilot_angle: 0.25, pilot_throttle: 0.5 },
        ],
        summary,
      };
    } else {
      // 未 mock 的端点响亮失败：静默空对象会掩盖组件对真实响应结构的假设
      await route.fulfill({ status: 404, json: { detail: `unmocked endpoint: ${pathname}` } });
      return;
    }
    await route.fulfill({ json: body });
  });
  await page.goto('/');
});

test('加载 Tub → 加载模型 → 生成曲线 → 展示模型贴合摘要', async ({ page }) => {
  // ConfigLoader：TubLoader 的『加载 Tub』按钮在 config 未加载时禁用
  // （TubLoader.tsx:92 disabled={!config}），真实 UI 流程必须先加载配置。
  await page.getByRole('textbox', { name: '配置路径输入框' }).fill('/tmp/car');
  await page.getByRole('button', { name: '加载配置' }).click();

  // setConfig 会收起侧栏抽屉（useStore.ts:190 activeDrawer: null），
  // 且配置加载后会自动连带加载 <car>/data Tub；等 PA 当前数据卡出现
  // 『Tub: /tmp/tub』即代表 config + auto-tub 均已完成、抽屉已关闭。
  await expect(page.getByText('Tub: /tmp/tub').first()).toBeVisible();

  // 重新打开抽屉，操作 SidePanel 的 TubLoader（真实中文 aria-label）
  await page.getByRole('button', { name: '加载器' }).click();
  await page.getByRole('textbox', { name: 'Tub 路径输入框' }).fill('/tmp/tub');
  await page.getByRole('button', { name: '加载 Tub' }).click();

  // 模型选择器（包在 <label>『模型文件』内）
  const modelSelect = page.getByRole('combobox', { name: '模型文件' });
  await expect(modelSelect.getByRole('option', { name: 'DKG-1.tflite' })).toBeAttached();
  await modelSelect.selectOption('/tmp/DKG-1.tflite');
  await page.getByRole('button', { name: '加载并预测' }).click();

  // predict 返回后 pilot 栏显示 0.250
  await expect(page.getByText('0.250').first()).toBeVisible();

  // 曲线 pilot 选择器无 label；页面有多个 combobox，按 option 文本稳健定位
  const plotSelect = page.getByRole('combobox').filter({
    has: page.getByRole('option', { name: '选择已加载 Pilot' }),
  });
  await plotSelect.selectOption('pilot-1');
  await page.getByRole('button', { name: '生成曲线' }).click();

  await expect(page.getByText('模型贴合摘要（误差 = pilot − 用户）')).toBeVisible();
  await expect(page.getByText('MAE 0.150').first()).toBeVisible();
  await expect(page.getByText('MAE 0.300').first()).toBeVisible();
});
```

- [ ] **Step 4: 运行 E2E**

Run: `cd web_ui/frontend && npx playwright test`
Expected: `1 passed`（首次可能提示缺系统库：`Host system is missing dependencies` → 需 `npx playwright install-deps chromium`（要 sudo）→ 无 sudo 则按回退方案处理）

- [ ] **Step 5: vitest 隔离 + gitignore Playwright 产物（执行期新增，独立提交）**

不隔离时 `npx vitest run` 会把 `e2e/pilot-arena.spec.ts` 误收集为 vitest 用例（它 import `@playwright/test`）而失败。`web_ui/frontend/vite.config.ts` 的 test 块追加（**注意**：显式 `exclude` 会整体覆盖 vitest 默认排除——node_modules 等——必须合并 `configDefaults`）：

```ts
import { configDefaults } from 'vitest/config'
// test 块内：
    // 注意：显式 exclude 会整体覆盖 vitest 默认排除（node_modules 等），必须合并
    exclude: [...configDefaults.exclude, 'e2e/**'],
```

根目录 `.gitignore` 增补：

```
# Playwright 运行产物
web_ui/frontend/test-results/
web_ui/frontend/playwright-report/
```

Run: `cd web_ui/frontend && npx vitest run`
Expected: `160 passed`，不收集 e2e/；`npm run check` 无新增错误（e2e/ 不在 tsconfig type-check 范围）

- [ ] **Step 6: Commit（实际为两个提交）**

```bash
git add web_ui/frontend/playwright.config.ts web_ui/frontend/e2e/pilot-arena.spec.ts
git commit -m "test(arena): Playwright E2E——Tub→模型→曲线→摘要面板全流程（route-mocked）"
git add web_ui/frontend/vite.config.ts .gitignore
git commit -m "test(web-ui): vitest 排除 e2e/ 目录并 gitignore Playwright 产物"
```

---

### Task 6: 可选环境补齐 + 手工验收清单（交付后收尾）

**Files:** 无（本机环境操作 + 手工清单）

- [ ] **Step 1:（可选）Linux 本机安装 pupil_apriltags，解除 2 例 skip**

Run: `cd web_ui/backend && pip install pupil-apriltags`
- 成功 → `python -m pytest tests/test_apriltag_generator.py tests/test_drift_vision.py::TestDetectorDownscale -q`，预期全绿；再跑全量记录新数字。
- 源码编译失败（Python 3.11 无预编译 wheel）→ 保持现状：这 2 例在 Windows 开发机（已装该库）上覆盖，不阻塞。
- **纪律**：仅装本机环境，不改 `pyproject.toml`/依赖清单（该依赖是 dev-machine 层面的既有约定）。

- [ ] **Step 2: 手工验收清单（用户 Windows 机器，真实 DKG-1）**

| # | 操作 | 预期 |
|---|------|------|
| 1 | `cd web_ui/backend && python main.py` 重启后端 | 启动正常 |
| 2 | `cd web_ui/frontend && npm run build` | 构建成功 |
| 3 | 浏览器 Ctrl+F5 进 Pilot Arena，加载 DKG-1 | 推理徽标 ≈50–60 FPS（原 4–5） |
| 4 | 观察后端控制台 10 秒 | 除启动外**无** `INFO:donkeycar.config:loading config` |
| 5 | 4 列 viewer 同时播放 | 无卡顿；若卡顿在 myconfig 设 `ARENA_PREDICTION_INTERVAL_MS=33~50` 后复测 |
| 6 | Tub Plot 生成曲线 | 摘要面板 MAE/RMSE/bias/max/帧数与手算一致 |

- [ ] **Step 3: 更新 CHANGELOG 与 handoff**

测试全绿后：`CHANGELOG.md` 增补 `## 2026-09-04 (175)` 条目下的测试明细；`docs/guide/pilot-arena-handoff.md` 的「明早核对清单」逐项打勾。

---

## 执行顺序与依赖

- 顺序：1 → 2 → 3 → 4 → 5 → 6（无跨任务依赖，任何单任务完成即可独立合并）。
- 验证矩阵：每个任务都有"运行命令 + 预期输出"，提交前全量回归一次后端（`cd web_ui/backend && python -m pytest tests/ -q`）与前端（`npx vitest run && npm run check`；`npm run lint` 仅要求本工作文件零新增——repo 有 2 个预存 error：`TubEditor.tsx:1538`、`SimCollectCard.test.tsx:28`，与本工作无关）。

## 自审记录

- **覆盖对照**：原痛点①4~5FPS → Task 3 实测时延护栏（<30ms 预算）+ Task 6 手工徽标验收；②每帧 config 日志刷屏 → Task 2 计数护栏 + Task 3 caplog 断言 0 条；③新功能摘要 → Task 4 组件测试 + Task 5 E2E 全流程；④并发/节流旋钮 → Task 6 手工 4 列负载（自动化留待后续专项，避免过度工程）。
- **占位符扫描**：无 TBD/TODO；所有代码块完整可粘贴执行。
- **类型一致性**：metric 字段 `count/mae/rmse/bias/max_abs_error` 与 `compute_prediction_metrics`（routers/arena.py）、`ArenaMetricSummary`（services/api.ts:599）、`renderMetricSeries`（PilotArenaPage.tsx:785）三处一致；接口字段 `model_path/model_type/loaded_at` 与 `ArenaPilot`（api.ts:576）一致。
