<!-- From: /home/dkc/projects/DonkeyDrifter/AGENTS.md -->
# DonkeyDrifter 智能体指南

本文件为 AI 编程智能体提供在 DonkeyDrifter 仓库中高效工作所需的必要上下文。该项目是一个源自 Donkeycar 的独立 Python 自动驾驶/漂移机器人平台。以下所有事实均取自工作树中的实际文件（当前分支 `v1.6.0-UX`，版本 `0.1.1`）。

## 项目概览

- **版本**：`0.1.1`，定义于 `donkeycar/_version.py`。
- **Python 要求**：`>=3.11.0,<3.12`。`donkeycar/__init__.py` 在导入阶段强制校验该版本。
- **主要分发包**：`donkeydrifter`（setuptools 元数据位于 `setup.cfg`）。
- **实现包**：`donkeycar/`（遗留兼容性命名空间）。
- **推荐导入**：`import donkeydrifter as dk`。
- **兼容导入**：`import donkeycar as dk` 仍可通过 `donkeydrifter/__init__.py` 中的 `sys.meta_path` 别名层工作。
- **CLI 入口点**：`donkey = donkeycar.management.base:execute_from_command_line`。
- **项目主页**：`https://github.com/DonkeyDrift/DonkeyDrifter`（来自 `setup.cfg` 的 `url`）。
- **上游源码**：`https://github.com/autorope/donkeycar`。
- **许可证**：DonkeyDrifter 的更改采用 Apache License 2.0；上游 Donkeycar 部分保留 MIT。参见 `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md` 和 `LICENSES/MIT-donkeycar.txt`。

DonkeyDrifter 不隶属于 Donkeycar 维护者，也不受其赞助或认可。

## 仓库布局

```text
donkeydrifter/       # 公共别名包，将导入转发到 donkeycar/
donkeycar/           # 当前实现包 + 遗留兼容性命名空间
  __init__.py        # 强制要求 Python >=3.11，暴露 Vehicle、Memory、load_config
  _version.py        # __version__ = '0.1.1'
  vehicle.py         # 车辆驱动循环和 PartProfiler
  memory.py          # 部件间通信的键/值总线
  config.py          # 配置加载器
  parts/             # 59+ 硬件/算法部件（摄像头、控制器、keras、pytorch、tub_v2、IMU、GPS、drive_api_bridge 等）
  pipeline/          # 训练流水线、数据增强、序列处理、数据库
  management/        # CLI 工具和 UI（base.py、tui.py、train_local.py、train_online.py、ui/、tub_web/）
  templates/         # `donkey createcar` 使用的车辆应用模板（basic、complete、cv_control、path_follow、simulator、arduino_drive 等）
  tests/             # 核心单元/集成测试（40+ 测试文件）
  utilities/         # 辅助工具和 TrackSpeedPlanner
  contrib/、gym/     # 社区和模拟器集成
web_ui/              # 统一的 FastAPI 后端 + React/Vite 前端
  backend/main.py    # FastAPI 应用，挂载 /api/{config,tub,trainer,drive,arena,connector}
  backend/routers/   # FastAPI 路由模块（config.py、tub.py、trainer.py、drive.py、arena.py、connector.py）
  backend/tests/     # FastAPI 契约测试（test_arena.py、test_branding.py、test_config.py、test_connector.py、test_drive.py）
  frontend/src/      # React/TypeScript/Vite SPA（pages/、components/、services/、store/、hooks/）
parts/               # 额外的顶层部件目录（保留旧版 drive_api_bridge.py，但模板实际导入的是 donkeycar/parts/drive_api_bridge.py）
tests/               # 根级迁移/集成测试（6 个文件）
scripts/             # 独立工具（convert、freeze、profile、migrate_model_names、multi_train 等）
arduino/             # mono_encoder 和 quadrature_encoder 草图
docs/                # 架构、计划、指南、验证、超能力规范
```

## 技术栈

- **核心运行时**：Python 3.11、NumPy、Pillow、Tornado、pandas、PyYAML、requests、rich、paramiko、pygame、gymnasium、paho-mqtt、simple_pid、progress、pyfiglet、psutil、pynmea2、pyserial、utm、websockets、aiortc、av。
- **机器学习**：TensorFlow `2.15.*`、Keras；PyTorch `2.1.*`、pytorch-lightning、torchvision、fastai `<2.8`。OpenCV 在 `pi` 平台 extra 中显式列出，PC 开发环境通常也需要安装。
- **数据格式**：Tub v2（清单 + 目录 + 图片）；逻辑位于 `donkeycar/parts/tub_v2.py` 和 `donkeycar/parts/datastore_v2.py`。
- **遥测**：paho-mqtt。
- **终端 UI**：rich、Kivy（`.kv` 文件作为包数据包含）。
- **Web UI 后端**：FastAPI、Uvicorn、Pydantic、python-multipart、websockets、aiortc、av。
- **Web UI 前端**：React 18、TypeScript ~5.8、Vite 6、Tailwind CSS 3、Zustand、Chart.js、axios、react-router-dom 7、lucide-react、clsx、tailwind-merge。
- **测试**：pytest、pytest-cov、responses、mypy；前端 vitest + jsdom + @testing-library/react + Playwright。
- **构建/打包**：setuptools 通过 `setup.cfg` + `pyproject.toml`；`python -m build` 用于 wheels/sdists。

## 构建、安装和运行命令

为本地开发安装包（选择与您机器匹配的平台 extras）：

```bash
# PC / Linux / WSL
pip install -e ".[pc,dev]"

# macOS with Apple Silicon/Metal
pip install -e ".[macos,dev]"

# Raspberry Pi
pip install -e ".[pi,dev]"

# Jetson Nano
pip install -e ".[nano,dev]"
```

Web UI 一次性依赖安装：

```bash
donkey installweb --path ./web_ui
# 或
make installweb
```

这会从 `web_ui/backend/requirements.txt` 安装后端 Python 依赖，并在 `web_ui/frontend` 中运行 `npm install`。

运行统一的 Web UI：

```bash
donkey web --path ./web_ui
# 自动安装缺失依赖并打开浏览器：
donkey web --path ./web_ui --install-deps --open
```

运行核心测试：

```bash
pytest
pytest donkeycar/tests/test_vehicle.py -q
```

运行 Web UI 后端测试：

```bash
cd web_ui/backend
python -m pytest tests -q
```

运行 Web UI 前端检查：

```bash
cd web_ui/frontend
npm run check   # tsc --noEmit
npm run lint    # eslint .
npm run build
npm run test    # vitest
```

构建发布版本：

```bash
python -m build --sdist --wheel
# 或
make package
```

运行完整测试目标：

```bash
make tests   # 运行 pytest
```

## `donkey` 提供的 CLI 命令

注册于 `donkeycar/management/base.py`：

- `createcar` – 从模板生成车辆目录。
- `update` – 刷新当前目录中的车辆文件。
- `findcar` – 在本地网络上发现车辆 IP。
- `calibrate` – PWM/舵机校准。
- `train` – 训练入口点。
- `tubplot`、`tubhist`、`makemovie`、`cnnactivations` – 数据可视化。
- `models` – 模型数据库。
- `ui`、`tui` – GUI/TUI；裸 `donkey` 默认为 TUI。
- `web` – 启动统一的 FastAPI + React Web UI。
- `installweb` – 安装 Web UI 后端/前端依赖。
- `createjs` – 摇杆创建器。

## 开发约定

### 导入兼容性契约

- 新代码和模板应优先使用 `import donkeydrifter as dk`。
- 现有的 `import donkeycar` 必须保持兼容；不要破坏 `donkeydrifter/__init__.py` 中的别名层。
- CLI 命令必须保持为 `donkey`。
- 现有的 `DONKEY_*` 配置键在第一阶段迁移中不更名。
- 现有的 Web UI `/api/*` 路由和驱动 WebSocket 协议在第一阶段迁移中不更名。
- 不要盲目替换每个 Donkeycar 引用；上游归属、兼容性文档和许可文本必须在适当的地方保留 Donkeycar 名称。

### Vehicle / Part / Memory 架构

- `Vehicle`（`donkeycar/vehicle.py`）是主循环容器。
- 部件通过 `Vehicle.add(part, inputs=[], outputs=[], threaded=False, run_condition=None)` 注册。
- 每个循环节拍从 `Memory` 读取命名的 `inputs`，调用 `part.run()`（或对于 `threaded=True` 在后台线程中调用 `part.update()`），并将命名的 `outputs` 写回。
- `Memory`（`donkeycar/memory.py`）是一个简单的键/值总线。部件通过字符串键通信，而非直接引用。
- 部件使用鸭子类型：实现 `run()`；线程部件还实现 `update()`；清理放在 `shutdown()` 中。避免多个部件并发写入相同的 Memory 键。

### 代码风格

- **Python**：`CONTRIBUTING.md` 引用 PEP-8。Black 配置存在于 `.github/linters/.python-black`（`line-length = 80`、`target-version = ['py37']`、`skip-string-normalization = true`），主要由 GitHub Super-Linter 使用；注意项目实际运行时为 Python 3.11。
- **TypeScript**：`tsconfig.json` 使用 `module: ESNext`、`moduleResolution: bundler`、`jsx: react-jsx`、`strict: false`，路径别名 `@/* -> ./src/*`。
- **ESLint**：`eslint.config.js` 使用 `typescript-eslint` recommended、`react-hooks` recommended，以及 `react-refresh/only-export-components` 作为警告。
- **Tailwind**：`tailwind.config.js` 使用 `darkMode: "class"` 和内容路径 `./index.html` 和 `./src/**/*`。

### Web UI 约定

- 后端入口点：`web_ui/backend/main.py`（默认端口 `8000`）。
- 前端开发服务器：`web_ui/frontend`（默认端口 `5188`，Vite 将 `/api` 代理到 `http://localhost:8000`）。
- 前端 API 客户端集中在 `web_ui/frontend/src/services/api.ts` 中；不要在其他地方硬编码 API 基础 URL。`VITE_API_BASE_URL` 可以覆盖基础 URL。
- 视频传输可以通过 `VITE_DRIVE_VIDEO_TRANSPORT=webrtc|mjpeg` 强制指定；默认是自动。
- 生产构建是使用 HashRouter 的静态 SPA（`/#/drive`、`/#/trainer` 等）。

## 测试说明

- **核心 Python 测试**：`pytest`（收集 `donkeycar/tests/` 和 `tests/`）。`donkeycar/tests/pytest.ini` 抑制弃用警告，启用 INFO 级别的 CLI 日志，并设置 `reruns = 3`。
- **覆盖率**：`.coveragerc` 启用分支覆盖率并忽略 `donkeycar/tests/*`。
- **根级集成测试**：`pytest tests/ -q` 覆盖迁移品牌、恢复逻辑、模型命名重构、在线训练器工作区、Tub 管理器刷新。
- **Web UI 后端测试**：`cd web_ui/backend && python -m pytest tests -q` 覆盖驱动（WebRTC/MJPEG/统计）、连接器、竞技场、配置和品牌。
- **Web UI 前端测试**：`cd web_ui/frontend && npm run test` 在 jsdom 中运行 vitest。Playwright 风格的测试计划也存在于 `web_ui/frontend/testsprite_tests/` 下。

## 安全注意事项

- `web_ui/backend/main.py` 中的 FastAPI 后端为本地开发配置了 CORS，`allow_origins=["*"]`、`allow_credentials=True`、`allow_methods=["*"]`、`allow_headers=["*"]`。这是针对 LAN 原型设计的有意宽松设置；在未添加身份验证或限制来源的情况下，不要直接将 Web UI 暴露给不受信任的网络。
- Web UI 或 WebSocket 控制通道上没有内置的身份验证层。任何具有车辆/后端网络访问权限的人都可以发送驱动命令、查看视频流以及启动/停止训练。
- WebRTC 信令和 MJPEG 回退视频是局域网功能。在公共或共享 Wi-Fi 上运行之前，请考虑网络分段。
- 车辆端模板和 `myconfig.py` 可能包含硬件凭证或引脚。如果生成的车辆目录包含 SSH/MQTT 或云密钥，请将其视为敏感信息。
- 不要提交密钥、`node_modules` 或构建产物。仓库已通过 `.gitignore` 排除它们。

## 部署和打包

- **setuptools 打包**：`python -m build --sdist --wheel`（或 `make package`）生成 `donkeydrifter-<version>-py3-none-any.whl` 和 `donkeydrifter-<version>.tar.gz`。CI 在发布前运行 `twine check dist/*`。
- **PyPI 发布**：`.github/workflows/publish-pypi.yml` 在标签 `v*` 上触发并通过 OIDC 发布。
- **CI / 测试**：`.github/workflows/python-package-conda.yml` 在 push/PR 时跨 `macos-latest` 和 `ubuntu-latest` 运行，创建 Python 3.11 conda 环境，安装 `.[pc,dev]`，验证 `donkeydrifter` 和 `donkeycar` 导入，构建包，并运行 `pytest`。`.github/workflows/superlinter.yml` 以非阻塞模式运行 GitHub Super-Linter。
- **Docker**：顶层 `Dockerfile` 存在但目前已过时。它使用 `python:3.6`，引用不存在的 `setup.py` 和 `[tf]` extra，并面向 Jupyter 而非 FastAPI/React Web UI。除非明确更新，否则将其视为遗留文件。

## 迁移契约

在 DonkeyDrifter 迁移期间：

- 新代码和新模板应优先使用 `donkeydrifter` 导入。
- 旧代码中的 `donkeycar` import 必须继续兼容。
- `donkeydrifter/__init__.py` 通过 `sys.meta_path` 把 `donkeydrifter.<submodule>` 映射到 `donkeycar.<submodule>`；迁移时不要破坏这个别名层。
- CLI 命令继续沿用 `donkey`。
- 第一阶段不重命名旧 `DONKEY_*` 配置键。
- 第一阶段不重命名 Web UI 的 `/api/*` 路径和驾驶 WebSocket 协议。
- 不要盲目全局替换 Donkeycar 字样；上游来源、兼容说明和许可证文本中的 Donkeycar 名称应保留。

## 重要的智能体注意事项

- 编辑模板时，新生成的车辆应用应使用 `import donkeydrifter as dk`。
- 编辑 Web UI 路由时，保持 `/api` 契约稳定，除非有单独的迁移计划更改它们。
- 更改许可证或归属文件时，保持 `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md` 和 `LICENSES/MIT-donkeycar.txt` 一致。
- TensorFlow 固定在 `2.15.*`，PyTorch 固定在 `2.1.*`；主要版本升级会影响模型兼容性。
- Tub v2 是规范的数据格式；录制逻辑集中在 `donkeycar/parts/tub_v2.py`。
- CLI 模板文件既是用户生成的应用源，也是配置契约的一部分；模板的更改通常需要在 `cfg_*.py` 文件和测试中进行匹配更新。
- 车辆端 Web UI 桥是 `donkeycar/parts/drive_api_bridge.py`（模板通过 `donkeydrifter.parts.drive_api_bridge` 导入），一个线程部件，取代了传统的 Tornado `LocalWebController`，并通过 WebSocket 将状态/视频推送到 FastAPI 后端；同时支持 WebRTC 视频轨道和 MJPEG 降级回退。

## 有用的参考

- `README.md` – 快速入门和兼容性摘要。
- `CLAUDE.md` – 面向 Claude Code 的扩展中文指南，包括命令速查表和架构说明。
- `docs/guide/donkeycar-compatibility.md` – 双导入兼容性指南。
- `docs/guide/web-drive-console-user-guide.md` – 驱动页面用户指南。
- `docs/plan/donkeydrifter-v0.1.0-release-notes.md` – 验证结果和发布说明。
- `docs/plan/web-drive-console-migration.md` 和 `docs/plan/drive-api-bridge-migration.md` – 迁移设计文档。
