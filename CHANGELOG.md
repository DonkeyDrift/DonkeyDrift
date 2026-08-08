# 变更日志

## 2026-08-08

- feat(web_ui): Web UI 全站中英文国际化（i18n）：默认中文（逐字保留现有中英混排界面），可一键切换为全英文界面，语言选择持久化、关机重启后保留
  - 新增 `web_ui/frontend/src/i18n/`：`index.tsx` 提供 `LanguageProvider`、`useTranslation()` hook 与供普通模块（services/stores）使用的独立 `t()`；支持 `{var}` 插值，回退链为 当前语言 → zh → key 本身；语言选择写入 localStorage `donkeydrifter.ui.lang`，首次访问默认 `zh`。`messages/` 下按 10 个命名空间组织字典（common/fab/tubnav/tubeditor/trainer/arena/connector/drive/driveviz/drivehooks），共 427 对 zh/en 词条，zh 侧逐字镜像现有界面，en 侧为完整英文翻译。
  - `web_ui/frontend/src/main.tsx` 挂载 `LanguageProvider`；顶栏 `LanguageSwitcher.tsx` 由占位改为真实切换；右下角 `FabActions.tsx` 语言菜单改接 i18n 上下文（两处切换等效），帮助弹窗全部文案走 `fab.*` 字典。
  - 全站 40+ 源文件（pages/components/hooks/services）的用户可见字符串——含标题、按钮、label、placeholder、aria-label、title、alt、canvas fillText、图表 legend、alert/confirm/toast/setError 及状态枚举→显示映射——全部改走 `t()`；品牌名、后端数据值（模型名/tub 名/路径/错误 message）、协议枚举值、`<kbd>` 键名、单位按约定不译。
  - 顺带修复（工作中发现）：`pages/PilotArenaPage.tsx` 模型类型加载失败分支改用 `getApiErrorMessage`（原直接渲染英文 `error.message`，与全页其他 5 处不一致）；`components/drive/VideoStream.tsx` 删除被重复注册一遍的 MJPEG 淡出 `useEffect`；`tubEditor.restoreTitle` 快捷键提示由双反斜杠 `(\\)` 修正为单 `\`；`SimulatorConfig` toast 与 `FileBrowserModal` 的关闭按钮补 `aria-label`（新增 `common.close` 词条）。
  - 测试同步：`components/LanguageSwitcher.test.tsx` 重写为 3 项用例（默认中文激活、点击切换并持久化、重新挂载恢复选择）；新增 `components/FabActions.test.tsx` 2 项用例（默认中文渲染、持久化 en 时英文渲染）；其余测试因 zh 逐字镜像原界面无需改动。验证：`tsc -b --noEmit` 零错误、`vitest` 54/54 通过、`npm run build` 通过；脚本核对 427 对词条 zh/en 完全对等、代码引用 key 无一缺失、无残留硬编码界面文案（注释与 console 除外）。

- feat(web_ui): MUS4 皮肤固化为永久主题并新增顶栏 GitHub 链接与语言切换组件（此前未提交界面统一改动，随本次一并入库）
  - `web_ui/frontend/index.html`：`<html>` 硬设 `class="theme-mus4"`；`web_ui/frontend/src/main.tsx` 无条件引入 `themes/theme-mus4.css`（不再存在运行时主题切换器）。
  - `web_ui/frontend/src/themes/theme-mus4.css`：文档头重写为"永久主题"约定，并补齐 ESP32 Drifter Console 的填充/线框视觉语言说明与对应规则（选中态实心 `#5cc8ff` + 近黑文字、状态色绿/黄/红/灰线框等）。
  - 新增 `web_ui/frontend/src/components/GitHubLink.tsx`（+ `GitHubLink.test.tsx`）：顶栏 GitHub 仓库链接图标；新增 `web_ui/frontend/src/components/LanguageSwitcher.tsx`（初版为占位组件，本次已接通真实切换，见上条）。
  - 测试同步：`GitHubLink.test.tsx` 2 项用例通过。

- feat(web_ui): 右下角帮助入口改为复刻 ESP32 Drifter Console 的 FAB 组合（发光圆点开关 + 语言球 + 帮助球 + 语言菜单 + 帮助弹窗），并移除底部页脚
  - 新增 `web_ui/frontend/src/components/FabActions.tsx`（替代 `web_ui/frontend/src/components/HelpModal.tsx`）：1:1 复刻 ESP32 `WebConsoleAssets.h` 的 `.fabToggle`（18px 发光青点、双层辉光阴影、hover 放大 1.18 倍）、`.fabActions` 展开动画（语言球上飞 56px、帮助球左飞 56px、.18s 过渡）、`.langFab`（46px 蓝球 🌐）/ `.helpFab`（46px 青球深色粗体 ?）、`.langMenu`（中文/English 菜单、选中高亮、选择持久化到 localStorage `donkeydrifter.ui.lang`）与 `.helpModal`（右下角锚定、`#5cc8ff` 边框渐变面板）；document 级点击收起行为与 ESP 一致。帮助弹窗中的快捷键列表内容保持 DonkeyDrifter 独有（播放控制 / 时间轴导航 / 选择与图表）。
  - 弹窗关闭按钮 × 与 Drifter Console「功能说明」弹窗统一为幽灵样式（28px 透明底 + `#a1a1aa`，hover `#27272a` 底白字）。
  - `web_ui/frontend/src/components/Layout.tsx`：移除底部页脚行（`<footer>` 品牌文字行）；`HelpModal` 引用替换为 `FabActions`。
  - `web_ui/frontend/src/themes/theme-mus4.css`：移除旧的 help 按钮颜色覆盖段（组件已内置 ESP 样式，覆盖段会破坏一致外观）。
  - 验证：`npm run check`（tsc）与 `npm run test`（vitest）通过；Playwright 截图核对收起 / 展开 / 语言菜单 / 帮助弹窗四态外观。

## 2026-08-07

- fix(provisioning): 配网后台线程异常防护与上位机 IP 停报诊断日志
  - 背景（实车排查）：ESP32 经 HTTP OTA 重启后，manage.py 进程的 HOSTIP 周期上报曾长时间静默停止（线程存活、串口 fd 正常、日志无任何记录），只能等进程自愈或重启；为根因定位与兜底防护做两处加固。
  - `donkeycar/parts/provisioning.py`：`update()` 两个后台循环（独立串口模式 / Arduino 共享模式）循环体加 `try/except Exception`，异常经 `logger.exception` 记录后继续运行，线程不再因未捕获异常静默死亡；`_maybe_report_host_ip()` 新增 `_host_ip_skip_count` 计数——`detect_lan_ip()` 连续探测失败时按「首次 + 每 30 次」限频输出 WARNING 告警，恢复时输出 INFO 日志（含此前连续跳过次数）。
  - 测试同步：`donkeycar/tests/test_provisioning.py` 新增 `test_no_ip_detected_warns_rate_limited_and_recovers`（限频告警与恢复日志）与 `TestProvisioningPartUpdateResilience::test_loop_continues_after_unexpected_exception`（循环连续抛异常后线程仍存活、上报仍执行）。
  - 验证：`pytest donkeycar/tests/test_provisioning.py` 94 项全部通过。

- refactor(web_ui): UI 品牌名从 `DonkeyDrifter Web UI` 统一简化为 `DonkeyDrifter`
  - 前端：`web_ui/frontend/index.html` 浏览器标签页标题改为 `DonkeyDrifter`；`web_ui/frontend/src/components/Layout.tsx` 页脚品牌文字同步修改（顶部导航本来即为 `DonkeyDrifter`，无需改动）。
  - 后端：`web_ui/backend/main.py` FastAPI `title` 改为 `DonkeyDrifter`，根路径两条 JSON 提示消息改为 `DonkeyDrifter is running`。
  - CLI：`donkeycar/management/tui.py` TUI 选项 6 的启动提示文案「将启动 DonkeyDrifter 的 Drive 标签页」同步修改。
  - 测试同步：`web_ui/backend/tests/test_branding.py`（标题与根消息断言）、`donkeycar/tests/test_web_ui_branding.py`（index.html 标题断言）更新为新名称；验证两组测试全部通过（2 + 3 passed）。`CHANGELOG.md` 与 `docs/` 中的历史记录保持原样未动。

- feat(web_ui): 移除 Web UI 的 Calibrate 校准功能，舵机/电调 PWM 校准统一在 ESP32 Drifter Console（Web Console）中进行
  - 前端：删除 `web_ui/frontend/src/pages/CalibratePage.tsx`（5 个 PWM 滑杆校准页面）；`web_ui/frontend/src/App.tsx` 移除 `/calibrate` 路由与 `CalibratePage` 懒加载；`web_ui/frontend/src/components/Layout.tsx` 移除顶部导航 Calibrate 入口；`web_ui/frontend/src/services/api.ts` 移除 `sendCalibrate()`。
  - 后端：`web_ui/backend/routers/drive.py` 移除 `CalibrateRequest` 模型与 `POST /api/drive/calibrate` 端点（原实现向车端 WebSocket 下发 `type=calibrate` 消息）。
  - 文档：`docs/guide/web-drive-console-user-guide.md` 移除「校准页面」章节、导航表 Calibrate 行、API 表 `/calibrate` 行及文件结构中的 `CalibratePage.tsx`，新增简短「校准」说明指向 ESP32 Drifter Console 与 `donkey calibrate --channel` CLI。
  - 验证：后端 `python -m pytest tests -q` 70 项全绿；前端 `npm run test` 47 项全绿、`npm run check`（tsc）无错误、`npm run lint` 0 errors（2 个既有 warning 与本次无关）。

- fix(cli): 第二次启动 `donkey drive` 时自动杀掉上一次启动的进程，释放摄像头等硬件资源，避免旧进程占用硬件导致车端离线
  - 新增 PID 记录文件 `~/.donkeycar/drive.pid`：`donkeycar/management/base.py` 与 `donkeycar/management/tui.py` 各提供一组 `_read_drive_pid_file()` / `_write_drive_pid_file()` / `_remove_drive_pid_file()` / `_kill_previous_drive_processes()` 辅助函数；`Drive.run()`（CLI）与 TUI 选项 6 `DriveCommand` 在启动新进程前读取 PID 文件，先 SIGTERM 优雅终止、0.5s 后对仍存活进程 SIGKILL，随后删除 PID 文件。
  - 只精确杀掉 PID 文件中记录的进程（前端 / 后端 / 车端三个子进程），不按端口扫杀，不会误杀其他程序；进程已不存在时静默跳过。本次启动成功后写入新的三个 PID；后端就绪超时或正常 Ctrl+C 退出时清理 PID 文件。
  - 影响范围：CLI `donkey drive` 命令与 TUI 选项 6（DriveCommand）。
  - 测试同步：`donkeycar/tests/test_drive_command.py` 的 `_FakeProcess` 补 `pid` 属性（原用例未随 PID 记录功能更新而失败）；`test_drive_run_spawns_three_processes_and_injects_env` 将 `_DRIVE_PID_FILE` monkeypatch 到临时目录，避免测试读写真实 `~/.donkeycar/drive.pid` 误杀实车进程。验证：`test_drive_command.py` / `test_tui_drive.py` / `test_tui_menu.py` 共 21 项全部通过。

- fix(web_ui): 移除前端右下角的 TRAE SOLO badge
  - `web_ui/frontend/package.json`：移除 devDependency `vite-plugin-trae-solo-badge`；`web_ui/frontend/vite.config.ts`：移除 `traeBadgePlugin` 的 import 与插件配置（dark / bottom-right / prodOnly / 点击跳转 trae.ai）。

- fix(ci): 修复 "Python package and test DonkeyDrifter" 工作流持续失败——裸 pytest 收集范围、mamba 弃用、可选依赖缺失与过时断言四类问题，CI 恢复可用（PR #11，已合并 main）
  - 新增根级 `pytest.ini`（仅 `testpaths = donkeycar/tests tests`）：裸 `pytest` 不再收集 `web_ui/`，与后端契约测试的独立依赖隔离，也避免误收集 `web_ui/` 根目录的临时调试脚本。
  - `.github/workflows/python-package-conda.yml`：删除 `mamba-version: "*"`（mamba 在 macOS runner 上触发 codesign 错误导致建环境失败，默认 conda 已足够）；新增 "Run backend contract tests" 步骤（`cd web_ui/backend && pip install -r requirements.txt && python -m pytest tests -q`），后端契约测试正式纳入 CI。
  - `web_ui/backend/requirements.txt` 末尾补充 `httpx2`（starlette TestClient 的 HTTP 客户端依赖，此前后端测试环境缺包报错）。
  - 测试适配（均为测试代码落后于既有实现、实现侧无回归，仅改测试）：
    - `tests/test_auth_part.py` 整文件重写，适配 AuthPart 惰性初始化（`setup()` 已在 `8427cf5d` 刻意移除），17 项通过。
    - `donkeycar/tests/test_serial2.py` 适配四态状态机，34 项通过。
    - `donkeycar/tests/test_tui_drive.py` 三处端口断言 8000→8100（`ee5439e1` 的有意变更），10 项通过。
    - 可选依赖缺失时跳过而非报错：`test_dgym_reconnect.py` 增加 `pytest.importorskip("gym_donkeycar")`、`test_torch.py` 模块级 importorskip torch 与 pytorch_lightning、`test_train.py` fastai_linear 用例 importorskip fastai。
    - `web_ui/backend/tests/test_branding.py` 标题断言更新为 'DonkeyDrifter Web UI'、根路径按前端 dist 是否存在分支断言（品牌名当日晚些时候再次简化为 `DonkeyDrifter`，断言随之更新，见上方 refactor 条目）；`test_provisioning.py` monkeypatch 目标改为 `donkeycar.parts.provisioning`、缺 ssid 期望码 400→422；后端契约 70 项全部通过。
  - 验证：本地 donkey 环境全量裸 `pytest`（`donkeycar/tests` + 根级 `tests/`）478 passed, 16 skipped 全绿。
- chore(repo): 解除 `web_ui/frontend/dist/` 编译产物的版本追踪（7 个历史遗留文件 `git rm --cached`，本地文件保留；`dist` 本就在 `web_ui/frontend/.gitignore` 中，此后新产物不再入库）。

## 2026-08-06

- feat(web_ui): Calibrate 页面新增 RC Channels 实时面板，与 ESP32 Drifter Console 双向同步（后端 WiFi 直连 ESP32，不动固件、无需车端 manage.py 在跑）
  - 链路：后端作为 WS 客户端直连 ESP32 遥测端口（`ws://<host>:81/`，~60Hz 二进制帧 'M4'/v2），解析出 RC Channels 字段（ch1..ch6 各通道脉宽、sd/ed 输出 duty、sm/mm 转向/油门中点、tl/tu 油门上下限、mode/park/vol）缓存并节流（200ms，对齐 ESP32 UI 的 RC DOM 刷新）广播给浏览器；浏览器下发的 `SERVO_MID`/`MOTOR_MID`/`THROTTLE_MIN`/`THROTTLE_MAX` 命令经后端 HTTP `POST /api/cmd?target=web` 转发 ESP32（首次自动 `AUTH:`，密码可配，默认为空）。两个 UI 以 ESP32 固件为唯一数据源，任一侧修改经遥测广播同步到另一侧，双向同步天然成立。
  - 后端新增 `web_ui/backend/routers/esp32.py`：`Esp32Link` 单例管理到 ESP32 的 WS 重连循环（3s 退避、配置变更 kick 立即重连）、遥测解析 `parse_telemetry_frame()`（`struct '<4BIIIHhh6fBB6H4h2fBB2f4H2h'` 与固件 `WebTelemetry.cpp::pushWifiWebSocketData()` 逐字段对齐）、命令白名单（仅 4 条校准命令，正则严格校验）、浏览器 WS 通道与空闲释放（浏览器全部断开 30s 后释放 ESP32 连接——固件仅允许 2 个并发 WS 客户端）；路由 `GET /api/esp32/status`、`GET/POST /api/esp32/config`、`POST /api/esp32/command`、`WS /api/esp32/ws`，挂载于 `web_ui/backend/main.py`。连接配置（host/password）持久化到 `esp32_link.json`（目录约定同 `drive_params.json`：DONKEY_CAR_DIR → ~/mycar → backend/data），默认 host `mus4-esp.local`（固件默认 AP SSID `MUS4-ESP` 的 mDNS 名），可用 `ESP32_HOST` 环境变量覆盖。
  - 前端新增 `web_ui/frontend/src/hooks/useEsp32Rc.ts`（连 `/api/esp32/ws`，处理 `esp32_state` 快照与 `esp32_rc` 广播，3s 自动重连，命令 100ms latest-value-wins 节流）与 `web_ui/frontend/src/components/calibrate/RcChannelsPanel.tsx`——1:1 复刻 ESP32 UI 的 RC Channels 面板：6 通道网格（CH4 Mode 黄色高亮边框、窄屏 3 列）、OUT Steering/Throttle 行、Mid S/Mid T（Set 按钮把当前 OUT 值设为中点）、Min T/Max T 滑杆（Min T 上限=Mid T、Max T 下限=Mid T 动态跟随，量程 4915-9830），样式沿用固件 rcCell 配色（#0d1219/#2b3441/#8fa1b5）；滑杆拖动期间用本地值避免遥测回跳。面板头部含连接状态点、主机设置（保存并重连）与手动重连按钮。`web_ui/frontend/src/services/api.ts` 新增 `Esp32RcTelemetry`/`Esp32Status` 类型与 `getEsp32Status`/`getEsp32Config`/`setEsp32Config`/`sendEsp32Command`/`getEsp32WebSocketUrl`。`web_ui/frontend/src/pages/CalibratePage.tsx` 顶部集成该面板；原有 5 个 PWM 滑杆（面向 PCA9685 直驱车型）保留不变。
  - 测试同步：新增 `web_ui/backend/tests/test_esp32.py` 13 个契约用例（路由挂载经 `collect_route_paths`、帧解析含坏 magic/短帧拒绝、配置持久化与非法 host 拒绝、命令白名单/首次 AUTH/ACK/NACK/认证失败 502/不可达 502、WS 快照与遥测广播）；前端新增 `src/hooks/useEsp32Rc.test.tsx` 与 `src/components/calibrate/RcChannelsPanel.test.tsx` 共 7 用例（标签渲染、Set 按钮下发 SERVO_MID/MOTOR_MID 当前 OUT 值、滑杆节流命令、Max T 下限跟随 Mid T、离线禁用控件）。
  - 验证：后端 `python -m pytest tests -q` 83 项全绿；前端 `npm run test` 54 项全绿、`npm run check` 无错误、`npm run lint` 0 errors（2 个既有 warning 与本次无关）、`npm run build` 成功；另用伪 ESP32（websockets + http.server）做实链路冒烟：二进制帧→浏览器广播、AUTH→命令 ACK、空闲自动释放连接全部符合预期。待实车联调（需 ESP32 在线时打开 Calibrate 页验证真实遥测与命令回环）。

- refactor(web_ui): 移除 UI 皮肤切换功能，Web UI 只保留 DonkeyDrifter 自身皮肤
  - 删除 `web_ui/frontend/src/components/SkinSwitcher.tsx`（顶栏 `Drifter Console UI` / `DonkeyDrifter Web UI` 分段切换按钮）及其测试 `SkinSwitcher.test.tsx`、`web_ui/frontend/src/store/useUiPrefsStore.ts`（zustand 持久化皮肤状态）、`web_ui/frontend/src/themes/theme-mus4.css`（MUS4/ESP32 Drifter Console 皮肤样式表）。
  - `web_ui/frontend/src/components/Layout.tsx`：移除 SkinSwitcher 渲染与 `theme-mus4` class 切换副作用；`web_ui/frontend/src/main.tsx`：移除 theme-mus4.css 导入；`web_ui/frontend/src/components/drive/DriveModeSelector.tsx`：清理引用 theme-mus4.css 的过期注释（`data-mode`/`mode-active` 钩子保留，仍被测试使用）。
  - 验证：`npm run test`（vitest 8 文件 47 用例全部通过）、`npm run check`（tsc 无错误）、`npm run lint`（0 errors，2 个既有 warning 与本次无关）。
  - 配套：ESP32 固件仓库（`Firmware/MUS4_FW`）同步移除 Web Console 的 DonkeyDrift 皮肤与切换按钮，两边各自只保留自己的 UI。

- fix(provisioning): 修复 TUN 模式 VPN 运行时 ESP32 Drifter Console HOST 分页显示错误上位机 IP（198.18.0.1，ESP32 不可达）的问题
  - 根因：`donkeycar/parts/provisioning.py` 的 `detect_lan_ip()` 用 UDP socket connect `8.8.8.8` 做路由查询取默认出口 IP；Clash Meta/mihomo 等 TUN 模式 VPN 会劫持默认路由到虚拟接口（本机 `Meta` 接口，198.18.0.1/30，属 198.18.0.0/15 基准测试网段伪装的假 IP），内核应答的源地址即为 VPN 假 IP，经 `HOSTIP|<ipv4>` 帧上报后 ESP32 Web Console Network 卡片 HOST 分页显示 198.18.0.1 而非真实局域网地址 192.168.3.41。
  - 修复：`detect_lan_ip()` 改为分级探测——① UDP 路由查询结果（默认出口 IP）是 RFC1918 私有地址**且不位于虚拟接口上**时直接返回（无 VPN/分流 VPN 的常见路径，行为不变）；② 出口被 VPN 劫持或 UDP 查询失败（离线局域网）时，先经 `_physical_default_iface()` 解析 `ip route show default` 找残留的物理网关默认路由（mihomo auto-route、OpenVPN def1、wg-quick 策略路由均会保留高 metric 的物理默认路由），取其接口上的 RFC1918 地址；③ 物理默认路由被完全移除时，用 `_select_lan_ip()` 从 `_enum_inet_entries()`（解析 `ip -4 -o addr show`）的接口地址表中选择——跳过回环与虚拟接口（docker/br0/br-/lxdbr/veth/tun/tap/wg/Clash Meta 等，见 `_VIRTUAL_IFACE_RE`），优先物理命名接口（wl*/en*/eth*/usb*/bond*）；④ 仍无结果保留旧行为返回默认出口地址（公网直连兼容），最后回退主机名解析。新增 `_is_rfc1918()` 统一判定 10/8、172.16/12、192.168/16，显式排除 198.18/15（VPN 假 IP）、100.64/10（CGNAT/Tailscale）、169.254/16（链路本地）。
  - 关键分支：UDP 查询结果为 RFC1918 时须先确认其接口不在 `_VIRTUAL_IFACE_RE` 之列——全隧道 WireGuard/OpenVPN 会把 10.x 隧道地址分到 wg0/tun0 并劫持默认路由，只看地址段会把隧道 IP 报给 ESP32（与 198.18.0.1 同一故障模式）。
  - 测试同步：`donkeycar/tests/test_provisioning.py` 的 `TestDetectLanIp` 全部改为 hermetic 风格（`_mock_udp`/`_mock_net` 辅助 mock socket 与两个 `ip` 命令解析函数），含 2 个 VPN 劫持回归用例（198.18 假 IP、RFC1918 隧道地址）；新增 `TestIsRfc1918`（11 个参数化地址判定）、`TestSelectLanIp`（物理优先于靠前非虚拟、跳过虚拟接口、lxdbr0/br0 网桥与 bond0 命名、非虚拟兜底、无可用地址 5 用例）、`TestEnumInetEntries`（`-o` 格式解析含 veth `@ifN` 后缀剥离、命令失败 2 用例）、`TestPhysicalDefaultIface`（TUN 劫持下认出残留物理默认路由、跳过虚拟网关路由、仅虚拟默认返回 None、命令失败 4 用例）。
  - 验证：本机复现环境（wlp1s0=192.168.3.41 + Meta=198.18.0.1）下 `detect_lan_ip()` 返回 192.168.3.41，`_physical_default_iface()` 正确认出 wlp1s0；`pytest donkeycar/tests/test_provisioning.py` 92 项全部通过。另经多视角对抗评审（correctness/test-quality/compat 三视角 + 逐条反驳验证）确认并修复了全隧道 VPN 绕过、网桥命名缺口、优先级未被测试锁定等残余问题。


## 2026-08-04

- feat(web_ui): 驾驶页模式选择器按 ESP32 Drifter Console 模式卡片配色，一种颜色代表一种模式（手动=绿 `#39d98a`、半自动=琥珀 `#ffcc66`、全自动=蓝 `#5cc8ff`）
  - `web_ui/frontend/src/components/drive/DriveModeSelector.tsx`：`MODE_OPTIONS` 为每个模式增加 `activeClass`（默认皮肤为对应模式色的 20% 底 + 同色文字，替代原先三模式统一的 cyan 激活态）；按钮新增 `data-mode` 属性与激活时的 `mode-active` 标记类，供主题精确定位每个分段。
  - `web_ui/frontend/src/themes/theme-mus4.css`：原先把所有激活分段统一覆盖为蓝色实心填充的规则，改为按 `button.mode-active[data-mode=...]` 分别填充绿/琥珀/蓝 + 黑色加粗标签（沿用 Drifter Console `.netTabs.active` 的选中态语言），hover 色分别为 `#74e4ad` / `#ffdb94` / `#8bdcff`；配色与既有固件模式徽标 `data-rc-mode` 规则一致。
  - 测试：新增 `web_ui/frontend/src/components/drive/DriveModeSelector.test.tsx` 4 个用例（渲染/点击回调/三模式激活色类/disabled），`npm run check`（tsc）与 vitest 全部通过。


## 2026-08-03

- fix(ci): 修复后端契约测试在 FastAPI 0.141 下的两处失败（`test_main_registers_arena_router`、`test_main_registers_connector_router`，macOS + Ubuntu 双红）
  - 根因：`web_ui/backend/requirements.txt` 未锁定版本，CI 当日拉到 fastapi 0.141.1；该版本 `include_router` 改为惰性挂载，`app.routes` 中存私有 `_IncludedRouter` 条目（无 `.path` 属性）而非展平后的路由，按 `{route.path for route in main.app.routes}` 遍历路由表的两处契约测试抛 `AttributeError`（2 failed / 68 passed）。本地环境仍为 fastapi 0.136.3 旧行为，故本地全绿、CI 独红。
  - 修复：新增 `web_ui/backend/tests/conftest.py::collect_route_paths()`，鸭子类型兼容两代 FastAPI——路由条目有 `.path` 直接收集；无 `.path` 但有 `original_router`（0.141+ 惰性挂载）则携带 `include_context.prefix` 递归展开嵌套路由。两处测试改用该辅助函数，不断言 FastAPI 内部结构。
  - 验证：venv 复现 CI 依赖（fastapi 0.141.1 + starlette 1.3.1）——未修复时两测试复现 CI 同款 `AttributeError`，修复后 70 passed；本地 fastapi 0.136.3 下亦 70 passed。


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
