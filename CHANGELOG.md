# 变更日志

## 2026-08-03

- fix(ci): 修复 "Python package and test DonkeyDrifter" 两处测试失败（PR #14 合并后 CI 变红）
  - 删除 `test_project_metadata.py::test_agent_docs_describe_donkeydrifter_migration_contract`：该用例读取仓库根的 `AGENTS.md`/`CLAUDE.md`，而 agent 说明文件已按约定移出版本控制（本地保留、`.gitignore` 排除），CI 环境不存在这两文件必然 FileNotFoundError（macOS + Ubuntu 双红）；迁移契约已由 `test_docs_include_compatibility_and_attribution_guides`（`docs/guide/donkeycar-compatibility.md`）覆盖。
  - 修复 `test_tui_restore.py::test_get_data_cache_dir`（仅 macOS 红）：`/var` 是 `/private/var` 的符号链接，`Path.cwd()` 返回解析后物理路径，期望值比较前对 `mkdtemp()` 结果补 `os.path.realpath()`。


- feat(provisioning): `ProvisioningPart` 周期向 ESP32 上报本机局域网 IP（`HOSTIP|<ipv4>` 帧）——配套 MUS4 固件 v1.7.39，Drifter Console Network 卡片 HOST 分页显示上位机 IP
  - `donkeycar/parts/provisioning.py` 新增 `detect_lan_ip()`：UDP socket connect 外部地址做路由查询（不实际发包）取默认出口 IPv4，过滤 127.x，失败回退主机名解析，均失败返回 None。
  - `ProvisioningProtocol` 新增 `build_host_ip(ip)` 构建 `HOSTIP|<ipv4>` 上行帧（Linux → ESP32，与既有 `STATUS|`/`OK|`/`FAIL|` 同通道）。
  - `ProvisioningPart` 新增 `host_ip_report`（默认 True）与 `host_ip_report_interval`（默认 10 秒）参数及 `_maybe_report_host_ip()` 节流上报：首次循环立即上报，之后每周期重新探测 IP（DHCP 换地址自愈），独立串口模式与 Arduino 共享串口模式的 `update()` 循环均已接入；ESP32 重启丢失运行时状态后 10 秒内自动恢复显示。
- fix(provisioning): 修复 `ProvisioningPart.run_threaded()` 签名不接收 inputs 传参导致整车崩溃的潜伏 bug
  - 场景：`Vehicle.update_parts()` 以 `p.run_threaded(*inputs)` 调用线程 Part，而 manage.py 注册该 Part 时带 `inputs=['provisioning/trigger']`；旧签名 `run_threaded(self)` 拒收位置参数抛 `TypeError`，Vehicle 主循环首次迭代即退出（此前 `PROVISIONING_ENABLED` 默认为 False，从未实车触发）。
  - 修复：`run_threaded(self, trigger=None)` 与 `run()` 对齐，接受可选 trigger dict 并支持手动触发配网；非 dict / None 输入安全忽略。
- 同步更新 `donkeycar/tests/test_provisioning.py`：新增 13 个用例（`detect_lan_ip` 四条路径、`build_host_ip` 帧构建、上报节流/禁用/无 IP 行为、`run_threaded` trigger 回归三条），全文件 64 项测试全部通过。
- 实车验证：mycar 启用 `PROVISIONING_ENABLED=True` 后重启 manage.py，ESP32（v1.7.39）`/api/status` 显示 `host_ip=192.168.3.41` 且 `host_ip_age_s` 每 ~10 秒刷新。


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
- fix(web_ui): Drive 遥测曲线捕捉不到 RC 手柄输入、陀螺仪 xyz 不显示——断点均在车上位机侧：RC 值解析后只缓存不发布、`HAVE_IMU` 关闭致 ArdImu 未注册、IMU 量纲超出图表固定量程
  - 新增 `ArdRc` 部件（`donkeycar/parts/actuator.py`）：把 `Arduino.Arduino_readline()` 解析 `T<t>S<s>` 帧时无条件更新的 `controller.steering/throttle`（-1..1）发布到 Memory 键 `rc/steering`、`rc/throttle`；刻意不接 `user/angle`，避免重蹈串口 RC 怠速值覆盖导致录制数据间歇跳 0 的历史问题。
  - `DriveApiBridge`（`donkeycar/parts/drive_api_bridge.py`）遥测协议扩展 `rc_steering`/`rc_throttle` 字段：`run_threaded`/`run` 签名末尾追加默认 None 参数（向后兼容，模板无需改），`field_name_map` 同步映射；后端 `routers/drive.py` 原样广播，无需改动。
  - 前端：`useDriveWebsocket.ts` `Telemetry` 接口加 `rc_steering?`/`rc_throttle?`；`TelemetryChart.tsx` 新增 RC Steering/RC Throttle 两条默认开启曲线，`CurveConfig` 新增 `scale` 显示缩放——gyro(rad/s)×0.2（对齐固件 Drifter Console 的 ÷5）、accel(m/s²)×(1/9.8)（1g 满量程），解决 y 轴固定 [-1,1] 下 IMU 曲线被裁剪成贴边直线的问题。
  - 车端接线（mycar 本机车辆目录，不随库分发）：注册 `ArdRc` 输出 `rc/steering`/`rc/throttle`、遥测桥 inputs 末尾追加两键、开启 `HAVE_IMU = True`（ArdImu 从 ESP32 `$IMU` 帧读取——此前固件 100Hz 上行一直被解析但零消费者）；ARDUINO_CONTROLLER 模式下 IMU 不写入 tub，避免新增 imu 键与既有 tub manifest schema 冲突触发 `datastore_v2` 断言、drive 启动即崩溃（本次排障实车复现并修复）。
  - 测试同步：`donkeycar/tests/test_drive_api_bridge_telemetry.py` 补 rc 字段入消息与 None 跳过断言；`web_ui/backend/tests/test_drive_telemetry_forward.py` 转发样例补 rc 字段；`TelemetryChart.test.tsx` 更新为默认 5 条曲线，新增 RC 写入与 scale 缩放用例（mock 数据集改渲染 JSON 数据，NaN 序列化为 null）。
- 验证：车端相关 `pytest` 85 项通过、后端契约 70 项通过、前端 `npm run check` + `vitest run` 47 项通过；实车实链验证：telemetry ~60Hz 含全部 rc/imu 字段（静止 az≈1g、RC 中位抖动合理），WebRTC 视频 60fps 发送、浏览器 53fps 接收。
- feat(web_ui): Drive 遥测接入固件 `M<m>:P<p>` 帧——Drive 页直接显示固件模式与 Park 手刹锁定徽标；实车探针借此定案 RC Throttle 恒精确 0 的根因是固件 Park 手刹锁定（rc_park=1 时 ESP32 SafetyState 持续钳油门、转向不钳），并非遥测链路故障
  - `donkeycar/parts/actuator.py`：`Arduino.__init__` 新增 `mode_data` 缓存，`Arduino_readline()` M 分支解析后无条件写入（此前 M 帧 1Hz 到达上位机但只解析不发布）；`ArdRc.run_threaded()` 扩展为四元输出 `(steering, throttle, mode, park)`，mode/park 未收到 M 帧时为 None，仅注册两键的旧调用方不受影响。
  - `DriveApiBridge`（`donkeycar/parts/drive_api_bridge.py`）：`run_threaded`/`run` 签名在 `rc_throttle` 后插入 `rc_mode`/`rc_park`（默认 None，None 字段跳过不发；插入点位于无任何位置调用方的 drift 参数之前，实车模板位置解包已对齐核对）。
  - 前端：`useDriveWebsocket.ts` `Telemetry` 接口加 `rc_mode?`/`rc_park?`；`DrivePage.tsx` 摄像头画面下方新增徽标行——`rc_park===1` 显示红色"Park 锁定 · 油门被钳 0"，并常显"固件模式：手动/半自动/全自动"。
  - 车端接线（mycar 本机车辆目录，不随库分发）：`ArdRc` 注册四输出 `rc/steering`/`rc/throttle`/`rc/mode`/`rc/park`，遥测桥 inputs 末尾同步追加 `rc/mode`、`rc/park` 两键（位置 17-18 与桥签名一致）。
  - 测试同步：`donkeycar/tests/test_drive_api_bridge_telemetry.py` 补 rc_mode/rc_park 入消息与 None 跳过断言；`web_ui/backend/tests/test_drive_telemetry_forward.py` 转发样例补两字段。
- 验证：库遥测测试 6 项、后端契约 2 项、`test_actuator.py` 25 项、前端 `npm run check` + `vitest run`（47 项）+ `build` 全部通过；实车实链探针 15s 收 897 条遥测（~60Hz）确认 rc_mode/rc_park 正常流动，rc_park=1 与 RC Throttle 精确 0 的因果关系成立。

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
