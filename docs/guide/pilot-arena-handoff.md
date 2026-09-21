# Pilot Arena（Web UI 模型对比台）交接与后续工作

> 用途：供后续 AI/开发者继续开展 Pilot Arena 相关工作。首次建立 2026-09-04（本会话完成"推理链路性能优化 + 模型贴合摘要"）。
> 测试基线：后端 `cd web_ui/backend && python -m pytest tests/ -q` 本机 **340 passed + 2 skipped**（4 例 `TestAdaptiveDetection` 失败为本机 pupil_apriltags 缺失的既有环境问题，见 §6）；前端 `cd web_ui/frontend && npx vitest run` **158 passed**（27 文件）+ `tsc -b` + `npm run build` 全绿。
> 同日测试体系补齐后：本机已装 `pupil-apriltags` 1.0.4，后端 **351 passed + 1 skipped**（仅剩 opt-in 集成测试，`ARENA_INTEGRATION=1` 时 1 passed、实测 4.23ms/帧）；前端 **160 passed**（28 文件）+ Playwright E2E **1 passed**（详见 `docs/superpowers/plans/2026-09-04-pilot-arena-testing.md` 执行记录）。

## 0. 文档地图

| 文档 | 用途 |
| --- | --- |
| `docs/plan/pilot-arena-web-ui-migration.md` | 总体迁移/优化方案（MVP 已落地；§3.3 为后续候选） |
| **本文档** | 当前状态 + 调用链速览 + 成果/经验/教训 + 遗留核对项 |

## 1. 一句话架构与热路径

Web 前端 `/pilot`（`web_ui/frontend/src/pages/PilotArenaPage.tsx`，经 `FlowPage.tsx` 懒加载）⇄ `POST /api/arena/...`（`web_ui/backend/routers/arena.py`）。模型加载一次（`POST /pilots/load` → `get_model_by_type` → `TfLite.load`，实例存全局 `loaded_pilots`）；播放/滑帧时逐帧 `POST /pilots/{id}/predict`（未命中预测缓存才计算）。

后端单帧 predict 热路径（2026-09-04 优化后实测，DKG-1.tflite 120×160 float32）：
`_predict_loaded_pilot`（arena.py）= record 查找 → `load_car_config`（**mtime 缓存命中**，µs 级）→ 磁盘读图+PIL 解码（~0.1ms）→ `pilot.run`（normalize + TFLite invoke，~1.3ms）→ 写预测缓存。合计 **≈1.7ms/帧（≈580FPS 当量）**。

## 2. 2026-09-04 成果（性能优化 + 新功能）

### 2.1 推理瓶颈分解（实测，勿再猜）

| 环节 | 耗时 | 结论 |
| --- | --- | --- |
| 裸 TFLite invoke | 1.24 ms（≈807FPS） | 模型本身非瓶颈 |
| `pilot.run()`（归一化+推理） | 1.33 ms（≈750FPS） | Python 侧冗余 ~0.09ms，**不值得动 donkeycar 核心**（影响训练/h5 路径） |
| 单帧 JPEG 解码 | 0.09 ms | 无需图片缓存 |
| **`load_config()` 每次执行** | **≈75–80 ms** | 原占总耗时 ~97%（config.py+myconfig.py 全量重编译） |
| 前端评估节流下限 | 250ms → 观察"4~5FPS" | 硬上限 4Hz |

### 2.2 已落地改动（全部工作区未提交，待 review）

- **后端 config 缓存**（`web_ui/backend/routers/arena.py`）：`load_car_config` 按 (config.py, myconfig.py) **mtime 缓存**（模块级 `_car_config_cache` + `_car_config_lock`，变化即失效重载，含锁内二次确认）。predict/preview/批量/load 全走此函数 → config INFO 日志只在首次/保存配置后出现一次。
- **前端评估节流**（`PilotArenaPage.tsx`）：下限 250ms→**16ms**（评估节奏=逐帧播放 `DRIVE_LOOP_HZ`）；新增旋钮 `ARENA_PREDICTION_INTERVAL_MS`（fallback 常量）；`ARENA_INFERENCE_CONCURRENCY` 上限 2→4。
- **新功能·模型贴合摘要**（规划 §3.3）：`POST /pilots/{id}/predictions` 响应新增 `summary`（angle/throttle 各自 MAE/RMSE/bias=pilot−user/max|err|/count，非有限帧剔除；纯函数 `compute_prediction_metrics`）；前端 Tub Plot 图下展示（i18n zh/en 各 10 词条，`arena.metric*`/`arena.plotSummary`）。

### 2.3 性能评估数据

- 单帧 predict：**79ms → 1.72ms**（含 config 缓存命中+解码+推理）。
- 批量 200 帧含摘要首跑 330ms（≈606FPS 当量）；摘要计算 **~0.27µs/点**（20 万点 53ms）可忽略；全缓存命中重跑 1.1ms。
- 前端 inference 徽标预期 ~4 → ≈DRIVE_LOOP_HZ（60Hz 时 ~60）；**浏览器端待人工确认**。

### 2.4 测试

`test_arena.py` +4（config 缓存语义 1：未变化复用同一对象/mtime 变化重载；摘要 3：偏差口径、非有限剔除、接口含 summary），TDD 先红后绿。

2026-09-04 当日补齐的完整分层体系（六任务计划见 `docs/superpowers/plans/2026-09-04-pilot-arena-testing.md`，已全部提交分支 `test/pilot-arena-testing`）：

| 层 | 内容 | 结果 |
| --- | --- | --- |
| 测试基建修复 | `TestAdaptiveDetection` 4 例替身注入（`raising=False` + 可用性守卫） | 后端全量 351 passed |
| API 回归护栏 | `test_arena.py` +54 行：predict 逐帧不重编译 config（计数 + caplog 0 条） | passed |
| 真实模型集成 | `tests/integration/test_arena_real_model.py`（opt-in，真实 DKG-1） | 1 passed，4.23ms/帧 |
| 前端组件 | `PilotArenaPage.test.tsx` 摘要面板渲染（两侧/单侧数据） | 2 passed |
| 浏览器 E2E | Playwright route-mocked 全流程（config 前置→Tub→模型→预测→曲线→摘要） | 1 passed |

## 3. 调用链/关键符号速查

| 符号 | 位置 | 说明 |
| --- | --- | --- |
| `load_car_config` / `_car_config_cache` | arena.py | mtime 缓存（µs 级命中，变化重载） |
| `compute_prediction_metrics` / `_series_summary` | arena.py | 摘要纯函数（误差=pilot−user） |
| `predict_pilot_records` | arena.py | 批量预测端点，返回 `summary`+`points` |
| `ARENA_PREDICTION_MIN_INTERVAL_MS`/`predictionMinIntervalMs`/`evaluationIntervalMs` | PilotArenaPage.tsx | 推理节流（16ms 下限 + config 旋钮） |
| `plotSummary`/`renderMetricSeries` | PilotArenaPage.tsx | 摘要展示区 |
| `ArenaPredictionsResponse`/`ArenaMetricSummary` | web_ui/frontend/src/services/api.ts | 摘要类型 |

## 4. 经验（可复用方法论）

1. **先用测量把"慢"拆成数字再动手**：本问题真实瓶颈与表象（"模型 4~5FPS"）完全无关——模型 750FPS，瓶颈在每帧 config 重编译(75ms) 与前端节流(250ms)。`load_config` 一次 ~75ms 的真相只有实测才能定位。
2. **热路径重复重活 = 先缓存再谈算法**：同一 car config 文件在一秒内被逐帧重编译执行是纯浪费；按 (文件, mtime) 缓存 + 锁内二次确认，语义与"每次读最新"等价且线程安全。
3. **前端硬节流会掩盖后端真相**：250ms 节流当时是给 79ms/帧后端兜底的保护；后端提速后必须同步放开节流（250→16ms、并发上限 2→4），否则优化对用户不可见。
4. **多级缓存配合节流形成自适应速率**：前端节流+coalescing（pending 追最新帧）+ 后端预测缓存（1500/pilot）+ config mtime 缓存，四层配合使评估速率由模型实际能力决定、过载时优雅降级到每帧 coalesce。
5. **纯函数 + 接口分层便于 TDD**：摘要计算抽成 `compute_prediction_metrics`（纯函数），接口只做装配；非有限值语义在纯函数层单测闭环。

## 5. 教训（踩坑）

1. **别被症状带偏**：用户报"推理慢 4~5FPS"，若直接优化 TFLite 或换模型，方向就错了——先用 5 分钟 benchmark 分解（裸 invoke / pilot.run / 解码 / config / 前端节流）再动手。
2. **drift 链路与本机环境差异**：本机(Linux) 无 `pupil_apriltags` → `drift_vision.py:30` try 导入失败、模块无 `_PupilDetector`，4 例 `TestAdaptiveDetection` 报 AttributeError。**这是既有环境问题，与改动无关**；Windows 基线无此问题。改 drift 视觉相关前先在本机核对此差异，别误判为回归。
3. **时序敏感测试串行跑**：后端含 FakeCamera 节拍/重载宽限类测试对 CPU 调度敏感，全量回归应独占机器串行执行，勿与前端构建并行抢核。
4. **pytest 路径纪律**：web 后端测试须 `cd web_ui/backend` 再跑（依赖 tests/conftest.py 的 sys.path 注入）；仓库根 `pytest.ini` testpaths 只含 donkeycar/tests 与根 tests。

## 6. 遗留与核对项（2026-09-04 未做/待决策）

- [ ] **真机人工验收（用户 Windows 机器，待做）**：重启后端 + `npm run build` + Ctrl+F5，确认①播放时 inference 徽标 ≈DRIVE_LOOP_HZ ②config INFO 日志不再逐帧刷屏 ③4 列多 viewer 并发负载可接受（卡顿则 `ARENA_PREDICTION_INTERVAL_MS` 调到 33~50 权衡）。自动化侧（route-mocked Playwright E2E）已覆盖 UI 全流程，真机部分仍需人工。
- [ ] **决策·默认节流**：16ms 下限在多 viewer（4×60Hz）时会放大后端请求量；如实测吃紧可下调默认或文档化推荐配置。
- [x] ~~**可选**：本机 4 例 `test_drift_vision` 环境失败~~ → **已解决**（2026-09-04）：测试替身注入修复（`raising=False` + 可用性守卫置位，本不需真库）；本机另补装 `pupil-apriltags` 1.0.4，全量 351 passed。
- [ ] **可选·后续候选**（规划 §3.3 其余项）：Arena 配置持久化、多模型同图层曲线、单帧误差展示、批量任务队列/取消。
- [x] 本轮改动已全部提交于分支 `test/pilot-arena-testing`（自 345f6f7d 起，含用户 Nowhere_X 并行提交 5698f176），**未推送、未合并**，待用户决定。
