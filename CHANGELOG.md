# 变更日志

## 2026-08-02

- feat(tui): TUI `open` 命令在仅有一个有效项目时自动打开（PR #5，已合并 main）
  - `OpenProjectCommand.execute()`（`donkeycar/management/tui.py`）新增单项目分支：扫描 `~/projects` 后若恰好只有 1 个有效项目（含 `manage.py` + `myconfig.py`），打印提示并直接调用 `_change_to_project()` 切换进入，显示成功面板后按回车返回菜单，不再要求输入编号。
  - 0 个项目时保留"未找到有效项目"提示；多个项目时保留原有编号手动选择流程，行为均不变。
  - 启动前的 `_auto_open_project()` 原有单项目自动打开逻辑不变。
- 同步更新 `donkeycar/tests/test_tui_project_selection.py`：新增 2 个用例（单项目自动打开且不要求输入编号、多项目仍手动选择编号），全文件 11 项测试全部通过。
- feat(tui): `drive` 命令未进入项目时不再拦截，仅有一个项目时自动进入后再打开 Web Console
  - `DriveCommand.execute()`（`donkeycar/management/tui.py`）移除非 mycar 目录的红色拦截：扫描 `~/projects` 后若恰好只有 1 个有效项目，打印提示并自动调用 `_change_to_project()` 切换进入，再照常进入命令预览与确认流程。
  - 0 个或多个项目时显示黄色提示"仍将打开 Web Console 驾驶控制台，但不会启动车辆进程（manage.py）"，流程继续而不再直接退出；已在有效项目内时行为不变。
- 同步更新 `donkeycar/tests/test_tui_project_selection.py`：新增 3 个用例（单项目自动进入并记录 last_project、无项目时不拦截且不切目录、多项目时不自动进入），全文件 14 项测试全部通过。
- feat(tui): `web` 命令启动 Web UI 后自动打开浏览器
  - `WebUICommand.get_command_line()`（`donkeycar/management/tui.py`）追加 `--open`（含无 bundled 路径分支）：启动前后端后自动打开浏览器直达 Web UI 首页，不再需手动输入地址。`drive` 命令此前已带 `--open --route /drive`，`donkey_ui` 为 Kivy 桌面窗口不涉及。
- 同步更新 `donkeycar/tests/test_tui_web_command.py`：原有用例增加 `--open` 断言，新增无 bundled 路径分支用例；连同项目选择测试共 16 项全部通过。
- feat(web_ui): 顶栏新增"切换 UI 风格"分段选择条——点选分段即可切换 MUS4 Web Console（ESP32 页面）皮肤或 Donkey 默认皮肤，仅换视觉风格，功能与布局位置完全不变
  - 新增 `web_ui/frontend/src/themes/theme-mus4.css`：全部规则以 `html.theme-mus4` 前缀覆写高频 Tailwind 编译类（背景 `#101318`、面板 `#171c24`、边框 `#2b3441`、强调 `#5cc8ff`、胶囊按钮、system-ui 字体），不含任何布局属性，tsx 组件零改动；末尾另有一条仅针对 SkinSwitcher 激活段的加深规则（`#05070a`，纯颜色）。
  - 新增 `web_ui/frontend/src/store/useUiPrefsStore.ts`：zustand + persist（`donkey-ui-prefs`）持久化 `skin: 'donkey' | 'mus4'`，默认 donkey 原风格，刷新保持，对外提供 `setSkin(skin)`。
  - `Layout.tsx` 顶栏右端渲染分段选择条 `SkinSwitcher`（`web_ui/frontend/src/components/SkinSwitcher.tsx`）：pill 容器内并排 "ESP32 UI" 与 "Donkey UI" 两个分段，点击分段直接切到对应皮肤，当前生效分段背景明显加深（active 态，`aria-pressed`），一眼可辨当前 UI，六个标签页均可见；`main.tsx` 引入主题 CSS，`theme-mus4` class 切换逻辑保留在 `Layout.tsx`。
  - 新增 `web_ui/frontend/src/components/SkinSwitcher.test.tsx`（4 项用例：双分段渲染、默认激活 Donkey UI、点击切至 mus4 且 active 跟随、切回 donkey）；另新增 `src/setupTests.ts` 提供内存版 localStorage（Node ≥22 的实验性 localStorage 遮蔽 jsdom 实现，导致 zustand persist 在测试环境无存储可用），并在 `vite.config.ts` 注册 `setupFiles`。
  - chart.js 图表线条颜色由 JS 传入，不随皮肤切换。
- 验证：`npm run check` / `lint` / `vitest run`（45 项）/ `build` 全部通过。
- feat(web_ui): ESP32 皮肤向 Drifter Console 进一步对齐——补齐面板外框与红/绿/蓝三色视觉
  - `web_ui/frontend/src/themes/theme-mus4.css`（仍为纯视觉覆写，tsx 组件零改动）：
    - 面板外框：`.bg-zinc-900` 面板叠加 ESP32 `.stateCard` 同款对角渐变 `linear-gradient(135deg,#1c2430,#121821)`；并用 `outline + outline-offset:-1px` 为全部面板与内层信息块（`.bg-zinc-900*`、`.bg-zinc-800*`）绘制 1px 内嵌细框——不动布局、不覆盖 Tailwind 投影（Donkey 大量信息块本不带 border 类，此前切到 ESP32 皮肤后看不到框）。
    - 三色状态框：绿 `#39d98a`（emerald 系，正常/开启）、红 `#ef4444`（red 系，关闭/异常）、蓝 `#5cc8ff`（cyan 系，信息）分别给对应语义表面加同色系内嵌框，对应 Drifter Console 的 parkUnlocked/parkLocked/信息态边框；警告黄统一为 ESP32 的 `#ffcc66`（原 `#f59e0b`），amber 文字/表面/边框同步替换。
    - 原有边框更可见：`border-zinc-700` 提为 `#344154`（同 ESP32 `.stateCard` 边框），`border-white/10` 由半透明白改为灰蓝实色。
    - SkinSwitcher 激活段在 ESP32 皮肤下叠加青色描边，当前分段更醒目。
  - 文件头部注释的允许属性清单新增 `background-image` 与 `outline/outline-offset`，仍禁止一切布局属性。
- 验证：`npm run check` / `lint`（仅 2 条既有 warning）/ `vitest run`（45 项）/ `build` 全部通过。
- feat(web_ui): ESP32 皮肤第二轮回访——驾驶页模式按钮三着色与录制键红框（本机 Firefox headless 截图逐项验证）
  - 驾驶模式选择器按 Drifter Console 模式卡（.mode0/.mode1/.mode2）着色：仅激活分段变色——手动=绿 `#39d98a`、半自动=黄 `#ffcc66`、全自动=蓝 `#5cc8ff`，各带同色内嵌框；选择器锚定 `DriveModeSelector` 独有容器签名（`inline-flex rounded-lg overflow-hidden`），全仓库无第二处匹配。
  - 录制键常态叠加红色内嵌框（record = red 语义），选择器 `button.inline-flex.rounded-lg.bg-zinc-800:not(.border)` 全仓库仅匹配驾驶页录制键；红色状态框组补 `bg-red-400/10`（视频降级徽章）。
  - 验证方式：本机 snap Firefox 151 headless + selenium（/tmp venv，未动系统环境）分别截取 Donkey/ESP32 两种皮肤的 Tub Manager 与 Drive 页面对比图，并用 JS 强制切换 active 态逐一确认三个模式按钮的绿/黄/蓝渲染；`npm run build` 通过。
- fix(ci): 修复 "Python package and test DonkeyDrifter" 工作流持续失败——裸 pytest 收集范围、mamba 弃用、可选依赖缺失与过时断言四类问题，CI 恢复可用
  - 新增根级 `pytest.ini`（仅 `testpaths = donkeycar/tests tests`）：裸 `pytest` 不再收集 `web_ui/`，与后端契约测试的独立依赖隔离，也避免误收集 `web_ui/` 根目录的临时调试脚本。
  - `.github/workflows/python-package-conda.yml`：删除 `mamba-version: "*"`（mamba 在 macOS runner 上触发 codesign 错误导致建环境失败，默认 conda 已足够）；新增 "Run backend contract tests" 步骤（`cd web_ui/backend && pip install -r requirements.txt && python -m pytest tests -q`），后端契约测试正式纳入 CI。
  - `web_ui/backend/requirements.txt` 末尾补充 `httpx2`（starlette TestClient 的 HTTP 客户端依赖，此前后端测试环境缺包报错）。
  - 测试适配（均为测试代码落后于既有实现、实现侧无回归，仅改测试）：
    - `tests/test_auth_part.py` 整文件重写，适配 AuthPart 惰性初始化（`setup()` 已在 `8427cf5d` 刻意移除），17 项通过。
    - `donkeycar/tests/test_serial2.py` 适配四态状态机，34 项通过。
    - `donkeycar/tests/test_tui_drive.py` 三处端口断言 8000→8100（`ee5439e1` 的有意变更），10 项通过。
    - 可选依赖缺失时跳过而非报错：`test_dgym_reconnect.py` 增加 `pytest.importorskip("gym_donkeycar")`、`test_torch.py` 模块级 importorskip torch 与 pytorch_lightning、`test_train.py` fastai_linear 用例 importorskip fastai。
    - `web_ui/backend/tests/test_branding.py` 标题断言更新为 'DonkeyDrifter Web UI'、根路径按前端 dist 是否存在分支断言；`test_provisioning.py` monkeypatch 目标改为 `donkeycar.parts.provisioning`、缺 ssid 期望码 400→422；后端契约 70 项全部通过。
  - 验证：本地 donkey 环境全量裸 `pytest`（`donkeycar/tests` + 根级 `tests/`）全绿。
- chore(repo): 解除 `web_ui/frontend/dist/` 编译产物的版本追踪（7 个历史遗留文件 `git rm --cached`，本地文件保留；`dist` 本就在 `web_ui/frontend/.gitignore` 中，此后新产物不再入库）。

## [0.1.2] — 2026-06-30

### 驾驶页面 (Drive UI)
- 新增 WebRTC 低延迟视频传输支持，含 MJPEG 自动回退机制
- 添加垂直油门指示器并重构控制栏布局
- 实现侧边面板多抽屉切换，菜单项支持图标与悬停交互效果
- 浮动触发按钮跟随侧边抽屉动画
- 新增实时视频延迟显示、FPS 统计与 WebRTC 连接状态追踪
- 输入源选择器重构并补充单元测试

### 后端 (Backend)
- 新增 WebRTC 信令服务（offer/answer/ICE 候选），含 TURN/ICE 服务器配置
- 实现模拟器自动恢复机制（检测、重连、状态同步）
- 新增局域网车辆扫描与连接优化
- 配置热重载与模拟器扫描优化
- WebSocket 连接异常处理与失效连接清理
- 新增 Drive API Bridge 远程驾驶桥接（含 WebRTC 视频流）
- 驾驶统计详情与录制条数即时同步

### CLI / TUI
- TUI 新增项目管理功能
- Web 命令自动打开浏览器、自动选择可用端口
- 新增调试模式支持并屏蔽冗余第三方日志
- 进程管理重构并补充测试

### 核心库 (Donkeycar)
- Arduino 控制器新增 IMU 数据支持
- 新增 ESP32 串口认证组件与单元测试
- 新增 Serial2 双向连通测试部件及端口扫描功能
- 修复 DGym 连接崩溃问题，调整默认端口并添加重连测试
- 修复 myconfig 模板中 DONKEY_GYM 默认值

### 文档 (Docs)
- 新增基于 Git Worktree 的并行开发指南
- 新增 Drive 60FPS WebRTC 设计规格
- 新增 WebRTC TURN 配置设计与视频加载优化方案
- AGENTS.md 中文本地化并持续更新

### 构建与配置
- 添加 gymnasium 和 pygame 模拟器依赖
- 环境变量配置支持（前端 API 地址、调试模式等）
- 忽略 worktree 目录

---

## [0.1.1] — 初始发布

- 基于 Donkeycar 派生的模块化自驾与漂移机器人平台
- Vehicle + Memory + Part 核心运行时架构
- Tub v2 数据录制格式
- Keras / TensorFlow / PyTorch 训练管道
- 统一 Web UI（FastAPI 后端 + React/Vite 前端）
- ESP32 串口协议与 Arduino 控制器
- CLI 工具链（createcar、calibrate、web、train 等）
- 模拟器集成（DonkeyGym）
