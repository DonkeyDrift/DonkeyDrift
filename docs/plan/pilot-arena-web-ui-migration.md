# Pilot Arena Web UI 迁移与优化方案

## 1. 背景与目标

旧版 Pilot Arena 已在 Kivy 管理界面中实现，核心代码位于：

- `donkeycar/management/ui/pilot_screen.py`
- `donkeycar/management/ui/pilot_screen.kv`

新版 Web UI 使用 FastAPI + React 架构，目前 `web_ui/frontend/src/components/Layout.tsx` 中只有禁用状态的 “Pilot Arena” 占位入口，尚未提供实际页面、后端 API 或模型对比能力。

本方案目标是将旧版 Pilot Arena 的核心能力迁移到新版 Web UI，让用户可以在浏览器中完成多模型加载、当前 Tub record 推理、用户控制与模型预测叠加显示，以及批量预测曲线对比。

## 2. 旧版功能分析

### 2.1 PilotLoader

`PilotLoader` 负责选择模型类型、选择模型文件并加载模型：

- 支持模型文件格式：`.h5`、`.tflite`、`.savedmodel`、`.trt`。
- 根据 `model_type` 调用 `donkeycar.utils.get_model_by_type(model_type, cfg)` 创建 pilot 实例。
- 调用 `pilot.load(model_path)` 加载模型文件。
- 成功加载后将 `[model_path, model_type]` 写入 `rc_handler.data['pilots']`，用于下次启动恢复。
- 根据模型类型调整文件过滤器：
  - `tflite`：`.tflite`
  - `tensorrt`：`.trt`、`.savedmodel`
  - 其他：`.h5`、`.savedmodel`

### 2.2 PilotBoard 与 PilotViewer

`PilotBoard` 管理多个 `PilotViewer`：

- 支持添加和移除 viewer。
- 支持 1-4 列网格布局。
- 每个 viewer 持有一个 `PilotLoader`、一张叠加预览图和一个数据面板。
- 多个 viewer 可以并排对比不同模型在同一条 record 上的推理结果。

### 2.3 OverlayImage 推理与画线

`OverlayImage.get_image()` 是旧版 Pilot Arena 的核心流程：

1. 从当前 Tub record 读取原始图像。
2. 依次执行：
   - pre transformations
   - augmentations
   - post transformations
3. 读取用户控制值：
   - `user/angle`
   - 当前 throttle field，默认 `user/throttle`
4. 使用 `donkeycar.management.makemovie.MakeMovie.draw_line_into_image()` 绘制用户控制线，颜色为绿色。
5. 如果 pilot 已加载，调用 `pilot.run(aug_img_arr)` 得到模型预测 `(angle, throttle)`。
6. 再次调用 `MakeMovie.draw_line_into_image()` 绘制模型预测线，颜色为蓝色。
7. 将预测结果写入复制后的 record，供数据面板展示。

### 2.4 图像增强与变换

旧版支持运行时调整图像处理流程：

- brightness：通过 `AUG_BRIGHTNESS_RANGE` 控制。
- blur：通过 `AUG_BLUR_RANGE` 控制。
- pre transformations：推理前变换。
- post transformations：增强后变换。

可选 transformation 包括：

- `TRAPEZE`
- `CROP`
- `RGB2BGR`
- `BGR2RGB`
- `RGB2HSV`
- `HSV2RGB`
- `BGR2HSV`
- `HSV2BGR`
- `RGB2GRAY`
- `RBGR2GRAY`
- `HSV2GRAY`
- `GRAY2RGB`
- `GRAY2BGR`
- `CANNY`
- `BLUR`
- `RESIZE`
- `SCALE`
- `GAMMANORM`

对应可复用实现：

- `donkeycar.parts.image_transformations.ImageTransformations`
- `donkeycar.pipeline.augmentations.ImageAugmentation`

### 2.5 字段映射

旧版通过 `rc_handler.data['user_pilot_map']` 将用户字段映射到 pilot 字段，例如：

- `user/angle` → `pilot/angle`
- `user/throttle` → `pilot/throttle`

迁移到 Web UI 时不建议直接复用 `rc_handler`，因为它属于 Kivy 管理 UI 层，可能带来 UI 依赖和 `.donkeyrc` 写入副作用。MVP 使用 Web 后端默认字段映射，后续再独立实现无 UI 依赖的持久化配置。

### 2.6 Tub Plot

旧版 `PilotScreen.tub_plot()` 调用：

```python
ShowPredictionPlots().plot_predictions(
    cfg=self.config,
    tub_paths=get_app_screen('tub').ids.tub_loader.file_path,
    model_path=model_path,
    limit=limit,
    model_type=model_type,
    noshow=False,
    dark=True,
)
```

该能力用于批量对比用户驾驶数据和模型预测数据。Web UI MVP 推荐优先返回 JSON 数据，由前端 Chart.js 绘制曲线；后续再考虑复用 `ShowPredictionPlots` 生成 PNG 图。

## 3. MVP 范围与非目标

### 3.1 MVP 包含

- 启用 Web UI 导航中的 “Pilot Arena” 入口。
- 新增 `/pilot` 页面。
- 列出 `models` 目录中的可用模型，支持 `.h5`、`.tflite`、`.savedmodel`、`.trt`。
- 按 `model_type` 加载和卸载多个 pilot。
- 对当前 Tub record 执行单条推理。
- 返回用户控制值与模型预测值。
- 生成带用户绿色线和模型蓝色线的预览图。
- 支持 1-4 列多模型并排显示。
- 支持 brightness、blur、pre transformations、post transformations。
- 支持批量预测数据接口，前端绘制 user/pilot angle 与 throttle 曲线。

### 3.2 非目标

MVP 不处理以下内容：

- 多用户隔离。
- 后端长期缓存大量预测结果。
- SSE 批量推理进度。
- 完整迁移 `.donkeyrc` 持久化行为。
- 完整支持所有复杂多输入模型，例如 memory、behavior、IMU、RNN、3D 输入模型。
- 高级可视化，例如 saliency map、分布统计和模型排行榜。

### 3.3 后续优化

后续可扩展：

- 独立的 Arena 配置文件，保存已加载模型、字段映射和 transformation 配置。
- 更完整的模型输入适配，复用训练/推理管线中的转换逻辑。
- 后端批量推理任务队列与取消能力。
- 多模型同图层曲线对比。
- 模型性能指标摘要，例如平均误差、最大偏差、throttle 差异统计。

## 4. 后端设计

### 4.1 新增 router

新增文件：

```text
web_ui/backend/routers/arena.py
```

在 `web_ui/backend/main.py` 中注册：

```python
from routers import config, tub, trainer, drive, arena

app.include_router(arena.router, prefix="/api/arena", tags=["arena"])
```

MVP 可以先在 `arena.py` 中维护轻量全局状态，与当前 Web UI 后端的现有风格保持一致。待逻辑变复杂后，再抽出 `web_ui/backend/arena_engine.py`。

### 4.2 状态管理

后端维护已加载 pilot 的内存字典：

```python
loaded_pilots: dict[str, LoadedPilot]
```

`LoadedPilot` 建议包含：

- `id`
- `name`
- `model_path`
- `model_type`
- `pilot`
- `loaded_at`
- `last_error`

注意：后端内存状态不应被前端持久化直接信任。页面刷新后，前端可以恢复模型路径和类型，但需要用户重新加载或提供 “Load All” 操作。

### 4.3 API 列表

#### GET `/api/arena/model-types`

返回 Web UI 可选模型类型。

MVP 可先返回常见 image-only 类型：

```json
{
  "model_types": [
    "linear",
    "categorical",
    "tflite_linear",
    "tflite_categorical",
    "tensorrt_linear",
    "tensorrt_categorical"
  ],
  "default": "linear"
}
```

#### GET `/api/arena/models`

查询参数：

- `working_dir`：car 项目目录，可选。
- `model_type`：用于按格式筛选模型，可选。

返回 `models` 目录中的模型文件。与 `web_ui/backend/routers/trainer.py` 的 `/api/trainer/models` 不同，该接口不能只显示 `.tflite`。

格式筛选建议：

| model_type | 扩展名 |
|---|---|
| 包含 `tflite` | `.tflite` |
| 包含 `tensorrt` | `.trt`、`.savedmodel` |
| 其他 | `.h5`、`.savedmodel` |

返回示例：

```json
{
  "models": [
    {
      "name": "pilot.tflite",
      "path": "/home/dkc/projects/mycar/models/pilot.tflite",
      "format": "tflite",
      "size": 123456,
      "modified": "2026-05-25T10:00:00",
      "compatible": true
    }
  ]
}
```

#### POST `/api/arena/pilots/load`

请求：

```json
{
  "model_path": "/home/dkc/projects/mycar/models/pilot.tflite",
  "model_type": "tflite_linear",
  "config_path": "/home/dkc/projects/mycar"
}
```

行为：

1. 加载 car 配置。
2. 调用 `get_model_by_type(model_type, cfg)`。
3. 调用 `pilot.load(model_path)`。
4. 生成 `pilot_id` 并保存到 `loaded_pilots`。

返回：

```json
{
  "status": true,
  "pilot": {
    "id": "pilot-abc123",
    "name": "pilot.tflite",
    "model_path": "/home/dkc/projects/mycar/models/pilot.tflite",
    "model_type": "tflite_linear"
  }
}
```

错误处理：

- 模型文件不存在：404。
- 模型类型不支持：400。
- 模型加载失败：500，并返回明确 detail。

#### GET `/api/arena/pilots`

返回当前后端内存中已加载 pilot 列表：

```json
{
  "pilots": [
    {
      "id": "pilot-abc123",
      "name": "pilot.tflite",
      "model_path": "/home/dkc/projects/mycar/models/pilot.tflite",
      "model_type": "tflite_linear",
      "loaded_at": "2026-05-25T10:00:00"
    }
  ]
}
```

#### DELETE `/api/arena/pilots/{pilot_id}`

从 `loaded_pilots` 中移除指定模型。

返回：

```json
{
  "status": true,
  "pilot_id": "pilot-abc123"
}
```

#### POST `/api/arena/pilots/{pilot_id}/predict`

请求：

```json
{
  "record_index": 0,
  "config_path": "/home/dkc/projects/mycar",
  "user_angle_field": "user/angle",
  "user_throttle_field": "user/throttle",
  "pilot_angle_field": "pilot/angle",
  "pilot_throttle_field": "pilot/throttle",
  "pre_transformations": ["CROP"],
  "augmentations": ["BRIGHTNESS"],
  "post_transformations": [],
  "brightness": 0.1,
  "blur": null
}
```

返回：

```json
{
  "status": true,
  "record_index": 0,
  "user": {
    "angle": 0.12,
    "throttle": 0.35
  },
  "pilot": {
    "angle": 0.1,
    "throttle": 0.31
  },
  "fields": {
    "user_angle": "user/angle",
    "user_throttle": "user/throttle",
    "pilot_angle": "pilot/angle",
    "pilot_throttle": "pilot/throttle"
  }
}
```

实现要点：

- 从当前已加载 Tub records 中读取 record。
- 读取图像字段，默认优先支持 `cam/image_array`。
- 按旧版顺序执行图像处理。
- 调用 `pilot.run(image)` 获取预测结果。
- 对不支持的复杂模型类型返回明确错误，不在前端静默失败。

#### GET `/api/arena/pilots/{pilot_id}/preview`

返回当前 record 的预览图。

查询参数与 predict 请求类似，可包含：

- `record_index`
- `config_path`
- `user_angle_field`
- `user_throttle_field`
- `pre_transformations`
- `augmentations`
- `post_transformations`
- `brightness`
- `blur`

行为：

- 读取 record 图像。
- 应用图像处理流程。
- 复用 `MakeMovie.draw_line_into_image()` 绘制：
  - 用户控制线：绿色 `(0, 255, 0)`
  - 模型预测线：蓝色 `(0, 0, 255)`
- 返回 PNG 或 JPEG。

#### POST `/api/arena/pilots/{pilot_id}/predictions`

用于 Tub Plot 数据。

请求：

```json
{
  "config_path": "/home/dkc/projects/mycar",
  "tub_path": "/home/dkc/projects/mycar/data",
  "start": 0,
  "limit": 1000,
  "user_angle_field": "user/angle",
  "user_throttle_field": "user/throttle"
}
```

返回：

```json
{
  "status": true,
  "limit": 1000,
  "points": [
    {
      "index": 0,
      "user_angle": 0.12,
      "user_throttle": 0.35,
      "pilot_angle": 0.1,
      "pilot_throttle": 0.31
    }
  ]
}
```

MVP 推荐返回 JSON 数据，由前端 Chart.js 绘图。后续可增加图片接口，复用 `ShowPredictionPlots().plot_predictions()`。

### 4.4 可复用工具

优先复用：

- `donkeycar.utils.get_model_by_type`
- `donkeycar.parts.image_transformations.ImageTransformations`
- `donkeycar.pipeline.augmentations.ImageAugmentation`
- `donkeycar.management.makemovie.MakeMovie.draw_line_into_image`
- `donkeycar.management.base.ShowPredictionPlots.plot_predictions`

谨慎复用：

- `donkeycar.management.ui.rc_file_handler.rc_handler`
- `donkeycar.management.ui.common.FullImage`
- `donkeycar.management.ui.common.get_app_screen`
- 任何 Kivy widget 或 screen 相关对象

这些对象属于旧 UI 层，不适合作为 FastAPI 后端依赖。

## 5. 前端设计

### 5.1 路由与导航

使用 `/pilot` 作为 Web UI 路由：

- 与旧版 Kivy screen 名称 `pilot` 对齐。
- 与当前 `/trainer`、`/drive`、`/calibrate` 风格一致。
- 导航文字保持 “Pilot Arena”。

需要修改：

- `web_ui/frontend/src/App.tsx`
- `web_ui/frontend/src/components/Layout.tsx`

### 5.2 页面结构

新增页面：

```text
web_ui/frontend/src/pages/PilotArenaPage.tsx
```

页面结构建议：

```text
PilotArenaPage
├── HeaderBar
│   ├── 标题 Pilot Arena
│   ├── 当前 config 状态
│   └── 当前 tub 状态
├── ArenaToolbar
│   ├── Add Pilot
│   ├── Columns 1/2/3/4
│   └── Tub Plot
├── TransformPanel
│   ├── brightness toggle + slider
│   ├── blur toggle + slider
│   ├── pre transformations multi-select
│   └── post transformations multi-select
├── PilotGrid
│   └── PilotViewer[]
└── RecordControls
    ├── record slider
    ├── previous / next
    └── user/pilot field mapping
```

### 5.3 组件拆分

建议新增目录：

```text
web_ui/frontend/src/components/arena/
```

代表性组件：

| 组件 | 职责 |
|---|---|
| `PilotGrid.tsx` | 根据列数渲染多个 viewer |
| `PilotViewer.tsx` | 单个模型卡片，显示加载状态、预览图、预测值 |
| `PilotLoader.tsx` | 模型类型选择、模型列表、加载按钮 |
| `TransformPanel.tsx` | brightness、blur、pre/post transformations |
| `RecordControls.tsx` | 当前 record 滑块、上一条、下一条 |
| `TubPlotModal.tsx` | 选择模型和 limit，展示批量预测曲线 |
| `PredictionChart.tsx` | 使用 Chart.js 绘制 angle/throttle 对比 |

MVP 可以先在页面内合并部分组件，跑通后再拆分。

### 5.4 Zustand 状态

建议扩展 `web_ui/frontend/src/store/useStore.ts` 或新增 arena 专用 store。

状态示例：

```typescript
interface ArenaPilot {
  id?: string;
  modelPath: string;
  modelType: string;
  name: string;
  loaded: boolean;
  lastPrediction?: {
    user: { angle: number; throttle: number };
    pilot: { angle: number; throttle: number };
  };
  error?: string;
}

interface ArenaConfig {
  columns: 1 | 2 | 3 | 4;
  pilots: ArenaPilot[];
  userAngleField: string;
  userThrottleField: string;
  pilotAngleField: string;
  pilotThrottleField: string;
  preTransformations: string[];
  augmentations: string[];
  postTransformations: string[];
  brightnessEnabled: boolean;
  brightness: number;
  blurEnabled: boolean;
  blur: number;
}
```

建议持久化：

- 列数。
- 模型路径、模型类型、模型名。
- 字段映射。
- transformation 配置。

不要持久化：

- 后端返回的 `pilot_id`。
- `loaded: true`。
- 最新预测值。
- 错误状态。

### 5.5 API 封装

扩展 `web_ui/frontend/src/services/api.ts`：

```typescript
export const listArenaModelTypes = async () => { ... };
export const listArenaModels = async (params) => { ... };
export const loadArenaPilot = async (payload) => { ... };
export const listArenaPilots = async () => { ... };
export const unloadArenaPilot = async (pilotId: string) => { ... };
export const predictArenaPilot = async (pilotId: string, payload) => { ... };
export const getArenaPreviewUrl = (pilotId: string, params) => { ... };
export const getArenaPredictions = async (pilotId: string, payload) => { ... };
```

预览图 URL 应包含 query 参数和 cache buster，避免切换 record 或 transformation 后浏览器显示旧图。

### 5.6 用户交互流程

#### 加载模型

1. 用户进入 `/pilot`。
2. 页面检查 config 和 tub 是否已加载。
3. 用户点击 Add Pilot。
4. 选择 model type。
5. 前端调用 `/api/arena/models` 获取兼容模型列表。
6. 用户选择模型并点击 Load。
7. 前端调用 `/api/arena/pilots/load`。
8. 成功后显示预览图和预测值。

#### 切换 record

1. 用户拖动 record slider 或点击上一条/下一条。
2. 更新当前 record index。
3. 对每个已加载 viewer 调用 predict。
4. 刷新 preview 图。
5. 未加载 viewer 保持空状态提示。

#### 调整 transformation

1. 用户调整 brightness、blur 或 transformation 列表。
2. 前端更新状态。
3. 对当前 record 重新请求 predict 与 preview。
4. 单个 viewer 出错只显示局部错误，不影响其他 viewer。

#### Tub Plot

1. 用户点击 Tub Plot。
2. 选择一个已加载 pilot 和 limit。
3. 前端调用 `/api/arena/pilots/{pilot_id}/predictions`。
4. 使用 Chart.js 绘制：
   - user angle vs pilot angle
   - user throttle vs pilot throttle

## 6. 测试与验证计划

后续实现必须遵循 TDD：先写测试，再写业务逻辑。

### 6.1 后端测试

建议新增：

```text
web_ui/backend/tests/test_arena.py
```

覆盖：

1. 模型列表：
   - mock `models` 目录。
   - 验证 `.h5`、`.tflite`、`.savedmodel`、`.trt` 均可被 arena 识别。
   - 验证不沿用 trainer 只显示 `.tflite` 的限制。
2. 加载模型：
   - mock `get_model_by_type()`。
   - mock pilot `.load()`。
   - 验证返回 `pilot.id`。
3. 加载失败：
   - 文件不存在。
   - 模型类型非法。
   - `pilot.load()` 抛错。
4. 卸载模型：
   - 验证从后端状态删除。
5. 单条预测：
   - mock 当前 Tub record。
   - mock pilot `.run()` 返回 `(angle, throttle)`。
   - 验证 user/pilot 数值。
6. 预览图：
   - mock 图像读取与 `MakeMovie.draw_line_into_image()`。
   - 验证返回 image response。
7. 批量预测：
   - mock records 与 pilot inference。
   - 验证 points 数量和字段。

### 6.2 前端测试与类型检查

优先验证：

- TypeScript 类型检查。
- ESLint。
- API 封装参数和返回类型。
- 页面空状态：未加载 config、未加载 tub、未加载模型。
- 加载失败错误提示。

如引入 E2E，可增加 Playwright smoke test：

- 进入 `#/pilot`。
- 看到 Pilot Arena 标题。
- 点击 Add Pilot。
- mock API 返回模型列表。
- 加载模型后显示预测结果。

### 6.3 手动集成验证

手动验证流程：

1. 启动 FastAPI 后端。
2. 启动 React 前端。
3. 加载 config。
4. 加载 tub。
5. 进入 Pilot Arena。
6. 添加一个 `.tflite` 或 `.h5` image-only 模型。
7. 验证当前 record 显示：
   - 用户线为绿色。
   - 模型预测线为蓝色。
   - user/pilot angle 和 throttle 数值正确。
8. 添加第二个模型。
9. 切换列数 1-4。
10. 拖动 record slider，所有已加载 viewer 更新。
11. 启用 brightness 和 blur，确认预览图变化。
12. 添加 `CROP` 或 `TRAPEZE` transformation，确认后端不崩溃。
13. 打开 Tub Plot，生成前 N 条对比曲线。
14. 卸载模型，确认 viewer 状态正确。
15. 刷新页面，确认模型配置可恢复，但需要重新加载后端模型实例。

### 6.4 回归风险点

- 不应破坏 Tub Manager、Trainer、Drive、Calibrate 现有页面。
- 不应修改 `/api/trainer/models` 的 `.tflite` 过滤行为。
- 不应引入 Kivy UI 依赖到 Web 后端启动路径。
- 不应在页面刷新后误认为后端内存中仍有已加载模型。

## 7. 实施步骤

### 阶段 0：文档确认

新增并确认本方案文档。

### 阶段 1：后端测试先行

新增 arena router 测试，先覆盖模型扫描、加载、卸载、预测、预览和批量预测。

### 阶段 2：后端实现

实现 `web_ui/backend/routers/arena.py`，并在 `web_ui/backend/main.py` 注册。

建议顺序：

1. model types。
2. models list。
3. load/unload pilots。
4. single predict。
5. preview image。
6. batch predictions。

### 阶段 3：前端类型与交互测试先行

补充 API 类型、页面空状态和关键交互测试，或至少先确保 TypeScript 与 ESLint 可运行。

### 阶段 4：前端实现

建议顺序：

1. `/pilot` 路由和导航入口。
2. 页面静态结构。
3. Add Pilot 和 PilotViewer 状态。
4. 模型列表、加载、卸载 API 接入。
5. 当前 record 推理与 preview 图刷新。
6. transformation panel。
7. Tub Plot modal 与 Chart.js。

### 阶段 5：端到端验证

按第 6.3 节完整走一遍 Web UI 操作流程，并运行后端测试、前端 lint/build。

## 8. 文件变更清单

### 8.1 本方案新增

```text
docs/plan/pilot-arena-web-ui-migration.md
```

### 8.2 后续实现建议新增

```text
web_ui/backend/routers/arena.py
web_ui/backend/tests/test_arena.py
web_ui/frontend/src/pages/PilotArenaPage.tsx
web_ui/frontend/src/components/arena/PilotGrid.tsx
web_ui/frontend/src/components/arena/PilotViewer.tsx
web_ui/frontend/src/components/arena/PilotLoader.tsx
web_ui/frontend/src/components/arena/TransformPanel.tsx
web_ui/frontend/src/components/arena/RecordControls.tsx
web_ui/frontend/src/components/arena/TubPlotModal.tsx
web_ui/frontend/src/components/arena/PredictionChart.tsx
```

### 8.3 后续实现建议修改

```text
web_ui/backend/main.py
web_ui/frontend/src/App.tsx
web_ui/frontend/src/components/Layout.tsx
web_ui/frontend/src/services/api.ts
web_ui/frontend/src/store/useStore.ts
```

## 9. 风险与处理策略

### 9.1 模型输入兼容性

风险：部分模型类型不能直接通过 `pilot.run(image)` 推理。

策略：MVP 明确支持 image-only 常见模型；复杂模型返回清晰错误，后续再扩展输入适配。

### 9.2 图像字段差异

风险：不同 Tub 中图像字段名可能不同。

策略：默认优先支持 `cam/image_array`，后续可扫描常见图像字段并允许用户选择。

### 9.3 Kivy 依赖泄漏

风险：直接复用 `rc_handler` 或 Kivy widget 会让 Web 后端依赖旧 UI。

策略：只复用非 UI 工具；字段映射和持久化在 Web 层独立实现。

### 9.4 后端全局状态

风险：全局 `loaded_pilots` 不适合多用户。

策略：MVP 与当前本地 Web UI 架构保持一致；后续如需要多用户，再引入 session id 或状态服务。

### 9.5 现有未提交修改

风险：仓库已有大量未提交修改，实施时可能误覆盖用户工作。

策略：后续编码前检查 `git status` 和相关 diff，只修改 Pilot Arena 相关文件，不执行 `git reset`、`git clean` 或覆盖式恢复操作。

## 10. 最小可行交付定义

Pilot Arena MVP 可认为完成，当满足以下条件：

1. `/pilot` 页面可从导航进入。
2. 后端 `/api/arena` router 可列出并加载模型。
3. 至少一个 `.tflite` 或 `.h5` image-only 模型可以完成当前 record 推理。
4. 页面显示 user/pilot angle 与 throttle。
5. 预览图显示用户绿色线和模型蓝色线。
6. 多个模型 viewer 可以并排对比。
7. Tub Plot 可以展示前 N 条 user vs pilot 曲线。
8. 后端测试覆盖核心 API。
9. 前端 lint/build 通过。
10. 现有 Tub Manager、Trainer、Drive、Calibrate 功能不回归。
