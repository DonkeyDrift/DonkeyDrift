# 变更日志

## 2026-08-15 (1)

- feat(launcher,web_ui): 实现"打开 Kimi Code Web"（issue #103/#104；配套 Firmware 侧 #59，固件 v1.7.74）
  - `donkeycar/launcher/kimi_web.py`（新增）：自动化核心——复用 `terminal.TerminalSession` 建独立 PTY bash 会话（writer 换成本模块的 `_BufferWriter` 缓冲输出，不动现有 WebSocket 桥），注入 `kimi` → TUI 就绪判定（alternate-screen 进入序列 `\x1b[?1049h` + 输出静默 2s，上限 60s）→ 注入 `/web` → 从注入点之后的输出剥 ANSI 捕获 URL（`Session:` 深链优先，`Local:`/`URL:`/`Network:` 次之，任意 http(s) 兜底）；`command not found`/`Trust this folder`/`No active session`/内嵌 server 失败均有专门报错；整体超时 120s；成功时会话保持存活（kimi web server 挂在该 PTY 前台），失败一律 close 不留孤儿。
  - `donkeycar/launcher/server.py`：新增 `POST /api/launch/kimi-code-web`——请求体可选 JSON `{"cwd": "/abs/path"}`（缺省上位机主目录；目录不存在直接报错，绝不回退）；成功 `200 {"status":"ok","url"}`、失败非 200 `{"status":"error","error"}`；**所有响应带 `Access-Control-Allow-Origin: *`**（DC 页面由 ESP32 提供服务，浏览器跨域 fetch :8090 依赖此头，仅此端点放行）；`_serve_json` 新增 `extra_headers` 参数承载。
  - D 页面（MENU_HTML）新增 **11 号菜单项"打开 Kimi Code Web"**（#104）：点击/数字键（先 1 再 1 二段输入）触发 `launchKimiCodeWeb()`，POST 固定带 `{"cwd":"/home/dkc/projects"}`（issue 要求先进入 projects 主文件夹），等待期间 overlay 显示"正在启动 Kimi Code Web（kimi 启动较慢，请耐心等待）..."，拿到 URL 后**当前标签页**跳转（区别于 #103 的新标签页）；help 文案数字键范围 0-10 改为 0-11。
  - `web_ui/backend/routers/launch.py`（新增）：`POST /api/launch/kimi-code-web` 转发路由——DD 前端与后端同源，相对路径到达本后端后原样转发到 launcher `http://localhost:8090`（125s 超时；连接失败回 502 中文错误；launcher 的业务错误 JSON 原样透传），`main.py` 挂载 `/api/launch` 前缀。
  - DD 前端（#103）：`services/api.ts` 新增 `launchKimiCodeWeb(signal)`（`validateStatus` 全放行，业务错误交给调用方按 status 判断）；`EnterButtons.tsx` 的 kimi 按钮接功能——防重复点击、点击同步上下文先 `window.open('about:blank','_blank')` 拿句柄规避弹窗拦截、`AbortController` 125s 超时、成功 `win.location.href=url`、失败关句柄并 alert；`i18n/messages/common.ts` 补 zh/en 词条（title/启动中…/失败/网络错误）。
  - 测试同步：`tests/test_launcher_kimi_web.py`（新增）19 项——strip_ansi/extract_web_url 纯函数、`_FakeSession` 脚本化 PTY（成功保活/cwd 透传/cwd 非法不建会话/command not found/Trust folder/No active session/超时回收/默认 session_factory）、内存 HTTP 服务器端点路由与 CORS 断言；`EnterButtons.test.tsx` 占位断言改为行为断言（成功填入预开标签页、失败关页+alert），共 7 例。全量回归：pytest 71 项、vitest 78 项通过。
  - 涉及文件：`donkeycar/launcher/kimi_web.py`、`donkeycar/launcher/server.py`、`web_ui/backend/routers/launch.py`、`web_ui/backend/main.py`、`web_ui/frontend/src/services/api.ts`、`web_ui/frontend/src/components/EnterButtons.tsx`、`web_ui/frontend/src/components/EnterButtons.test.tsx`、`web_ui/frontend/src/i18n/messages/common.ts`、`tests/test_launcher_kimi_web.py`

## 2026-08-14 (21)

- docs(readme): 重写仓库根 README
  - `README.md` 整体重写：补充平台定位（本仓库与 Firmware 仓库的 MUS4 ESP32 固件配套，构成完整漂移车平台）。
  - 新增 Features 一节：模板、数据训练、模拟器、Web UI、Launcher、MUS4 集成。
  - 新增 Repository Layout 一节，说明仓库目录结构。
  - Quick Start 注明要求 Python 3.11。
  - 仓库链接修正为 `github.com/DonkeyDrift/DonkeyDrift`。
  - 新增 Related Repositories 一节，指向 Firmware 仓库。
  - 保留原有 fork 声明、Donkeycar 兼容性说明与 License/致谢结构。
  - 测试同步：纯文档改动，无代码与测试变更，未运行测试。
  - 涉及文件：`README.md`

## 2026-08-14 (20)

- feat(launcher): 新增 `/terminal` 上位机 Web 终端——浏览器里得到上位机完整 bash 终端
  - 背景：Drifter Console 的 cmdTarget 下拉框此前只有 Web 一项（Serial 日志源在固件 v1.7.29 后与 Web 同源重复被去掉）。本改动把 Serial 选项恢复并升级为真正的上位机终端：固件侧选中 Serial 时以 iframe 嵌入 `http://<host_ip>:8090/terminal`，可在浏览器里直接使用上位机 bash（kimi/claude/codex/donkey 等全屏 TUI 程序可用）。
  - `donkeycar/launcher/terminal.py`（新增）：WebSocket↔PTY 桥——每个 ws 连接 fork 一个 PTY 跑 login shell，双向转发 stdin/stdout，支持浏览器端窗口缩放（resize 消息同步 TIOCSWINSZ）、连接关闭时回收子进程、shell 退出时主动通知前端。
  - `donkeycar/launcher/terminal_static/`（新增）：xterm.js 自包含终端页（`index.html` + 本地 vendored `xterm.js`/`xterm.css`/`addon-fit.js`，无 CDN 依赖，车内无互联网可用）。
  - `donkeycar/launcher/server.py`：新增 `/terminal` 终端页路由、`/terminal/static/*` 静态资源与 `/terminal/ws` WebSocket 端点。
  - 安全口径（用户已决策）：与固件控制台免密（Firmware v1.7.71）同口径——家用局域网场景不加认证，谁连上谁可用；后续如需暴露到非信任网络再补鉴权。
  - 测试同步：`donkeycar/tests/test_launcher_terminal.py`（新增）14 项——PTY 桥回显/resize/退出通知、路由与静态资源、server 集成。launcher + provisioning 全量 120 项通过。
  - 验证：systemd --user 重启部署后实测 `ws://192.168.3.41:8090/terminal/ws` 命令回显/窗口缩放/Ctrl-C/shell 退出通知全通；Playwright 无头浏览器对车上真实页面 E2E 九项全过（默认选中 Serial、选项顺序 serial→web、终端 iframe 自动加载并挂载 xterm、键入命令真实执行回显、切换 Web 恢复日志视图、localStorage 记住选择且刷新后恢复）。
  - 配套固件改动在 Firmware 仓库（PR #56，v1.7.72）：cmdTarget 恢复 Serial 选项（第一位、默认、记忆），选中后日志区切换为该终端 iframe。
  - 涉及文件：`donkeycar/launcher/terminal.py`、`donkeycar/launcher/terminal_static/`（index.html/xterm.js/xterm.css/addon-fit.js）、`donkeycar/launcher/server.py`、`donkeycar/tests/test_launcher_terminal.py`

## 2026-08-14 (19)

- feat(web_ui): DonkeyDrifter 手机版标题区三行布局——版本号常驻可见，进入按钮/主题/语言移入标题区
  - 背景：手机版（<lg）此前把版本号、进入按钮、主题/语言切换全部收进汉堡菜单，不展开菜单就看不到版本号。
  - `Layout.tsx`：手机版标题区改为三行——第一行 logo+标题、GitHub 图标紧跟标题右侧、版本号在 GitHub 右边（菜单收起也常驻），右端仅汉堡按钮；第二行进入按钮（DrifterConsole 在左；与当日 (18) 合并后 Donkey 键已删除，右侧为"打开 Kimi Code Web"占位键）；第三行左边浅色/跟随系统/深色切换、右边中文/English 切换。汉堡菜单展开后仅保留 5 个导航项（版本号/按钮/切换全部移出）。桌面版（≥lg）布局与按钮顺序零改动。
  - `EnterButtons.tsx`：新增 `consoleFirst` 属性，仅手机版标题区使用；桌面端默认顺序不变。（与当日 (18) 合并后 `consoleFirst` 语义以 (18) 为准：交换 kimi/console）
  - `SidePanel.tsx`：左侧 Loaders/Connectors 抽屉为 fixed 定位、顶部偏移原写死 top-16（64px，对应单行顶栏），三行标题区（实测 135px）把抽屉顶部约 70px 压进 sticky 顶栏下方被遮挡；改为手机版 `top-[143px]`（135px+8px 间距）、高度 `calc(100vh-143px)`，≥lg 保持 top-16 不变。
  - 测试同步：`EnterButtons.test.tsx` 补 2 项顺序断言，该文件共 6 项通过（与当日 (18) 合并后以 Tony 侧重写版 6 例为准）。
  - 验证：`tsc -b --noEmit` 零错误；vitest 全量 77/77 通过；Playwright 390px 手机视口（菜单开/关）与 1400px 桌面视口截图确认——手机版符合目标布局、桌面版零变化、抽屉下移后 Loaders 不再被遮挡。
  - 涉及文件：`web_ui/frontend/src/components/Layout.tsx`、`web_ui/frontend/src/components/EnterButtons.tsx`、`web_ui/frontend/src/components/EnterButtons.test.tsx`、`web_ui/frontend/src/components/SidePanel.tsx`

- fix(web_ui): 恢复被 main 合线（3a57408f）回退的主题回退逻辑
  - 根因：6b7e39bf（主题默认改回跟随系统）的三处改动在 main 合回 Tony 的 merge（3a57408f）中被旧版本覆盖回退——`theme.ts` `readStoredTheme()` catch 分支（localStorage 异常时）变回 `return 'dark'`、`ThemeSwitcher.test.tsx` 两处断言（默认态用例标题、非法存储值回退"深色"）。实现与测试互相矛盾，导致 `falls back to 深色 for unknown stored values` 在 Tony 上持续红（76/77）。
  - 修复：恢复 6b7e39bf 语义——catch 回退 `'system'`、非法存储值断言改回"跟随系统"、默认态用例标题改回"跟随系统 active by default"。`index.html` 首屏脚本与 launcher `server.py` 三处默认值未被回退，无需改动。
  - 验证：vitest 全量 77/77 通过。
  - 涉及文件：`web_ui/frontend/src/lib/theme.ts`、`web_ui/frontend/src/components/ThemeSwitcher.test.tsx`

## 2026-08-14 (18)

- feat(web_ui): 头部入口按钮——删除"打开 Donkey"，新增"打开 Kimi Code Web"占位键，"进入"改名"打开"
  - EnterButtons 组件移除 Donkey 按钮及 enterDonkey 跳转逻辑，i18n 删除 `common.enterButtons.donkey` / `donkeyTitle` 键。
  - 新增"打开 Kimi Code Web"占位按钮（功能预留，无 onClick/跳转）：桌面版头部排在"打开 DrifterConsole"左侧；手机版汉堡菜单内（`<EnterButtons consoleFirst />`）排在其右侧——`consoleFirst` 语义由交换 donkey/console 改为交换 kimi/console。
  - 按钮文案"进入 DrifterConsole"→"打开 DrifterConsole"（zh），"Enter DrifterConsole"→"Open DrifterConsole"（en），其余词条不变。
  - 测试：`EnterButtons.test.tsx` 重写为 6 例（双键渲染、桌面默认顺序、手机 consoleFirst 顺序、Kimi 占位点击无动作、DC 扫描成功新开标签、扫描失败 alert），vitest 6/6 通过；全量 77 例中唯一失败的 ThemeSwitcher 用例为 Tony 基线被 main 合线回退的既有问题（另一会话修复中），与本次无关。
  - 涉及文件：`web_ui/frontend/src/components/EnterButtons.tsx`、`web_ui/frontend/src/components/Layout.tsx`、`web_ui/frontend/src/i18n/messages/common.ts`、`web_ui/frontend/src/components/EnterButtons.test.tsx`

## 2026-08-14 (17)

- feat(launcher): Donkey 菜单页手机版顶栏两行布局 + 英文版菜单标题对齐修复
  - 手机版（≤640px）顶栏改为两行：第一行与电脑版完全一致（logo 图标 → Donkey 标题 → GitHub 图标 → 版本号），第二行最左为浅色/跟随系统/深色切换键、最右为中文/English 切换键；实现为新增仅手机端显示的 `.headerBreak` 换行元素 + `@media (max-width:640px)` 内 `#themeTabs{margin-left:0}` / `#langTabs{margin-left:auto}`，桌面端布局零改动。
  - 英文版菜单 0/1 号标题（Drifter Console / Create Car）错位修复：根源是英文分类标签 Manage/Data/Drive/Filter/Train 宽度不一，中文版二字标签天然等宽无此问题；新增 `html[lang="en"] .catPill{width:70px;justify-content:center}` 仅对英文版固定分类 pill 等宽，中文版像素级不变，电脑版与手机版同效。
  - 验证：`py_compile` 通过；8091 临时实例 + Playwright 实测——英文版 0/1/2 号标题 x 坐标均为 162（修复前错位），中文版保持 137.1 不变；手机端 390px 下主题键 x=12（最左）、语言键 x=270（贴右边框）；桌面端顶栏仍为单行。中英文 × 桌面/手机四种组合截图确认。
  - 涉及文件：`donkeycar/launcher/server.py`

## 2026-08-14 (16)

- fix(launcher): systemd 单元改 `KillMode=process`，launcher 重启不再连坐杀死 drive 进程
  - 根因：`donkeydrifter-launcher.service` 此前用默认 `KillMode=control-group`，每次停止/重启 launcher（部署新代码、手工 restart）都会按 cgroup 整体回收，把经 launcher 启动的 `donkey web`（后端 8100 + 前端 5188）与 `manage.py drive` 一并杀掉，正在使用的 DonkeyDrifter 驾驶界面随即掉线且不会自动恢复（launcher 无重启后自动重拉 drive 的逻辑）；且 `manage.py drive` 的 WS 重连循环会拖住 SIGTERM，导致 stop 触发 90s 超时报 `Failed with result 'timeout'`。今日 17:05/17:29/17:47 三次重启均复现"进不去 DonkeyDrifter"。
  - 修复：`donkeycar/launcher/donkeydrifter-launcher.service` 新增 `KillMode=process`——停止/重启只向 launcher 主进程发信号，drive 子进程继续存活；下次 `POST /api/launch/drive` 仍按 `~/.donkeycar/drive.pid` 先杀旧进程再启动，不累积孤儿。顺带消除 stop 超时（不再等子进程退出）。
  - 已同步本机已安装单元 `~/.config/systemd/user/donkeydrifter-launcher.service` 并 `systemctl --user daemon-reload`（无需重启服务，下次 stop/restart 即生效）；实机验证：daemon-reload 后 `systemctl --user restart`，8090 数秒内恢复，`manage.py drive`（8100）与 vite（5188）进程全程存活、页面持续 200。
  - 测试：新增 `tests/test_launcher_service_unit.py`（断言 `KillMode=process`、保留 `Restart=always`、无 `control-group` 回退、unit 基本形态不变）。
  - 涉及文件：`donkeycar/launcher/donkeydrifter-launcher.service`、`tests/test_launcher_service_unit.py`（新增）

## 2026-08-14 (15)

- feat(web_ui): UI 语言首访自动跟随浏览器语言
  - `web_ui/frontend/src/i18n/index.tsx` 初始化顺序改为：localStorage 已存选择优先，无存则读取 `navigator.language`——`zh` 开头（zh-CN/zh-TW 等）用中文，其余一律英文；自动检测结果不落盘，仅用户手动切换时写入 localStorage `donkeydrifter.ui.lang` 并在后续访问优先生效（关机/重启后仍记住手动选择）。
  - 测试同步：`LanguageSwitcher.test.tsx` 扩为 5 项（中文浏览器默认中文、英文浏览器首访自动英文且不落盘、点击切换并持久化、恢复已存选择、已存选择优先于浏览器语言），新增 `setBrowserLanguage` mock 辅助；`FabActions.test.tsx` 默认中文用例补浏览器语言 mock 保持确定性。
  - 验证：`tsc -b --noEmit` 零错误、`vitest` 14 个文件 75/75 通过、`npm run build` 成功。
  - 涉及文件：`web_ui/frontend/src/i18n/index.tsx`、`web_ui/frontend/src/components/LanguageSwitcher.test.tsx`、`web_ui/frontend/src/components/FabActions.test.tsx`

## 2026-08-14 (14)

- fix(launcher,provisioning): 修复 Drifter Console 上看不到上位机 IP
  - 根因①：launcher 常驻 HOSTIP 上报（`server.py` `_report_hostip_to_esp32`，30s 周期）候选端口仅 `/dev/ttyACM0/1`、`/dev/ttyUSB0`，不覆盖本车 ESP32 配网串口 `/dev/ttyS6`（UART 直连），一个都不命中等于从没发过；且裸 `open()` 不配置 termios，按端口残留波特率（默认 9600）发送，固件 115200 收到全乱码。
  - 根因②：ModemManager 会探测 `ID_MM_CANDIDATE=1` 的串口并篡改 termios（实测车上 `/dev/ttyS6` 在 `manage.py` 持有期间被从 115200 改成 9600），`ProvisioningPart` 只在打开时配置一次，被篡改后持续乱码，HOSTIP 帧固件无法解析。
  - 修复：`server.py` 候选端口补 `/dev/ttyS6` 置顶；改为每次发送前 open → tcsetattr 115200 8N1（CLOCAL|CREAD、关 ONLCR 输出翻译）→ write → tcdrain → close，被篡改下一周期自愈；IP 探测由 `hostname -I` 简易解析换用 `provisioning.detect_lan_ip()`（VPN/TUN 感知，与配网模块同一逻辑）。`provisioning.py` `_write_line()` 独立串口模式发送前重新断言波特率（Arduino 共享串口不动，由 actuator 管理）。
  - 测试：新增 `donkeycar/tests/test_launcher_hostip.py` 11 例（端口优先级与回退、115200/8N1 标志位断言、无 IP 不触碰串口、端口全灭静默、写失败换口、无 termios 平台回退）；`test_provisioning.py` 补 2 例（独立模式重设波特率、Arduino 共享模式不动波特率）。
  - 验证：本地 pytest 相关 106 项通过；实机调用修复版上报后 ESP32 `/api/status` 出现 `host_ip=192.168.3.41`（本机 IP）；分支 CI 全绿。
  - 涉及文件：`donkeycar/launcher/server.py`、`donkeycar/parts/provisioning.py`、`donkeycar/tests/test_launcher_hostip.py`（新增）、`donkeycar/tests/test_provisioning.py`

- test(tui): 同步菜单名大写排版改动，修复 Tony CI 红
  - #88 把菜单功能名改为首字母大写（"drive"→"Drive"）后漏改 `test_main_menu_sixth_item_is_drive_page` 期望，Tony 主干 CI 持续红；期望值修正为 "Drive"。
  - 涉及文件：`donkeycar/tests/test_tui_menu.py`

## 2026-08-14 (13)

- feat(web_ui,launcher): 三端主题默认由深色改回"跟随系统"（DonkeyDrifter web_ui + Donkey launcher；Drifter Console 见 Firmware v1.7.67 / Firmware#49）
  - `web_ui/frontend/src/lib/theme.ts`：`readStoredTheme()` 无存储或存储值非法时回退由 `'dark'` 改回 `'system'`（跟随系统）；用户显式点选浅色/深色后仍以存储值为准。
  - `web_ui/frontend/index.html`：首屏防闪烁脚本默认改为 `'system'`，经 `matchMedia('(prefers-color-scheme: dark)')` 解析，matchMedia 不可用时回退深色。
  - `donkeycar/launcher/server.py`：三处默认值同步——首屏内联脚本（无存储/非法值一律 matchMedia 解析）、`let uiTheme = 'system'`、`initTheme()` 兜底 `stored = 'system'`。
  - `web_ui/frontend/src/components/ThemeSwitcher.test.tsx`：默认态断言同步翻转（默认激活"跟随系统"、默认跟随系统主题变化、非法存储值回退"跟随系统"）。
  - 验证：vitest 全量 73 项通过；Playwright 实测全新浏览器（无任何存储）系统浅色 → `theme-light`、系统深色 → `theme-mus4`，切换键激活态为"跟随系统"。

## 2026-08-14 (12)

- feat(launcher): 菜单页与启动中转页语言跟随浏览器自动检测
  - `donkeycar/launcher/server.py` 菜单页（MENU_HTML）：新增 `detectBrowserLanguage()`（`navigator.language` 小写后以 `zh` 开头→中文，其余一律→英文，异常兜底中文）；`readStoredLanguage()` 改为 localStorage `donkeydrifter.ui.lang` 显式选择优先、无存储时回退浏览器检测（原先无存储时硬编码中文）。用户手动切换仍写 localStorage 持久化、跨重启优先于自动检测——与 DD web_ui（Tony-webui-lang-autodetect 在制）和 DC 固件 v1.7.66 同一语义。
  - 启动中转页 `LAUNCH_DRIVE_HTML` 补自包含中英 i18n：经同一 localStorage 键读取显式选择、无存储跟随浏览器；「正在启动/启动失败/未知错误/网络错误」四条文案双语化并全部经 `t()` 渲染，`<html lang>` 动态设置。
  - 测试同步：新增 `tests/test_launcher_language_autodetect.py` 2 项（菜单页检测接线与回退语义、中转页双语字典对齐及 `t()` 全覆盖、无残留硬编码中文）。
  - 验证：新增 2 项 pytest 通过；临时实例（127.0.0.1:18090）实测 `/` 与 `/launch/drive` 均正确下发新代码；两页全部 `<script>` 块经 `node --check` 语法校验通过。
  - 涉及文件：`donkeycar/launcher/server.py`、`tests/test_launcher_language_autodetect.py`

## 2026-08-14 (11)

- feat(web_ui): 手机版/竖屏平板响应式适配（<1024px 与手机一致）
  - 根因修复：`index.html` viewport 由写死 `width=520` 改为 `width=device-width`；`index.css` 删除 `html,body,#root` 的 `min-width: 520px`（此前手机一律按 520px 排版再整体缩小，"显示不全"即由此而来）。
  - 页头（`Layout.tsx`）：<lg 改为汉堡菜单——logo+标题常驻，右侧仅保留 GitHub 图标与汉堡按钮；菜单面板内含 5 个导航项、"进入 Donkey"/"进入 DrifterConsole"按钮、主题/语言切换、版本徽章，路由切换自动收起。≥lg 桌面布局不变（与旧版构建同宽度截图逐像素比对一致）。新增 i18n 词条 `common.nav.menu`（中「菜单」/英 "Menu"）。
  - Drive 页：顶部工具栏（输入源/模式/模型/录制/计数）改 `flex-wrap` 允许换行。
  - SidePanel 抽屉：打开宽度由固定 `w-96` 改为 `min(24rem, 100vw-3.5rem)`，窄屏下触发按钮不再被推出屏外。
  - 网格与小布局：Trainer 标题行补 `flex-wrap`；LocalConfigForm/RemoteConfigForm/CarConnectorPage 共 5 处无前缀 `grid-cols-2` 改 `grid-cols-1 lg:grid-cols-2`；CarConnectorPage 任务日志长行补 `break-all`；PilotArena 当前数据卡片 `md:grid-cols-3`→`lg:` 并补 `min-w-0 break-all` 防长路径撑破；TubNavigator 图像区 `md:`→`lg:`、首尾帧按钮组 `grid-cols-4`→`grid-cols-2 lg:grid-cols-4`；TubEditor 工具条补 `flex-wrap`。
  - 验证：vitest 全量 73 项通过；`npm run build`（tsc+vite）通过；Playwright 实测 390×844（手机）/768×1024（竖屏平板）/1280×800（桌面）× 5 个路由共 15 组全部零横向溢出；dist 已部署 8100 供手机浏览器实测。
  - 涉及文件：`web_ui/frontend/index.html`、`web_ui/frontend/src/index.css`、`web_ui/frontend/src/components/Layout.tsx`、`web_ui/frontend/src/components/SidePanel.tsx`、`web_ui/frontend/src/components/TubEditor.tsx`、`web_ui/frontend/src/components/TubNavigator.tsx`、`web_ui/frontend/src/components/trainer/LocalConfigForm.tsx`、`web_ui/frontend/src/components/trainer/RemoteConfigForm.tsx`、`web_ui/frontend/src/i18n/messages/common.ts`、`web_ui/frontend/src/pages/CarConnectorPage.tsx`、`web_ui/frontend/src/pages/DrivePage.tsx`、`web_ui/frontend/src/pages/PilotArenaPage.tsx`、`web_ui/frontend/src/pages/TrainerPage.tsx`

## 2026-08-14 (10)

- feat(launcher): 菜单新增「Drifter Console」项（0 号置顶、常用），一键打开车上控制台
  - 新增 `donkeycar/launcher/dc_discovery.py`：Drifter Console 局域网发现模块。固件 v1.7.14 起默认禁用 mDNS/NetBIOS/LLMNR 名称发现（`DISABLE_WIFI_NAME_DISCOVERY`），无法依赖主机名，改为探测 `/api/status` 的 MUS4 特征字段（`version=`/`ap_ip=`）定位车辆：先探车辆 AP 固定地址 192.168.4.1，未命中再并行扫描本机所在 /24 网段（48 线程、单地址 0.6s 超时），结果缓存 60 秒。
  - `server.py` 新增 `POST /api/launch/dc` 返回 DC URL；menuItems 将 Drifter Console 编号 0 置顶（其余项编号不变）；键盘 0 由「返回上一页/关闭标签页」改为选中 0 号，删除 history.back()/window.close() 分支；帮助按键说明更新为数字键 0-10（中英 + HTML 兜底同步）。
  - `tui.py`「驾驶」分类新增 DrifterConsoleCommand（is_favorite=True，无需 mycar 目录），经同一发现模块定位后用默认浏览器打开；TUI 菜单编号不变（0 在 TUI 仍为退出）。
  - 验证：`POST /api/launch/dc` 实测 1.8s 返回 `http://192.168.3.46/`（`/api/status` 确认为车上 MUS4 v1.7.66）；Playwright 实测点击 0 号/按 0 键跳转 DC、按 1,0 选中 10 号；截图确认 0 号置顶排版。
  - 涉及文件：`donkeycar/launcher/dc_discovery.py`（新增）、`donkeycar/launcher/server.py`、`donkeycar/management/tui.py`

- feat(launcher): 菜单功能名排版改为首字母大写、空格分词
  - 规则：每个单词首字母大写，单词间用空格连接不再用下划线；"UI" 两字母全大写。11 项依次为 Create Car / Open / Clear Data / Backup Data / Restore Data / Drive / Drifter Console / Web / Donkey UI / Train Local / Train Online；网页菜单与 TUI 命令显示名同步修改。
  - 注：TUI 参数历史以功能名为键，改名后对应功能的历史参数会重置一次。
  - 验证：临时实例 + Playwright 截图实测 11 项名称渲染正确；TUI 菜单列表逐项核对一致。
  - 涉及文件：`donkeycar/launcher/server.py`、`donkeycar/management/tui.py`

## 2026-08-14 (9)

- feat(launcher): CWD 栏标签改为双语全称，不再用缩写
  - 中文由 "CWD" 改为「当前工作目录」，英文改为 "Current Working Directory"（i18n 词条 `cwd.label`）。
  - 验证：本机测试实例 + Playwright 截图实测中/英文显示正确。
  - 涉及文件：`donkeycar/launcher/server.py`

- feat(launcher): 删除页头 "DonkeyDrifter Web Launcher" 文字
  - 页头仅保留 logo + Donkey 标题 + GitHub 图标 + 版本徽章，右侧副标题文字及其 i18n 词条移除。
  - 验证：本机测试实例 + Playwright 截图实测页头渲染正常。
  - 涉及文件：`donkeycar/launcher/server.py`

- feat(launcher): 调整菜单常用项标记：去掉 createcar/clear_data，新增 donkey_ui/train_local
  - 网页菜单（`launcher/server.py` menuItems）：1 号 createcar、3 号 clear_data 的 favorite 改为 false；8 号 donkey_ui、9 号 train_local 改为 true；现常用项为 6/7/8/9/10（drive、web、donkey_ui、train_local、train_online）。
  - 终端 TUI（`management/tui.py`）对应 Command 的 is_favorite 同步修改，与网页菜单保持一致。
  - 验证：本机临时实例（8091）+ Playwright 截图实测菜单徽标渲染正确；8090 重启后抽查页面内容一致。
  - 涉及文件：`donkeycar/launcher/server.py`、`donkeycar/management/tui.py`

- feat(launcher): 精简帮助弹窗内容
  - 键盘操作分区删除「?：显示此帮助信息」「0：返回上一页」「ESC：关闭弹窗」三条（仅删帮助文案，键盘实际功能未动）。
  - 删除「说明」分区及其唯一一条「目前仅支持通过浏览器启动「驾驶」功能（选项 6）」；中英文 i18n 词条同步移除。
  - 帮助弹窗现仅保留「键盘操作」分区下数字键 1-10 选菜单一条。
  - 验证：本机临时实例 + Playwright 截图实测帮助弹窗渲染正确；8090 重启后线上页面无残留词条。
  - 涉及文件：`donkeycar/launcher/server.py`

## 2026-08-14 (8)

- feat(web_ui,launcher): 主题默认改为深色，"跟随系统"仅在用户显式点选后生效
  - 按用户要求调整默认：此前 DD web_ui / D launcher 无持久化选择时默认"跟随系统"（首屏即按系统偏好渲染）；现默认深色，matchMedia 系统主题解析与变化监听仅在用户点选"跟随系统"后才生效。DC（Drifter Console，Firmware 仓库）同款修改在同名分支 `Tony-theme-default-dark` 另行进行。
  - DD（web_ui）：`src/lib/theme.ts` `readStoredTheme()` 无存储或存储值非法时由回退 `'system'` 改为回退 `'dark'`（`'system'` 仍是合法持久化值）；`index.html` 首屏防闪烁内联脚本同步——无有效存储值直接取深色，仅存储值为 `'system'` 时才经 matchMedia 解析。
  - D（launcher）：`donkeycar/launcher/server.py` 三处默认由 `'system'` 改为 `'dark'`——首屏防闪烁内联脚本、`let uiTheme` 初值、`initTheme()` 的 stored 兜底值；两处注释同步更新。
  - 测试：`web_ui/frontend/src/components/ThemeSwitcher.test.tsx` 默认激活分段断言由"跟随系统"改为"深色"并补"默认挂载即应用 `theme-mus4` 皮肤"断言，未知存储值回退断言同步改为"深色"，新增"默认状态下系统主题变化不生效"用例；vitest 全量 73 项通过，`server.py` 通过 py_compile。
  - 涉及文件：`web_ui/frontend/src/lib/theme.ts`、`web_ui/frontend/index.html`、`web_ui/frontend/src/components/ThemeSwitcher.test.tsx`、`donkeycar/launcher/server.py`

## 2026-08-14 (7)

- feat(web_ui): 页头 "DonkeyDrifter" 标题左侧新增 logo 图标
  - 图标文件取自主目录 `logo.png`（经 MD5 比对与 Donkey 启动页 8090 的 `/favicon.png` 为同一文件），新增为 `web_ui/frontend/public/logo.png`，构建后随 dist 以 `/logo.png` 提供。
  - 样式对齐 Donkey 启动页 headerLogo：32×32（`w-8 h-8`）、`rounded-lg`(8px)、1px `#2b3441` 边框、与标题间距 12px（`gap-3`）、flex 垂直居中；页头高度与导航布局不变。
  - 验证：Playwright 实测 8100 实页深/浅双主题页头截图，图标显示与参考样式一致；`/logo.png` HTTP 200；`npm run build` 与 `vitest`（14 文件 72 用例）全部通过。
  - 涉及文件：`web_ui/frontend/src/components/Layout.tsx`、`web_ui/frontend/public/logo.png`（新增）

## 2026-08-14 (6)

- fix(web_ui): 控制参数滑块 thumb 加宽对齐最初 Safari 原生尺寸（24×16px 纯白椭圆）
  - 用户反馈 14×12px 版本比"最初"小、比例不对：最初版本（d3349014）未自定义 thumb，其尺寸由浏览器原生渲染决定。本机实测 Firefox 153 原生为 ~16px 圆形、Linux WebKit(WPE) 为 18px 圆形，均与用户描述的"宽大于高的白色椭圆"不符；最终查 WebKit 源码 `RenderThemeCocoa.mm` 确认 Safari 原生 thumb 硬编码尺寸为 `kDefaultSliderThumbWidth=24` / `kDefaultSliderThumbHeight=16`，即 24×16px 白色椭圆，与用户描述的最初样式一致（高度 16≈15.4 被认可、宽度 24>18 补齐差距）。
  - thumb 由 14×12px 改为 `w-[24px] h-[16px]`（纯白不透明 rounded-full 椭圆形状不变），居中 margin 按公式 (轨道 6px − thumb 16px)/2 更新为 `-mt-[5px]`；轨道样式（6px 锌色）未动。
  - 验证：Playwright Chromium + WebKit 双引擎实测 8100 实页（深/浅双主题），thumb 精确渲染 24.00×16.00、纯白 (255,255,255) 不透明、与轨道垂直居中偏差 0.00px、轨道 6.00px 未变；`npm run build` 与 `vitest`（14 文件 72 用例）全部通过。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-14 (5)

- feat(launcher): 常用项标注由 `[*]` 改为「常用」，删除帮助面板星号说明行
  - 菜单常用项徽标文字由 `[*]` 改为「常用」（英文「Common」），紫色徽标样式不变，经 i18n 词条 `menu.favorite` 随语言切换。
  - 帮助面板「说明」分组删除"带 [*] 标记的为常用功能"一行（中英文词条同步移除）。
  - 验证：本机测试实例 + Playwright 截图实测中/英文菜单徽标与帮助面板，无 JS 报错。
  - 涉及文件：`donkeycar/launcher/server.py`

## 2026-08-14 (4)

- feat(launcher): Donkey 菜单页接入 Drifter Console 全套控件、浅色主题与页头徽章
  - 右下角帮助小点：逐字复刻 DC 的 FAB 簇——18px 发光小点点击展开 🌐 语言球（向上）与 ? 帮助球（向左），帮助面板锚定右下角（× 关闭、点遮罩关闭），保留 ESC/? 键盘交互；原居中帮助弹窗移除。
  - 顶栏右侧新增 DC langTabs 胶囊分段控件：浅色/跟随系统/深色 三态主题 + 中文/English 语言切换。
  - 浅色主题整套配色对齐 DC/DD 浅色版（背景 `#eef1f5`、白渐变卡片、强调色 `#0c9bd6`、语义色浅色变体 绿 `#1fae6b`/琥珀 `#b57d0e`/红 `#e5484d`/紫 `#b14ae0`）；主题落 `<html data-theme>`，localStorage key `donkeydrifter.ui.theme`，"跟随系统"经 matchMedia 实时解析并监听；head 内联脚本防首屏闪烁。
  - i18n 走 `data-i18n` 属性扫描（textContent/aria-label/title），菜单项、分类 pill、帮助面板、启动遮罩文案全部双语；localStorage key `donkeydrifter.ui.lang`。
  - 页头 "DonkeyDrifter Web Launcher" 右侧新增 GitHub 图标（SVG 与 DD `GitHubLink.tsx` 逐字一致，新标签页打开 DonkeyDrift 仓库）与版本徽章（DD VersionBadge 样式，版本源与 DD 后端 `/api/config/version` 同为 `donkeycar._version.__version__`）；删除底部"输入编号选择功能，?帮助，0退出"提示行及其 CSS/i18n 词条。
  - 验证：本机测试实例 + Playwright 8 场景截图（深/浅 × 中/英、FAB 展开、帮助面板、语言菜单、跟随系统+浅色系统偏好）全部正确，页面无 JS 报错。
  - 涉及文件：`donkeycar/launcher/server.py`

- fix(launcher): 修复 Safari 标签页图标显示为首字符"1"而非头盔 logo
  - 根因（两层）：① Safari 固定标签页不用 PNG favicon，需专用 mask-icon（单色 SVG），缺失时按访问地址首字符显示符号（IP 访问显示"1"）；② 2026-08-14 (2) 为破 Chrome 缓存给图标链接加的 `?v=N` 查询串触发 WebKit 图标处理异常——日志显示 Safari 成功拉到图标（200）仍回退首字符符号，而 DD/DC 均为无参数 `/favicon.png` 且工作正常。
  - 修复：用 cv2 从 `logo.png` 描摹黑色头盔线条生成单色 mask-icon SVG（`fill-rule=evenodd` 保留镂空细节）；生成 180×180 `apple-touch-icon.png` 与多尺寸 `favicon.ico`（16/32/48）；`_serve_favicon` 泛化为 `_serve_icon` + `_ICON_FILES` 路由表（正确 Content-Type + 补 `Last-Modified`，与 Vite 行为一致）；所有图标链接去掉查询串与 DD/DC 对齐，取代 (2) 的 `?v=2` 方案。
  - 验证：本机测试实例四个图标 URL 均返回 200 与正确 Content-Type；SVG 描摹经浏览器放大渲染目检与原 logo 一致。
  - 涉及文件：`donkeycar/launcher/server.py`、`donkeycar/launcher/donkey_favicon.svg`（新增）、`donkeycar/launcher/donkey_touch_icon.png`（新增）、`donkeycar/launcher/donkey_favicon.ico`（新增）

## 2026-08-14 (3)

- fix(launcher): Donkey 菜单页容器去掉 900px 限宽，全宽贴合浏览器两边
  - 问题：`MENU_HTML` 的 `.container` 原为 `max-width:900px; margin:0 auto`，宽屏浏览器下页面左右两侧大片空白，与 DonkeyDrifter / Drifter Console 随浏览器宽度贴合两边的全宽设计语言不一致。
  - 修复：`.container` 改为 `width:100%; margin:0`，页头、CWD 栏、菜单面板、底部提示随浏览器宽度整行铺满（保留 body 12px 边距）。
  - 验证：本机 8091 端口测试实例 + Playwright 截图实测，1920px 宽屏下菜单整行铺满到两边，800px 窄视口下排版正常无溢出。
  - 涉及文件：`donkeycar/launcher/server.py`

## 2026-08-14 (2)

- fix(launcher): 修复 Donkey 页浏览器标签页 favicon 不显示 + 页头新增 logo 图标
  - 根因：浏览器将早期"该页无图标"的状态缓存在本地 favicon 数据库中（重启系统不会清除），导致服务端虽已正确提供图标，标签页仍不显示。
  - 修复：两处 HTML 模板（`MENU_HTML`、`LAUNCH_DRIVE_HTML`）的 favicon 链接改为 `/favicon.png?v=2`，URL 变化强制浏览器重新拉取，绕过旧缓存；favicon 响应增加 `Cache-Control: no-cache`。
  - 新增 `/favicon.ico` 路由，与 `/favicon.png` 共用同一 PNG（即 projects 主文件夹的头盔 logo，MD5 `82ddb5cf…`）。
  - 菜单页页头 Donkey 标题左侧新增 32px 可见 logo（`.headerLogo`，复用 `/favicon.png`），圆角描边样式与菜单序号徽标一致。
  - 验证：本地测试实例实测页面输出正确、`/favicon.png?v=2` 与 `/favicon.ico` 均返回 200 且字节与 logo.png 一致。
  - 涉及文件：`donkeycar/launcher/server.py`

- fix(web_ui): 滑块恢复为 #47 用户确认的 14×12px 纯白椭圆 thumb（撤销 #71 的原生回退）
  - 用户确认"最初的椭圆形"= #47 的自定义纯白椭圆（14×12px rounded-full）；#71 按字面恢复 pre-#43 原生 thumb 后在 Chrome 渲染为半透明圆环（可见轨道），非用户所要。
  - 恢复 #68 状态：`h-3 bg-transparent` + 轨道伪元素 `h-1.5 mt-[3px]` + thumb `w-[14px] h-[12px] bg-white rounded-full border-none -mt-[3px]`（居中公式 (6−12)/2=−3px）。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-14

- fix(web_ui): 控制参数滑块恢复最初的原生样式（用户指示"直接复制最初的白色小点和轨道"）
  - ParamSlider 的 input 恢复为最初未改动版本：`w-full h-1.5 bg-zinc-800 rounded-lg appearance-none cursor-pointer`（input 自身即轨道，thumb 完全原生渲染），移除全部 `::-webkit-slider-thumb` / `::-webkit-slider-runnable-track` 等伪元素自定义样式。
  - 与最初版本唯一差别：`accent-cyan-500` → `accent-white`，保证任何浏览器下 thumb 都是纯白（Safari 下两者均渲染为白色原生椭圆）。
  - 实测（Playwright Chromium + WebKit）：该布局下原生 thumb 与轨道中心偏差 0.0px，无白色背景条（input 背景已被 bg-zinc-800 覆盖），thumb 渲染在轨道之上。
  - 验证：`npm run build` 与 `vitest`（13 文件 61 用例）全部通过。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

- fix(web_ui): 滑块 input 补 `bg-transparent`，消除白色背景条（用户所见"第三根线"）
  - 根因（实测验证）：Chrome/Safari 对 `appearance:none` 的 range input 默认绘制**白色背景**，上一版把 input 高度从 6px 改为 12px 且未覆盖背景后，深色面板上出现一条 12px 白色横条，轨道嵌在其中，视觉上成了"三根线"，白色 thumb 叠在白条上也难以辨认形状。
  - 修复：input 增加 `bg-transparent`；thumb 保持 `w-[14px] h-[12px]` 纯白椭圆（即 #47 用户认可的"最开始的椭圆形"尺寸）不变。
  - 验证：Playwright Chromium + WebKit 双引擎截图对比，加 `bg-transparent` 后白色横条消失，只剩锌色轨道（原始"两根线"观感）+ 居中白色椭圆 thumb；`npm run build` 与 `vitest`（13 文件 61 用例）全部通过。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-14 (1)

- feat(web_ui): 新增 MUS4 Light 浅色皮肤并接入主题切换(切换按钮 47ee39fb 随本分支一并合入)
  - 新皮肤 `web_ui/frontend/src/themes/theme-light.css`:与深色皮肤 `theme-mus4.css` 同源同构,以 `html.theme-light` 前缀覆盖 Tailwind 工具类;色板直接对标固件自带浅色主题(`Firmware/MUS4_FW/libraries/mus4_web/src/WebConsoleAssets.h` 的 `html[data-theme="light"]` 与 `CHART_THEMES.light`)——页面 `#eef1f5`、面板 `#fff` + `135deg #fff→#edf1f6` 渐变 + 细框 `#ccd5df`,状态文字/细框/图表线用固件浅色饱和色(蓝 `#0c9bd6`、绿 `#1fae6b`、红 `#e5484d`、琥珀 `#d99a17`),FILL 实色填充语言(蓝 `#5cc8ff` 等 + 近黑文字 `#061019`)保持不变;深色皮肤所有颜色逐字节未动。
  - 主题设施 `web_ui/frontend/src/lib/theme.ts`:localStorage 持久化(key `donkeydrifter.ui.theme`)、`<html>` 皮肤 class 切换、`useResolvedTheme()` 订阅钩子(canvas/图表配色用);`web_ui/frontend/index.html` 内联脚本首屏前应用主题防闪烁(跟随系统经 matchMedia 解析);`web_ui/frontend/src/components/ThemeSwitcher.tsx` 接入真实切换;"跟随系统"经 `matchMedia('(prefers-color-scheme: dark)')` 实时解析并监听系统主题变化自动跟随。
  - canvas/图表/内联样式/Tailwind 任意值类等皮肤 CSS 覆盖不到的 JS 配色全部改为主题感知(深色值逐字节保留在三元分支中):`drive/TelemetryChart.tsx`、`TubEditor.tsx`、`pages/PilotArenaPage.tsx`、`FabActions.tsx`、`EnterButtons.tsx`、`drive/DriveModeSelector.tsx`、`drive/ModelSelector.tsx`、`drive/InputSourceSelector.tsx`、`drive/VideoStream.tsx`、`TubNavigator.tsx`、`ui/Button.tsx`。
  - 测试同步:`ThemeSwitcher.test.tsx` 新增皮肤 class 应用/挂载恢复/跟随系统解析/系统主题实时跟随等 7 个用例;`drive/DriveModeSelector.test.tsx` 新增浅色配色切换用例;vitest 全量 14 文件 72 用例通过,`tsc -b` 与 `vite build` 通过,Playwright 5 页 × 深浅双主题截图复核。
  - `theme-mus4.css` 仅更新文件头注释(皮肤机制说明),无样式改动。

## 2026-08-12 (13)

- fix(web_ui): 滑块 thumb 改为 14×12px 纯白椭圆并精确垂直居中于轨道
  - 根因（实测验证）：WebKit/Blink 在轨道被自定义样式后，将原生 thumb 的**顶边对齐轨道顶边**，导致 thumb 中心比轨道中心低 (thumb高−轨道高)/2（Chromium 实测偏下 4.9px，WebKit 实测偏下 6.9px），上一版仅靠 `h-3` + 轨道 `mt-[3px]` 无法修正。
  - 修复：thumb 用自定义样式 `w-[14px] h-[12px] bg-white rounded-full border-none`（横向椭圆，与 Safari/macOS 原生 thumb 形状一致，纯白不透明完全遮挡轨道），居中 margin 按公式计算：`margin-top = (轨道高 6px − thumb 高 12px) / 2 = -3px`，非试凑值。
  - 验证：Playwright Chromium + WebKit 双引擎截图像素级测量，thumb 中心与轨道中心偏差均为 0.0px；`npm run build` 与 `vitest`（13 文件 61 用例）全部通过。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (12)

- fix(web_ui): 滑块 thumb 垂直居中于轨道
  - input 高度从 `h-1.5`（6px）改为 `h-3`（12px）容纳原生 thumb；轨道仍 `h-1.5`（6px）但加 `mt-[3px]` 在 12px 空间中垂直居中，thumb 原生渲染（`accent-white`）在 12px 空间中自然居中于轨道。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (11)

- fix(web_ui): 滑块 thumb 恢复原生渲染，仅将轨道移到独立伪元素层
  - 移除全部自定义 `::-webkit-slider-thumb` / `::-moz-range-thumb` 样式（多轮尝试均未匹配原生形状/大小）。
  - 保留 `accent-white`（原生 thumb：形状/大小/位置完全不变，纯白色）。
  - 轨道样式从 input 背景移到 `::-webkit-slider-runnable-track` / `::-moz-range-track` 伪元素，确保轨道画在 thumb 下方而非覆盖其上。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (10)

- fix(web_ui): 滑块 thumb 宽度从 16px 缩至 14px（w-4 → w-3.5），高度/位置不变
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (9)

- fix(web_ui): 滑块 thumb 改为 16×12px 椭圆形匹配 Safari 原生渲染
  - PR #55 的 `w-3 h-3`（12×12px）是正圆形，且不加 margin 在 Safari 中位置不对。
  - 用户浏览器（Safari/macOS）原生 thumb 是椭圆形（宽大于高），改为 `w-4 h-3`（16×12px）+ `rounded-full`（椭圆）+ `-mt-[3px]`（垂直居中：(12-6)/2=3px）。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (8)

- feat(launcher): Donkey 菜单页采用 Drifter Console 设计语言
  - `MENU_HTML` 完全重写为 DC 暗色仪表盘风格：背景 `#101318`、`system-ui` 字体、DC headerRow（h1 "Donkey" + version 副标题）、DC panel（`#171c24` bg + `#2b3441` border）、菜单项从 table 改为 DC state card（`linear-gradient` + `#344154` border）、分类标签用 DC 语义色 pill（管理=cyan, 数据=green, 驾驶=amber, 筛选=purple, 训练=red）、编号用 Consolas monospace cyan 徽章、DC reconnect overlay、DC dialog 风格帮助弹窗。
  - `LAUNCH_DRIVE_HTML`：`<title>` 改为 "Donkey"，添加 favicon link。
  - `do_GET` 新增 `/favicon.png` 路由 + `_serve_favicon()` 方法。
  - 新增 `donkeycar/launcher/donkey_favicon.png`：使用 projects 原有头盔 PNG 图标（与 `287205692.png` 一致）。
  - 涉及文件：`donkeycar/launcher/server.py`、`donkeycar/launcher/donkey_favicon.png`

## 2026-08-12 (7)

- fix(web_ui): 修正滑块 thumb 尺寸为 12×12px 匹配原生渲染
  - PR #53 的 `w-3 h-2`（12×8px）尺寸过小且加了不必要的 `-mt-px` 偏移，与原生 thumb 形状不符。
  - 通过 Playwright 截图对比确认：原生 thumb 约 12px 圆形、Chrome 在 `appearance: none` 下自动居中、无需手动 margin。
  - 本次改为 `w-3 h-3 rounded-full bg-white border-none`，不加 margin，与原生渲染尺寸/位置/形状一致。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (6)

- fix(web_ui): 修复滑块 thumb 无法遮挡轨道的问题（渲染层级分离）
  - 问题根因：`bg-zinc-800` 直接画在 `<input>` 元素背景上，可能与原生 thumb 的渲染层级冲突，导致轨道穿透 thumb 显示。
  - 将轨道样式从 input 背景移到 `::-webkit-slider-runnable-track` / `::-moz-range-track` 伪元素，确保轨道作为独立层绘制在 thumb 下方。
  - thumb 使用自定义 `::-webkit-slider-thumb` / `::-moz-range-thumb`：`w-3 h-2 rounded-full bg-white border-none -mt-px`（12×8px 椭圆形、垂直居中、纯白不透明），完全遮挡下方 6px 轨道。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (5)

- fix(launcher): 菜单页检测 `#drive` hash 自动启动 DonkeyDrifter
  - Drifter Console 固件 v1.7.62 起，"进入 DonkeyDrifter"按钮改为 `<a href="http://<ip>:8090/#drive" target="_blank">`，与"进入 Donkey"使用相同的 `/` 路径（仅 hash 不同），规避 Safari 无法加载 `/launch/drive` 的问题。
  - `donkeycar/launcher/server.py`：`MENU_HTML` 初始化代码检测 `location.hash === '#drive'`，自动调用 `launchDrive()` 启动驾驶。
  - 涉及文件：`donkeycar/launcher/server.py`

- feat(web_ui): 添加进入 Donkey 和进入 DrifterConsole 按钮
  - 新增 `EnterButtons` 组件，样式与 Drifter Console 的 otaButton 一致。
  - 进入 Donkey：打开 `http://<host>:8090/` Launcher。
  - 进入 DrifterConsole：扫描局域网 ESP32 设备并打开 Web Console。
  - 后端新增 `/connector/discover_console` 端点。
  - 布局：GitHub 图标右侧、语言切换键左侧。
  - 涉及文件：`web_ui/frontend/src/components/EnterButtons.tsx`、`EnterButtons.test.tsx`、`Layout.tsx`、`i18n/messages/common.ts`、`services/api.ts`、`web_ui/backend/routers/connector.py`、`web_ui/backend/tests/test_connector.py`

- feat(launcher): Donkey 菜单页采用 Drifter Console 设计语言
  - `MENU_HTML` 完全重写为 DC 暗色仪表盘风格：DC panel + state card 菜单项 + 语义色 pill 分类标签 + DC reconnect overlay + DC dialog 帮助弹窗。
  - `LAUNCH_DRIVE_HTML`：title 改为 Donkey，添加 favicon link。
  - `do_GET` 新增 `/favicon.png` 路由 + `_serve_favicon()` 方法。
  - 新增 `donkey_favicon.png`（200×200 cyan D 图标）。
  - 涉及文件：`donkeycar/launcher/server.py`、`donkeycar/launcher/donkey_favicon.png`

## 2026-08-12 (4)

- fix(web_ui): 控制参数滑块拖拽点改为纯白色（仅改颜色，不改形状）
  - 移除 PR #47 添加的全部自定义 `::-webkit-slider-thumb` / `::-moz-range-thumb` 样式（改变了原生椭圆形），改为 `accent-white`：浏览器原生渲染形状完全不变，仅将 accent-color 从 `#5cc8ff`（MUS4 主题覆写后的 accent-cyan-500）改为 `#ffffff` 纯白。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (3)

- fix(web_ui): 控制参数滑块拖拽点改为纯白不透明椭圆形
  - 上一版（#45）恢复 `accent-cyan-500` 浏览器原生渲染后，原生 thumb 仍透出下方深色轨道。
  - 本次使用自定义 `::-webkit-slider-thumb` / `::-moz-range-thumb` 样式：`w-3.5 h-3 rounded-full bg-white`，椭圆形（14×12px）、垂直居中（无 `-mt-1` 偏移）、纯白不透明，完全遮挡下方轨道。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-12 (2)

- fix(launcher): `/launch/drive` 跳转页等待 vite 就绪后再重定向
  - 背景：POST `/api/launch/drive` 启动 `donkey web`（vite 开发服务器）时会先杀旧进程再启新进程，POST 立即返回后页面立即重定向到端口 5188，但新 vite 需数秒才就绪，导致 Safari 显示"无法连接服务器"。
  - `donkeycar/launcher/server.py`：`LAUNCH_DRIVE_HTML` 的 JS 改为先轮询前端 URL（`fetch` + `mode:'no-cors'`，最多 30 次 × 1s = 30s），就绪后再 `window.location.href` 跳转；等待期间显示进度计数器 `(N/30)`。
  - 涉及文件：`donkeycar/launcher/server.py`

- fix(web_ui): 恢复 Drive 页面控制参数滑块为浏览器原生样式
  - 上一版（#43）为滑块添加了自定义 `::-webkit-slider-thumb` / `::-moz-range-thumb` 样式（`w-3.5 h-3.5 rounded-full -mt-1 shadow-[0_0_0_2px_#09090b]`），导致拖拽点由原生椭圆形变成正圆形、垂直方向偏上、且 shadow 环仍透出轨道。
  - 本次移除全部自定义 thumb 样式，恢复为 `accent-cyan-500` 浏览器原生渲染：拖拽点恢复为椭圆形、垂直居中、完全不透明（看不到下方轨道）。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`

## 2026-08-11 (10)

- fix(web_ui): Drive 页面控制参数面板三个显示问题修复
  - 滑块拖拽点透出轨道：白色拖拽点（`::-webkit-slider-thumb` / `::-moz-range-thumb`）添加 `shadow-[0_0_0_2px_#09090b]`，用面板背景色（zinc-950）在拖拽点周围生成 2px 实心环，遮住背后深色轨道（zinc-800），拖拽点保持纯白。
  - "重置默认"按钮文字换行：ParameterPanel 宽度从 `max-w-[320px]` 加宽到 `max-w-[360px]`（内边距 `px-3` 不变，按钮到边框距离不变）；三个按钮文本各自包裹 `<span className="whitespace-nowrap">` 双重保险防止换行。
  - 导出/导入图标大小不一致：三个图标（RotateCcw / Download / Upload）从 Tailwind `w-3 h-3` 类改为 lucide-react `size={12}` prop，统一尺寸设置方式。
  - 涉及文件：`web_ui/frontend/src/components/drive/ParameterPanel.tsx`、`web_ui/frontend/src/pages/DrivePage.tsx`

## 2026-08-11 (9)

- feat(launcher): 新增 GET `/launch/drive` 端点，返回极简跳转 HTML 页面
  - 背景：Drifter Console（ESP32 Web Console）的"进入 DonkeyDrifter"按钮原先用 `location.href` 导航到 POST-only 的 `/api/launch/drive`，GET 请求返回 404；且跨域 fetch 会被浏览器 CORS 拦截。
  - `donkeycar/launcher/server.py`：`do_GET` 新增 `/launch/drive` 路由，返回 `LAUNCH_DRIVE_HTML` 页面；页面加载后自动 fetch POST `/api/launch/drive`（同源），拿到 drive URL 后 `window.location.href` 重定向到 Drive 页面。Drifter Console 侧改为 `window.open('http://'+ip+':8090/launch/drive','_blank')` 在新标签页打开。

## 2026-08-11 (8)

- feat(launcher): 输入 6 后在新标签页打开 Drive 页面，保留 Launcher 菜单
  - 此前按 6 后 `window.location.href` 直接在当前标签页跳转，Launcher 菜单被替换掉。
  - `donkeycar/launcher/server.py`：`launchDrive()` 中改为 `window.open(url, '_blank')` 在新标签页打开；若被弹窗拦截器阻止则回退到当前页跳转。

## 2026-08-11 (7)

- fix(web_ui): DrivePage 在非安全上下文下 `crypto.randomUUID()` 崩溃导致"Something went wrong"
  - 问题：通过局域网 IP（非 localhost、非 HTTPS）访问 Drive 页面时，`crypto.randomUUID()` 不可用（返回 undefined），`createDriveClientId()` 调用时抛 TypeError；其 catch 块再次调用同一 API，异常未被捕获，传播到 React ErrorBoundary 显示"Something went wrong"。
  - `web_ui/frontend/src/services/api.ts`：新增 `generateUuid()` 辅助函数，优先使用 `crypto.randomUUID()`，不可用时回退到 `crypto.getRandomValues()`（非安全上下文也可用）；替换 `createDriveClientId()` 和 `createDriveWebRtcSession()` 默认参数中的 2 处 `crypto.randomUUID()` 调用。

## 2026-08-11 (6)

- fix(tubplot): 修复 Ubuntu 上 Tub 数据图表不显示--matplotlib 自动检测图形会话 DISPLAY 并切换 TkAgg 后端
  - 问题：`donkey tubplot` / `donkey tubhist` / `donkey cnnactivations` 在 Ubuntu 上运行时 `plt.show()` 不弹窗。根因是 matplotlib 在 `DISPLAY` 未设置时（SSH、Web 后台子进程等）默认回退到 `agg` 非交互式后端。
  - `donkeycar/management/base.py`：新增 `_ensure_display_and_backend()`（检测当前后端为 `agg` 时尝试切换 `TkAgg`）和 `_detect_graphical_display()`（从 `/proc/<pid>/environ` 读取 Xwayland/Xorg 进程的 `DISPLAY` 和 `XAUTHORITY`，支持 Wayland 下 Xwayland）；在 `ShowPredictionPlots`、`ShowHistogram`、`ShowCnnActivations` 三个类的 pyplot 导入前调用。
  - `mycar/manage.py`（本机）：菜单选项 4 和 Web 控制台启动 tubplot 时为子进程设置 `DISPLAY=:0`。
  - 验证：`donkey tubplot`（无 `--noshow`）GUI 窗口正常弹出（进程阻塞等待关闭）；`donkey tubhist` 同上且正确保存 PNG；`pytest test_tubplot` 通过。

## 2026-08-11 (5)

- feat(web_ui): DonkeyDrifter 页面 header 新增版本号显示，放在 GitHub 图标左侧
  - 背景：Drifter Console（ESP32 Web Console）已有版本号显示，DonkeyDrifter Web UI 缺失；用户要求参考 DC 样式补上。
  - `web_ui/backend/routers/config.py`：新增 `GET /version` 端点，从 `donkeycar._version.__version__` 返回 `{"version": "0.1.2"}`。
  - `web_ui/frontend/src/services/api.ts`：新增 `getVersion()` 异步函数调用 `/config/version`。
  - `web_ui/frontend/src/components/VersionBadge.tsx`（新）：版本徽章组件，挂载时请求版本号，加载中/出错时不渲染，正常时以 `text-zinc-500 text-xs uppercase tracking-wider` 样式显示 `v{version}`（参考 DC 的 `.version` 样式）。
  - `web_ui/frontend/src/components/Layout.tsx`：在 `<GitHubLink />` 左侧放置 `<VersionBadge />`。
  - 测试同步：`web_ui/backend/tests/test_config.py` 新增 `test_get_version_returns_version_string`；`web_ui/frontend/src/components/VersionBadge.test.tsx`（新）含 3 项用例（渲染版本号含 v 前缀、加载中不渲染、出错不渲染）。
  - 验证：后端 2/2 通过，前端 VersionBadge 3/3 通过，全套 54/54 通过。

## 2026-08-11 (4)

- fix(launcher): 新增孤儿进程清理--通过 pkill 按进程名搜索杀掉所有 donkey web / manage.py drive 进程
  - 背景：PID 文件方式只能杀掉最后一次启动的进程；如果用户在终端多次启动 DonkeyDrifter（或直接运行 `donkey web` 未写 PID 文件），旧进程会成为孤儿占用硬件资源。
  - `donkeycar/launcher/server.py`：新增 `_kill_orphaned_donkey_processes()`，使用 `pkill -f "donkey web"` 和 `pkill -f "manage.py drive"` 先 SIGTERM 后 SIGKILL 清理所有匹配进程；`_launch_drive()` 在 `_kill_previous_drive_processes()` 之后调用该函数作为兜底。
  - 验证：4 项测试全部通过（PID 文件杀进程、孤儿进程清理、5 次反复点击循环、混合场景）。

## 2026-08-11 (3)

- fix(launcher): 每次启动 drive 前强制杀掉上一次的进程，不再返回 already_running
  - 问题：此前 Launcher 检测到自己跟踪的进程仍在运行时直接返回 `already_running` 而不杀掉重启，导致用户反复点击"进入 DonkeyDrifter"或菜单输入 6 时无法清理旧进程（可能占用摄像头等硬件资源）。
  - `donkeycar/launcher/server.py`：`_launch_drive()` 移除 `already_running` 早退逻辑，改为每次调用都先执行 `_kill_previous_drive_processes()`（通过 `~/.donkeycar/drive.pid` 追踪并 SIGTERM→SIGKILL），再清理 launcher 内部进程引用，然后启动新进程。
  - 验证：代码逻辑检查通过（无 already_running、仅一次 kill 调用）；服务重启后 API 正常响应。

## 2026-08-11 (2)

- fix(launcher): Launcher 服务启动时通过串口向 ESP32 报告本机 IP（HOSTIP|<ipv4>），配合 Firmware v1.7.57 按钮动态获取 IP
  - `donkeycar/launcher/server.py`：新增 `_get_local_ip()`（优先返回 192.168.x.x 局域网 IP，排除 VPN/TUN 接口）、`_report_hostip_to_esp32()`（尝试 /dev/ttyACM0、/dev/ttyACM1、/dev/ttyUSB0 写入 HOSTIP 帧）、`_hostip_reporter_loop()`（每 30 秒上报一次的后台线程）、`_start_hostip_reporter()`；`run_server()` 启动时调用后者拉起 daemon 线程。
  - 说明：此为 best-effort 机制；当 `manage.py drive` 运行时，其 `ProvisioningPart` 会通过 Arduino 共享串口正确上报 HOSTIP，Launcher 的独立串口写入仅在没有车辆进程时作为补充。

## 2026-08-11

- feat(launcher): 新增 `donkeycar/launcher/` 模块--浏览器端 DonkeyDrifter 启动服务，无需打开终端即可从 ESP32 Drifter Console 一键进入 DonkeyDrifter
  - 背景：此前进入 DonkeyDrifter 需在终端输入 `donkey` 再输入 `6`，启动 `donkey web` + `manage.py drive` 两个子进程。新方案在宿主机上运行常驻 Launcher 服务（端口 8090），ESP32 Web Console 的"进入 donkey"/"进入 DonkeyDrifter"按钮直接跳转到该服务。
  - `donkeycar/launcher/server.py`：基于标准库 `http.server` 的轻量 HTTP 服务（无 Flask/FastAPI 依赖）。`GET /` 提供仿 TUI 菜单页面（dark theme、rich 风格表格、10 项菜单与 tui.py 一致、键盘数字选择）；`GET /api/status` 返回进程状态 JSON；`POST /api/launch/drive` 启动 `donkey web`（指定 `--backend-port` + `--frontend-port`，不带 `--open`）和 `manage.py drive`（注入 `DRIVE_API_SERVER_URL` 环境变量），PID 写入 `~/.donkeycar/drive.pid`，返回前端 URL（`http://<host>:<frontend_port>/#/drive`）。
  - `donkeycar/launcher/__main__.py`：入口点，支持 `--port`（默认 8090）和 `--host`（默认 0.0.0.0）参数。
  - `donkeycar/launcher/donkeydrifter-launcher.service`：systemd 用户服务模板，使用 conda 环境 Python，`WorkingDirectory=/home/dkc/projects/mycar`，`Restart=always`。
  - 前端页面 JS：键盘 1-9/10 选择菜单项（与终端一致），输入 6 触发 `/api/launch/drive` POST 并重定向；URL 中 `localhost` 替换为 `window.location.hostname` 以支持远程设备访问。
  - 安装方式：`cp donkeydrifter-launcher.service ~/.config/systemd/user/ && systemctl --user enable --now donkeydrifter-launcher`，`loginctl enable-linger dkc` 开机自启。
  - 验证：服务启动正常，`GET /` 返回菜单 HTML，`GET /api/status` 返回正确 JSON；systemd 用户服务 active (running)。

## 2026-08-10

- fix(cli): `donkey web`/`donkey drive` 自动打开浏览器前等待前端端口就绪，修复 TUI 选项 6/7 启动后浏览器打开"无法连接"页面的问题
  - 根因：`_launch_web_ui()` 拉起 Vite 前端进程后立刻 `webbrowser.open()`，Vite 需数秒才开始监听，浏览器在端口未监听时打开即显示无法连接且不会自动恢复（VS Code "View in Browser" 弹窗在端口监听后才出现，故点击总能正常打开）。
  - `donkeycar/management/base.py`：`Web` 新增 `_wait_for_port_ready()`（TCP 轮询本机端口直至可连接，默认 30s 超时）与 `_open_browser_when_frontend_ready()`（先等前端端口就绪再开浏览器；超时仍打开并打印警告，退化为旧行为由用户自行刷新）；`Web.run()` 与 `Drive.run()` 的 `--open` 路径统一改走该等待；`Drive._wait_for_backend_ready()` 复用 `_wait_for_port_ready()` 实现。
  - 测试同步：`donkeycar/tests/test_web_command.py` 的 `test_web_command_opens_requested_route` 补 `_wait_for_port_ready` monkeypatch（避免真实 socket 等待），新增 3 项用例（`_wait_for_port_ready` 对监听/关闭端口的探测、等待前端端口后再开浏览器、等待超时仍打开浏览器兜底）；`donkeycar/tests/test_drive_command.py` 新增 `test_drive_run_waits_for_frontend_port_before_opening_browser`。
  - 验证：相关 30 项测试全部通过；真实拉起 `donkey web --open` 端到端验证——浏览器打开回调在 Vite 就绪后才触发，打开瞬间该 URL 已返回 HTTP 200，退出时子进程清理正常。

## 2026-08-08

- fix(test): 修复配网循环韧性回归测试在 macOS CI 上的时序抖动（main 分支 run #198 失败）
  - 背景：main 分支 CI（macos-latest 任务）报 `donkeycar/tests/test_provisioning.py::TestProvisioningPartUpdateResilience::test_loop_continues_after_unexpected_exception` 失败（`assert 3 > 3`）——用例固定 `sleep(0.5)` 后断言循环调用超过 3 次，macOS runner 线程启动慢时 0.5s 内只跑了 3 次循环（ubuntu 与本地正常）。
  - `donkeycar/tests/test_provisioning.py`：改为轮询等待（`monotonic()` 5s 超时、20ms 间隔），循环跑过前 3 次异常调用后再 shutdown，不再依赖固定时长 sleep；测试意图（循环兜住异常继续运行）与断言不变。
  - 验证：该用例本地连跑 5 遍通过；`pytest donkeycar/tests/test_provisioning.py` 94 项全部通过。
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

