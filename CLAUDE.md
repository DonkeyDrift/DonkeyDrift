# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

Donkeycar 是一个模块化 Python 自驾车库，面向真实硬件、模拟器和教学实验场景。核心运行模型是把摄像头、控制器、执行器、训练/推理、数据记录等能力拆成可组合的 Part，并由 Vehicle 主循环串联。

- Python 版本：`>=3.11.0,<3.12`
- Python 包入口：`donkeycar/`
- CLI 入口：`donkey = donkeycar.management.base:execute_from_command_line`
- 旧版车辆模板：`donkeycar/templates/`
- 统一 Web UI：`web_ui/`，后端 FastAPI，前端 React/Vite

## 常用命令

### Python 包

```bash
pip install -e .[dev]          # 开发依赖：pytest、pytest-cov、responses、mypy
pip install -e .[pc,dev]       # 本地完整测试环境，CI 使用这一组 extra
pip install -e .[torch]        # PyTorch 后端，固定 torch 2.1
pip install -e .[pi]           # 树莓派环境

pytest                         # 运行全部 Python 测试
make tests                     # 等价于 pytest
pytest tests/test_restore_logic.py -q
pytest tests/test_restore_logic.py::test_name -v
pytest donkeycar/tests/test_vehicle.py -q
pytest donkeycar/tests/test_vehicle.py::test_name -v

mypy donkeycar/                # 类型检查
python -m build --sdist        # 通过 pyproject.toml 构建源码包；需要已安装 build
```

仓库根目录没有 `setup.py`，当前 `make package` 目标仍调用 `python setup.py sdist`，打包时不要依赖该目标，除非先修正 Makefile。

### Web UI 后端

后端 FastAPI 依赖（`fastapi` / `uvicorn` / `python-multipart`）已合并到 setup.cfg 的 `webui` extra；`pc` / `macos` extras 已通过 `webui` 自动拉取这些依赖，所以 `pip install -e .[pc]` 一次即可同时装好核心包和后端。

```bash
cd web_ui/backend            # 可选：仅在排查 requirements.txt 锁定版本时进入
pip install -r requirements.txt
python main.py
python -m pytest tests -q
python -m pytest tests/test_connector.py -q
python -m pytest tests/test_arena.py::test_predict_returns_user_and_pilot_values -q
```

后端开发服务默认监听 `0.0.0.0:8000`，FastAPI 应用定义在 `web_ui/backend/main.py`。

### Web UI 前端

```bash
cd web_ui/frontend
npm install
npm run dev      # Vite 开发服务，默认端口 5188
npm run build    # tsc -b && vite build
npm run lint     # ESLint
npm run check    # TypeScript noEmit
npm run preview
```

前端开发时 `/api` 由 Vite 代理到后端；也可通过 `VITE_API_BASE_URL` 覆盖 API base URL。当前 `package.json` 没有前端测试脚本，验证前端改动主要依赖 `npm run check`、`npm run lint`、`npm run build` 和手工运行页面。

### 一键安装前后端依赖

为了让 `pip install -e .[pc]` 之后能直接 `donkey web` 启动，新增了 `donkey installweb` 子命令（等价于 `make installweb`）：

```bash
# 1) 后端 Python 依赖（已通过 [pc] → webui 自动安装，一般无需重复执行）
pip install -e ".[pc,dev]"

# 2) 前端 Node 依赖（pip 无法处理 npm，需要单独执行）
donkey installweb --path ./web_ui
# 或者: make installweb

# 启动（缺失依赖时会打印一行提示）
donkey web
# 一体化启动并自动安装缺失依赖：
donkey web --install-deps
```

`donkey installweb` 是幂等的：仅安装实际缺失的 Python 包，仅在 `node_modules` 缺失或不完整时执行 `npm install`。可用 `--no-backend` / `--no-frontend` 选择性跳过。

### 运行时 CLI

```bash
donkey createcar --path ~/mycar --template complete
python manage.py drive
python manage.py train --tub ./data/* --model ./models/mypilot.h5
donkey calibrate --channel 0
```

这些命令通常在用户通过模板生成的车目录中执行，而不是在仓库根目录直接运行。

### CI 与格式检查

GitHub Actions 在 macOS 和 Ubuntu 上用 Python 3.11 conda 环境执行 `pip install -e .[pc,dev]` 后运行 `pytest`。Super-Linter 目前配置为 `continue-on-error` 且 `DISABLE_ERRORS=true`，会排除 `*.css` 和 `*.js`；Python Black 配置位于 `.github/linters/.python-black`，行宽为 80。

## 核心架构

### Vehicle + Memory + Part

`donkeycar/vehicle.py` 的 `Vehicle` 是运行时主循环容器。`Vehicle.add(part, inputs, outputs, threaded, run_condition)` 将 Part 注册进循环；主循环按顺序从 `Memory` 读取 inputs，调用 Part 的 `run()`，再把结果写回 outputs。

`donkeycar/memory.py` 的 `Memory` 是简单键值存储。Part 之间不直接互相依赖，而是通过字符串 key 交换数据。新增数据通道时，要在模板或车辆组装代码中显式声明对应 inputs/outputs。

Part 不需要继承基类；通常只要实现 `run()`，线程型 Part 还会实现 `update()`，可选实现 `shutdown()`。IO 密集型 Part 如摄像头、WebSocket 桥接适合 `threaded=True`。

### 主要目录职责

- `donkeycar/parts/`：可插拔硬件和算法组件，包括 camera、controller、actuator、keras、pytorch、path、behavior、simulation、tub_v2、drive_api_bridge 等。
- `donkeycar/templates/`：`donkey createcar` 使用的车辆应用模板和 `cfg_*.py` 默认配置，例如 `complete.py`、`basic.py`、`simulator.py`、`path_follow.py`、`cv_control.py`、`train.py`。
- `donkeycar/management/`：CLI 子命令入口和管理逻辑，包含 createcar、train、calibrate、drive、makemovie、在线训练等。
- `donkeycar/pipeline/`：训练管道、图像增强、序列数据处理和 Tub 数据集管理。
- `web_ui/`：新版统一管理界面，覆盖数据浏览编辑、模型训练、驾驶控制、校准、Pilot Arena 和 Car Connector。

### Web UI 后端

`web_ui/backend/main.py` 创建 FastAPI 应用并注册所有 `/api/*` 路由：

- `/api/config`：配置加载和保存
- `/api/tub`：Tub 数据浏览、图像读取、记录删除/恢复
- `/api/trainer`：本地/远程训练任务、日志流、模型管理
- `/api/drive`：驾驶 WebSocket、MJPEG 视频流、参数、校准和模型加载
- `/api/arena`：Pilot Arena 模型加载、单帧/批量预测和预览图
- `/api/connector`：远程车连接、状态检查、Tub/模型同步和远程驾驶桥接

新增后端路由时，需要在 `main.py` 中 `include_router`，并在对应 `web_ui/backend/tests/` 测试路由契约。

### Web UI 前端

前端是 React 18 + TypeScript + TailwindCSS + Zustand。关键约定：

- `web_ui/frontend/src/services/api.ts` 统一封装 axios API、WebSocket URL 和错误消息提取。
- `store/useStore.ts` 管理 Tub/训练相关状态，`store/useDriveStore.ts` 管理驾驶参数并持久化。
- 页面层位于 `src/pages/`：Home、Trainer、Drive、Calibrate、PilotArena、CarConnector。
- 驾驶相关实时输入拆在 `src/hooks/` 和 `src/components/drive/`，包括键盘、手柄、陀螺仪、虚拟摇杆和 WebSocket。

新增前端 API 调用应先放入 `services/api.ts`，再由页面或 hook 使用。

### 车端桥接和驾驶协议

`donkeycar/parts/drive_api_bridge.py` 是新版 Web UI 驾驶桥接 Part，用标准 Part 方式连接 FastAPI WebSocket，替代旧的独立 Tornado `LocalWebController` 入口。驾驶控制 WebSocket 使用 `/api/drive/ws`，通过 `role=car|client` 区分车端和浏览器端；视频流走 `/api/drive/video` MJPEG，控制通道和图像通道相互独立。

Car Connector 位于 `web_ui/backend/routers/connector.py` 和前端 `CarConnectorPage.tsx`，用于通过远程车配置执行连接检查、Tub/模型列表与同步、远程驾驶桥接等操作。

## 重要约定

1. 配置通过 `dk.load_config()` 加载用户车目录中的 `config.py` 和 `myconfig.py`，可调参数应优先走配置，不要硬编码到 Part 或模板中。
2. 录制数据统一使用 Tub v2 格式，相关逻辑集中在 `donkeycar/parts/tub_v2.py`；不要引入并行的数据目录格式。
3. `Vehicle.add(..., threaded=True)` 会调用 Part 的 `update()` 后台线程；并发写 Memory 时要避免多个 Part 写同一 key。
4. TensorFlow 固定在 2.15.x，PyTorch 固定在 2.1.x，依赖大版本升级会影响模型兼容性。
5. CLI 模板文件既是用户生成车应用的来源，也是配置契约的一部分；修改模板时通常要同步对应 `cfg_*.py` 和相关测试。
6. Web UI 前后端 API 前缀约定为 `/api`；前端 URL 拼接和错误消息应复用 `services/api.ts` 中已有工具。
