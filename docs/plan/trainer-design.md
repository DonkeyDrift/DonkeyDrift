# Trainer 标签页设计方案

## 1. train_online 执行逻辑分析

`OnlineTrainer`（`donkeycar/management/train_online.py`）执行 8 步流水线：

| 步骤 | 方法 | 说明 |
|------|------|------|
| ① 配置加载 | `_load_config` | 读取 `train_online.conf`（INI），含 host/user/password/remote_dir_base/model_name/python_path；首次自动创建默认值 |
| ② 模型命名 | `_generate_unique_model_name` | 格式 `{folder}-{clean_model}-{YYMMDD}-{4位随机码}`，本地 `./models` 查重 |
| ③ 数据打包 | `package_data` | `./data` → `data_cache/data-YYMMDD-XXX.tar.gz`，tar 完整性校验 |
| ④ SSH 连接 | `connect_ssh` | paramiko，3 次重试，超时 10s |
| ⑤ 远程空间 | `setup_remote_workspace` | 在 `remote_dir_base` 下创建 `mycar-YYMMDD-XXX-ABCD`，调用 `donkey createcar --path` |
| ⑥ 上传数据 | `upload_data` | SFTP put，Rich 进度条回调 |
| ⑦ 远程训练 | `run_remote_training` | 执行 `cd {dir} && {python} train.py --tub ./data --model ./models/{name} --type linear`；实时流式读取 stdout/stderr；解析 Epoch/Step/Loss；渲染 Rich 进度条；过滤 TF 噪音日志 |
| ⑧ 模型下载 | `download_model` | 拉取 `.tflite` + `.png`，tflite interpreter 校验完整性 |
| 清理 | `cleanup` | 删除远程 tar、关闭 SSH |

`train_local`（`donkeycar/management/train_local.py`）则直接调用 `donkey train --tub ... --model ... --type ...`，stdio 直通终端。

---

## 2. 现有 Web UI 架构

- **前端**：React 18 + Vite + Tailwind CSS + Zustand（persist）+ Chart.js + axios + **react-router-dom（已安装但未使用）**
- **后端**：FastAPI + uvicorn，已有 `/api/config`、`/api/tub`
- **状态管理**：`useStore.ts` 全局 Zustand store，持久化 `configPath`、`tubPath`、`isLooping`
- **导航**：`Layout.tsx` 顶部导航栏已有 "Tub Manager"（当前唯一页面）/ "Trainer" / "Pilot Arena" / "Car Connector" 占位链接

---

## 3. Trainer 标签页设计方案

### 3.1 前端架构

**路由**：启用 `react-router-dom`，`App.tsx` 改为 `BrowserRouter` + `Routes`：
- `/` → Tub Manager（现有页面）
- `/trainer` → Trainer 页面

**页面结构（`TrainerPage.tsx`）**：

```
TrainerPage
├── ModeTabs              // [本地训练 | 云端训练]
├── ConfigSection
│   ├── LocalConfig       // tub路径、模型名称、模型类型(linear/...)、迁移模型(下拉)
│   └── RemoteConfig      // SSH配置(host/user/password)、远程目录、Python路径、模型名称
├── ActionBar             // [开始训练] [停止训练] 按钮 + 状态指示灯
├── ProgressPanel         // Epoch/Step 进度条 + Loss 数值 + 耗时
├── LogPanel              // 仿终端日志流（虚拟滚动，ANSI→HTML 着色）
└── ModelsSection         // 本地 ./models 模型列表（名称、大小、时间、操作）
```

**状态扩展（`useStore.ts`）**：

```typescript
interface TrainingJob {
  id: string;
  mode: 'local' | 'online';
  status: 'pending' | 'running' | 'completed' | 'failed' | 'stopped';
  progress: {
    currentEpoch: number;
    totalEpochs: number;
    currentStep: number;
    totalSteps: number;
    loss: number | null;
    globalPercent: number;  // 0-100
  };
  logs: string[];
  startedAt: string;
  finishedAt?: string;
}

interface AppState {
  // ... 现有字段 ...
  activePage: 'tub' | 'trainer';
  trainingJob: TrainingJob | null;
  trainerOnlineConfig: {
    host: string; user: string; password: string;
    remoteDirBase: string; modelName: string; pythonPath: string;
  };
  setActivePage: (page: 'tub' | 'trainer') => void;
  startTrainingJob: (job: TrainingJob) => void;
  appendTrainingLog: (lines: string[]) => void;
  updateTrainingProgress: (progress: TrainingJob['progress']) => void;
  finishTrainingJob: (status: 'completed' | 'failed' | 'stopped') => void;
}
```

**前端组件拆分**：

| 文件 | 职责 |
|------|------|
| `pages/TrainerPage.tsx` | 页面壳，组合子组件 |
| `components/trainer/ModeTabs.tsx` | 本地/云端切换 |
| `components/trainer/LocalConfigForm.tsx` | 本地训练参数表单 |
| `components/trainer/RemoteConfigForm.tsx` | 云端 SSH/路径配置表单 |
| `components/trainer/ProgressPanel.tsx` | 进度条 + Loss 显示 |
| `components/trainer/LogPanel.tsx` | 终端日志流，带虚拟滚动 |
| `components/trainer/ModelsList.tsx` | 本地模型列表卡片 |
| `services/api.ts` | 新增 trainer API 调用 |

### 3.2 后端架构

**新增 FastAPI Router**：`web_ui/backend/routers/trainer.py`

```python
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()
```

**API 清单**：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/trainer/config` | 读取 `train_online.conf`，JSON 返回 |
| POST | `/api/trainer/config` | 写入 `train_online.conf` |
| GET | `/api/trainer/models` | 扫描 `./models`，返回列表（含大小、修改时间） |
| GET | `/api/trainer/backups` | 扫描 `./data_cache`，返回 tar.gz 列表 |
| POST | `/api/trainer/train/local` | 启动本地训练，返回 `{job_id}` |
| POST | `/api/trainer/train/online` | 启动云端训练，返回 `{job_id}` |
| GET | `/api/trainer/train/{job_id}/logs` | **SSE** 流式推送日志+进度 JSON |
| POST | `/api/trainer/train/{job_id}/stop` | 停止训练任务 |
| GET | `/api/trainer/train/{job_id}/status` | 查询任务当前状态 |

**任务执行引擎**：`web_ui/backend/trainer_engine.py`

```python
class TrainingJobManager:
    """单例，管理所有活跃训练任务"""
    jobs: Dict[str, TrainingJob]
    
class TrainingJob:
    id: str
    mode: Literal['local', 'online']
    status: Literal['pending', 'running', 'completed', 'failed', 'stopped']
    log_queue: asyncio.Queue[str]
    progress: TrainingProgress
    # local
    process: Optional[asyncio.subprocess.Process]
    # online
    trainer_thread: Optional[threading.Thread]
    stop_event: threading.Event
```

**本地训练执行**：
- `asyncio.create_subprocess_exec("donkey", "train", ...)`
- `asyncio.create_task(_read_stdout())` 读取 stdout 逐行入 `log_queue`
- 前端 SSE 端点 `while True: line = await queue.get(); yield f"data: {json}\n\n"`

**云端训练执行**：
- `OnlineTrainer` 是同步阻塞的（paramiko），使用 `asyncio.to_thread` 或独立 `threading.Thread` 运行
- **适配策略**：创建 `WebOnlineTrainer(OnlineTrainer)` 子类，重写 `_log` 和关键 `console.print` 输出，改为写入 `log_queue` 而不是 Rich Console
- 训练输出解析复用 `_parse_training_output` 的正则逻辑，在引擎层实时计算 `globalPercent` 和 `loss`

### 3.3 关键实现细节

**① 日志流与 SSE**

前端使用原生 `EventSource` 连接 `/api/trainer/train/{job_id}/logs`：

```typescript
const eventSource = new EventSource(`/api/trainer/train/${jobId}/logs`);
eventSource.onmessage = (e) => {
  const payload = JSON.parse(e.data);
  if (payload.type === 'log') appendLog(payload.line);
  if (payload.type === 'progress') updateProgress(payload.data);
  if (payload.type === 'status') updateStatus(payload.status);
};
```

后端 SSE 格式：
```json
{"type": "log", "line": "Epoch 1/20", "timestamp": "..."}
{"type": "progress", "data": {"currentEpoch": 1, "totalEpochs": 20, "currentStep": 50, "totalSteps": 100, "loss": 0.123, "globalPercent": 7.5}}
{"type": "status", "status": "completed"}
```

**② 进度解析复用**

直接复用 `OnlineTrainer._parse_training_output` 中的正则：
- `Epoch (\d+)/(\d+)` → epoch 信息
- `^(\s*\d+)/(\d+)\s+\[` → step 进度
- `loss: (\d+\.\d+)` → loss 值
- 全局进度算法：`((current_epoch-1) + current_step/total_steps) / total_epochs * 100`

**③ 配置双向同步**

`train_online.conf` 是 CLI 和 Web UI 共享的配置文件。后端提供读写接口，确保：
- Web UI 编辑的配置立即回写文件
- CLI 下次启动时读取到最新值
- 首次访问时若文件不存在，由后端调用 `_load_config` 逻辑自动创建默认值

**④ 模型管理**

训练完成后，后端 `TrainingJob` 状态变为 `completed`，前端自动调用 `GET /api/trainer/models` 刷新模型列表。
模型列表显示：
- 名称、文件大小、修改时间
- 操作按钮：下载（对于云端训练完成后已自动下载，此操作可能不需要）、删除、复制路径

**⑤ 训练停止机制**

- **本地**：`process.terminate()` → 3秒后 `process.kill()`
- **云端**：`ssh_client.close()` + 设置 `stop_event`，线程检测到后优雅退出

---

## 4. 文件变更清单

### 后端新增

| 文件 | 说明 |
|------|------|
| `web_ui/backend/routers/trainer.py` | FastAPI 路由：配置读写、任务启停、SSE 日志、模型/备份列表 |
| `web_ui/backend/trainer_engine.py` | 任务执行引擎：`TrainingJobManager`、`TrainingJob`、本地/云端执行逻辑、日志队列管理 |
| `web_ui/backend/web_online_trainer.py` | `WebOnlineTrainer` 类，继承 `OnlineTrainer`，适配 queue 输出 |

### 后端修改

| 文件 | 修改 |
|------|------|
| `web_ui/backend/main.py` | `app.include_router(trainer.router, prefix="/api/trainer", tags=["trainer"])` |

### 前端新增

| 文件 | 说明 |
|------|------|
| `web_ui/frontend/src/pages/TrainerPage.tsx` | Trainer 主页面 |
| `web_ui/frontend/src/components/trainer/ModeTabs.tsx` | 本地/云端切换标签 |
| `web_ui/frontend/src/components/trainer/LocalConfigForm.tsx` | 本地训练配置表单 |
| `web_ui/frontend/src/components/trainer/RemoteConfigForm.tsx` | 云端训练配置表单 |
| `web_ui/frontend/src/components/trainer/ProgressPanel.tsx` | 进度条 + 指标 |
| `web_ui/frontend/src/components/trainer/LogPanel.tsx` | 终端日志（虚拟滚动） |
| `web_ui/frontend/src/components/trainer/ModelsList.tsx` | 本地模型列表 |
| `web_ui/frontend/src/hooks/useTrainingJob.ts` | SSE 连接 + 状态管理 hook |

### 前端修改

| 文件 | 修改 |
|------|------|
| `web_ui/frontend/src/App.tsx` | 引入 `BrowserRouter` + `Routes`，配置 `/` 和 `/trainer` 路由 |
| `web_ui/frontend/src/components/Layout.tsx` | 导航栏 `<a>` 改为 `<Link to="/">` / `<Link to="/trainer">` |
| `web_ui/frontend/src/store/useStore.ts` | 扩展 `AppState`：添加 `activePage`、`trainingJob`、trainer 配置字段和相关 action |
| `web_ui/frontend/src/services/api.ts` | 新增 trainer API 函数 |

---

## 5. 实施优先级

| 阶段 | 内容 | 预估工作量 |
|------|------|-----------|
| **P0** | 路由框架 + 页面骨架 + 导航切换 | 小 |
| **P1** | 后端 API：配置读写 + 本地/云端任务启动 + SSE | 中 |
| **P2** | 前端：配置表单 + LogPanel（SSE 消费）+ 开始/停止按钮 | 中 |
| **P3** | 前端：ProgressPanel（进度条 + Loss）+ 解析逻辑 | 小 |
| **P4** | 前端：ModelsList + 后端模型扫描 API | 小 |
| **P5** | 打磨：错误处理、加载状态、移动端适配、键盘快捷键 | 小 |

---

## 6. 风险与注意事项

1. **Paramiko 阻塞**：`OnlineTrainer` 全程同步，必须在独立线程运行，SSE 通过 `asyncio.Queue` 桥接线程与 async 事件循环。
2. **Rich Console 冲突**：`OnlineTrainer` 内部强依赖 `rich.console.Console`。`WebOnlineTrainer` 子类需要重写所有 `console.print` 调用点，或改用 logging/queue 注入。
3. **当前工作目录**：`OnlineTrainer` 默认以进程 CWD 为基准找 `./data`、`./models`、`train_online.conf`。后端 FastAPI 启动时 CWD 可能不同，需要在引擎层显式传入 `working_dir`。
4. **大日志内存**：训练可能输出数万行日志，前端 `LogPanel` 必须做虚拟滚动或截断（只保留最近 N 行），防止浏览器内存泄漏。
