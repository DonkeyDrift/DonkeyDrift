# 变更日志

## 2026-08-20 (78)

- fix(web-ui): DD 主题切换改为会话级持久化，避免手动选择永久覆盖「跟随系统」
  - `web_ui/frontend/src/lib/theme.ts`：主题持久化存储由 `localStorage` 改为 `sessionStorage`（`readStoredTheme` 读取与 `setTheme` 写入两处），手动选择仅在当前标签页会话内生效，关闭标签页后重新跟随系统，消除「点过一次主题按钮后永远不再跟随系统」的问题。
  - `web_ui/frontend/index.html`：首屏内联脚本同步改读 `sessionStorage`，旧 `localStorage` 残留不再影响首屏主题。
  - `web_ui/frontend/src/components/ThemeSwitcher.tsx`：注释更新为会话级持久化语义。
  - 测试同步：`ThemeSwitcher.test.tsx` 断言由 `localStorage` 改为 `sessionStorage`；`vitest` ThemeSwitcher 8 项通过、`npm run build`（tsc + vite）通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (77)

- fix(drive): 摄像头按可用高度反推宽度并略降曲线图高度，画面更大且消除左右黑边
  - `web_ui/frontend/src/pages/DrivePage.tsx`：左列改为 `flex flex-col` + 桌面端 `lg:h-[calc(100vh-9rem)]`，摄像头区 `flex-1` 撑满剩余高度；`VideoStream` 由 `w-full + max-h` 改为 `lg:h-full lg:w-auto lg:max-w-full` 居中，按实际画面比例反推宽度，替换原先高度压缩时 `object-contain` 产生的左右黑边。
  - `web_ui/frontend/src/components/drive/TelemetryChart.tsx`：曲线区高度 `h-48` → `h-40`，为摄像头让出更多纵向空间。
  - 测试同步：`npm run build`（tsc + vite）通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (76)

- fix(drive): 限制摄像头高度，让 Drive 页摄像头与下方遥测曲线同屏可见
  - `web_ui/frontend/src/pages/DrivePage.tsx`：`VideoStream` 增加 `lg:max-h-[calc(100vh-32rem)]` 视口高度上限。摄像头按实际画面比例自适应后，在常见桌面屏上画面过高会把 `TelemetryChart` 顶出首屏；加此上限后曲线无需滚动即可同屏显示。`VideoStream` 内部画面为 `object-contain`，高度被压缩时完整居中、只留黑边不裁切。
  - 测试同步：`npm run check`（tsc）通过、`npm run build`（vite）通过，产物含该类名与 `max-height: calc(100vh - 32rem)` 规则。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (75)

- fix(web-ui): Donkey 内嵌页改为全屏铺满，并修正 Donkey 模式下的顶栏高亮、侧栏遮挡与帮助小球
  - `web_ui/frontend/src/pages/DonkeyMenuPage.tsx`：去掉 DD 侧标题栏与 `space-y-3` 包装，iframe 铺满顶栏以下全部可视区域（`h-[calc(100vh-3.5rem)]` + `h-full w-full border-0`），用户看到与真实 Donkey 启动页（8090）一致的完整界面。
  - `web_ui/frontend/src/App.tsx`：`isConsole` 扩展为 `isFullBleed`（`/console` 或 `/donkey`），`/donkey` 同样隐藏左侧 Loaders/Connectors 浮动抽屉，避免遮挡内嵌 launcher。
  - `web_ui/frontend/src/components/Layout.tsx`：新增 `isDonkey`/`isFullBleed`；`/donkey` 时流程锚点（Drive 等）一律不高亮；`<main>` 在 `/donkey` 改 `py-0` 全屏比例；`/donkey` 隐藏 DD 右下角 FAB，让 launcher 自带的 Donkey 帮助小球显示、不与 DD FAB 重叠。
  - `web_ui/frontend/src/components/EnterButtons.tsx`：`DonkeyEntryLink` 增加 `/donkey` 激活态（`text-cyan-500`），修复「在 Donkey 页时 Drive 为蓝色、Donkey 为灰色」。
  - 测试同步：`EnterButtons.test.tsx` 新增 Donkey 激活态断言；`App.test.tsx` 新增 `/donkey` 隐藏 SidePanel 与 FabActions 的断言；前端 vitest 21 文件 114 项、`npm run check`（tsc）、`npm run build` 全部通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (74)

- fix(flow): Drive/TM/Trainer/PA 大页节标题的灰色小字由垂直居中改为基线对齐，与标题视觉平行（Issue #233）
  - `web_ui/frontend/src/pages/FlowPage.tsx`：`FlowSectionHeader` 内层容器由 `items-center` 改为 `items-baseline`，小字 span 去掉多余的 `leading-none`，与基准组件 `SectionCardTitle`（视频录制库/Top编辑器）的小字 class 保持一致，消除小字相对 `text-xl` 大标题偏高、不平行的问题。
  - 测试同步：`npm run check`（tsc）通过、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (73)

- fix(drive): 虚拟摇杆抽屉展开/收起动画收窄过渡属性，减少卡顿（Issue #232 后续）
  - `web_ui/frontend/src/pages/DrivePage.tsx`：抽屉面板由 `transition-all` 改为 `will-change-[width] transition-[width]`，展开/收起只过渡 width，不再同时过渡 border 等 layout 属性，降低每帧 reflow/paint 负担。
  - `web_ui/frontend/src/components/ui/SectionCardTitle.tsx`：跑马灯副标题外层由 `transition-all` 改为 `transition-[opacity,margin-left]`，去掉 max-width 的 layout 过渡（宽度瞬时切换、由 `overflow-hidden` 裁剪），避免 hover 触发跑马灯时与抽屉展开动画叠加产生额外 reflow。
  - 测试同步：前端 vitest 21 文件 112 项通过、`npm run check`（tsc）通过、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-20 (72)

- fix(console): Drifter Console 连接条微调——「未发现设备」文案缩短、版本号样式对齐 DD 顶栏版本号、连接条与 iframe 视觉融合（Issue #234）
  - `web_ui/frontend/src/i18n/messages/console.ts`：`console.noDevice` 中英两处缩短为「未发现设备」/「No device found」，去掉「请确认同一网络」半句。
  - `web_ui/frontend/src/pages/DrifterConsolePage.tsx`：
    - 工具条去掉 `border-b border-zinc-800 bg-zinc-900/50`，改为与下方 iframe 同底色、无分隔线。
    - 版本号由 `font-mono text-xs text-zinc-400` 改为对齐顶栏 `VersionBadge` 的 `text-zinc-500 text-xs uppercase tracking-wider`，渲染为 `v{version}`（version 存纯版本号，去 V 前缀）。
  - 测试同步：前端 `npm run build`（tsc + vite）通过。
## 2026-08-20 (71)

- fix(launcher): Kimi Code Web 入口 origin 由 mDNS 主机名优先回退为局域网 IP 优先，恢复被 mDNS 迁移孤立的置顶与「完全自主」权限偏好（Issue #168 后续）
  - 背景：KCW 的置顶（`kimi-web.pinned-sessions`）、权限模式（`kimi-web.permission`）、onboarding 等 UI 偏好都存浏览器 localStorage、按 origin 隔离。前几轮为抗 DHCP 换 IP 漂移把入口 origin 稳定到 `tony007.local:58640`，但这次迁移本身把老 origin（局域网 IP `192.168.3.57:58640`）里的偏好孤立了——用户表现为「置顶全没了、原来是完全自主模式现在变逐条确认」。服务端无法跨 origin 读写浏览器 localStorage，唯一能恢复老偏好的办法是让入口 origin 回到老 IP。
  - `donkeycar/launcher/kimi_web.py`：`_entry_host()` 由 `return _mdns_hostname() or _lan_ip()` 改为 `return _lan_ip() or _mdns_hostname()`——局域网 IP 优先、mDNS 主机名兜底；同步更新模块 docstring、`_mdns_hostname()`/`_lan_url()`/`_mark_onboarded()`/`_allowed_host_values()` docstring 说明回退原因。`--allowed-host` 仍同时放行 mDNS 与局域网 IP，两种入口都能过 40301。
  - 测试同步：`tests/test_launcher_kimi_web.py` 的 mDNS 优先断言改为 IP 优先（loopback/本机 IP/local instance 三处），新增 mDNS 兜底用例（无局域网 IP 时回退 mDNS），删除已不可达的 mDNS rebind 门用例；`test_launcher_kimi_web.py` + `test_launcher_dsh_web.py` 共 81 passed。
  - 注：纯 DD launcher 改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (70)

- fix(console): Drifter Console 内嵌 iframe 改用 `?embedded=1` 参数加载，只隐藏 DD 嵌入视图里的车端 DC 标题栏，车端 DC 页面本身标题栏保持显示（Issue #234）
  - `web_ui/frontend/src/pages/DrifterConsolePage.tsx`：iframe `src` 由 `http://<ip>/` 改为 `http://<ip>/?embedded=1`。
  - 配套 Firmware 改动见 Firmware 仓库当日条目（v1.8.20 恢复 DC 标题栏显示、新增 `body.embedded .headerRow{display:none}` 与 embedded 参数检测）。

## 2026-08-19 (69)

- feat(console): Drifter Console 由 DD 风格重绘改为 iframe 1:1 嵌入车端原版，并在连接条「连接」按钮右侧显示车端固件版本号（Issue #234）
  - `web_ui/frontend/src/pages/DrifterConsolePage.tsx`：整页重写——删除 571 行 DD 风格重绘（状态 key=value 表格、遥测卡片、终端、Wi-Fi STA、OTA、开发模式、静音），改为 iframe 直接加载 `http://<ip>/`，排版与显示功能与车端 Web Console 完全一致；仅保留一条极简「发现/手动连接」工具条（设备选择下拉 + 重扫 + 手动 IP + 连接）。
  - 连接条版本号：`useEffect([selectedIp])` 调用车端 `api/status`，用 `version=(\S+)` 提取固件版本、去 `V` 前缀后以 `v1.8.19` 格式显示在「连接」按钮右侧（`font-mono text-xs text-zinc-400`）。
  - `web_ui/frontend/src/components/EnterButtons.tsx`：`DrifterConsoleEntryLink` 由「扫描车端 + `window.open` 新标签页打开车端原版」改为 `<Link to="/console">` 当前标签页内进入。
  - `web_ui/frontend/src/App.tsx`：新增 `/console` 懒加载路由与空闲预取；`isConsole` 时隐藏左侧 `SidePanel`（Loaders/Connectors 浮动抽屉不再遮挡 iframe），其它页面保持正常显示。
  - `web_ui/frontend/src/components/Layout.tsx`：`isConsole` 时流程锚点（Drive/TM/Trainer/PA）一律不高亮，Drifter Console 由 `DrifterConsoleEntryLink` 自身高亮，修复「打开 DC 时 Drive 仍为蓝色、DC 仍为灰色」；`<main>` 在 `/console` 改为 `py-0` 全屏比例。
  - `web_ui/frontend/src/i18n/messages/console.ts`：缩短「未发现设备，请确保连接同一网络」连接中提示文案。
  - 测试同步：前端 `npm run check`（tsc）与 `npm run build` 通过、vitest 全量通过。
  - 注：配套 Firmware 改动见 Firmware 仓库当日条目（v1.8.19 隐藏 DC 主页面 header 行）。

## 2026-08-19 (68)

- feat(web-ui): Donkey 菜单改为当前页内嵌显示，顶栏控件（静音/DEV/Car Connector）样式对齐 DC 与 OTA
  - `web_ui/frontend/src/App.tsx`：新增 `/donkey` 懒加载路由与空闲预取，指向新内嵌页 `DonkeyMenuPage`。
  - `web_ui/frontend/src/pages/DonkeyMenuPage.tsx`（新增）：以 iframe 嵌入 launcher(:8090) 的 Donkey 菜单页，点击顶栏 Donkey 不再新开标签页（与 Drifter Console 的 `/console` 一致）。
  - `web_ui/frontend/src/components/EnterButtons.tsx`：`DonkeyEntryLink` 由 `<a target="_blank">` 改为 `<Link to="/donkey">`，图标由 `Car` 改为 `Menu`；导出 `entryLinkCls` 供 Layout 复用。
  - `web_ui/frontend/src/components/ConsoleControls.tsx`：`ConsoleMuteButton` 静音态改 DC 蓝 `#5cc8ff`（边框/图标同色）并补 `aria-pressed`；`ConsoleDevToggle` 由滑块改为与 OTA 同款文字胶囊按钮（开启 cyan 高亮、关闭同 OTA 灰）。
  - `web_ui/frontend/src/themes/theme-mus4.css` / `theme-light.css`：`.console-mute-btn` 并入主题/语言按钮的双层内圈视觉（修复与语言切换按钮边框厚度不一致），并加静音激活态蓝色覆盖。
  - `web_ui/frontend/src/components/Layout.tsx`：Car Connector 导航项改用 `entryLinkCls`（与 KCW/DSH 同字号/弱化色）并加左侧 `Settings` 齿轮图标，桌面/移动端同步。
  - 测试同步：`EnterButtons.test.tsx` 断言 Donkey 改走 `/donkey` 内嵌路由；`ConsoleControls.test.tsx` 新增 DEV 胶囊与静音蓝态断言；前端 vitest 全量 21 文件 112 项、`npm run check`（tsc）、`npm run build` 全部通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (67)

- fix(drive): Drive 页虚拟摇杆抽屉面板移到把手左侧、标题不换行、副标题改为跑马灯（Issue #232 第五轮微调）
  - `web_ui/frontend/src/pages/DrivePage.tsx`：抽屉内部 `flex items-start gap-2` 中「面板内容」与「浮动触发把手按钮」对调，展开后顺序变为 视频画面 → 虚拟摇杆面板 → 把手开关，把手仍在面板右侧（展开时位于视频右侧更外侧）；`SectionCardTitle` 传入 `subtitleMarquee`。
  - `web_ui/frontend/src/components/ui/SectionCardTitle.tsx`：新增可选 `subtitleMarquee?: boolean` prop；标题 `<span>` 加 `whitespace-nowrap`，保证「虚拟摇杆」四字单行完整显示；副标题在 `subtitleMarquee` 为 true 时改为跑马灯渲染（外层 `overflow-hidden`、内层 `inline-block whitespace-nowrap` + `animate-[marquee-x_9s_ease-in-out_infinite]`），默认 false，不影响其他页面。
  - `web_ui/frontend/src/index.css`：新增 `@keyframes marquee-x`（`0% translateX(0)` → `72%`/`88% translateX(calc(-100% + 10rem))` 停顿 → `100% translateX(0)` 重播），实现副标题从左到右播放、到右端稍停后重播。
  - 测试同步：前端 vitest 21 文件 110 项通过、`npm run check`（tsc）通过、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (66)

- fix(web-ui): DonkeyDrifter 页主题按钮去掉「跟随系统」显示器图标，改为深/浅两态互切（默认仍跟随浏览器，但不显示跟随系统状态）（Issue #230 最终形态，DD 前端）
  - 背景：DD 前端（8000）主题按钮此前为 跟随系统/浅色/深色 三态，其中「跟随系统」显示显示器（电脑）图标；用户要求默认仍跟随浏览器，但按钮只保留太阳/月亮两态、去掉电脑图标。
  - `web_ui/frontend/src/components/ThemeSwitcher.tsx`：删除 `Monitor` 图标与 `NEXT_MODE`/`MODE_LABEL` 三态逻辑，改为按当前生效主题（`useResolvedTheme()`）在浅/深之间互切，图标仅太阳/月亮；aria-label 仅 `切换到浅色主题`/`切换到深色主题`。
  - `web_ui/frontend/src/lib/theme.ts`：删除仅三态按钮使用的 `useThemeMode` 与 `THEME_MODE_CHANGE_EVENT`；`setTheme` 不再广播 mode 事件，`useResolvedTheme` 订阅逻辑不变；`readStoredTheme` 仍默认 `system`（无存储时跟随浏览器并实时监听）。
  - `web_ui/frontend/src/components/ThemeSwitcher.test.tsx`：由三态用例改为两态用例（8 项），覆盖默认跟随系统、浅/深互切、持久化、手动选择后不再跟随。
  - 测试同步：`ThemeSwitcher` 8 项通过、`npm run check`（tsc）通过、`npm run build` 通过；完整前端 vitest 中 `App.test.tsx` 有 3 项因 `services/api` mock 缺 `getDonkeyUrl` 失败，为既有问题（PR #257 引入 `getDonkeyUrl` 未同步 mock），与本次改动无关。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (65)

- fix(web-ui): Drive 页顶部工具栏移入视频列，录制按钮右边缘与摄像头画面右边界对齐；修复 App.test mock 缺 getDonkeyUrl
  - `web_ui/frontend/src/pages/DrivePage.tsx`：顶部工具栏（左组 Park/模式/模型，右组录制条数/录制）由页面全宽独立一行移入「视频+遥测」左列（`flex-1 min-w-0`）内，右组右边缘随视频列收缩/扩展，抽屉展开时不再越过摄像头画面右边界；工具栏与视频之间加 `mb-4` 间距。录制与录制条数间隙保持 `gap-2 lg:gap-3` 不变。
  - `web_ui/frontend/src/App.test.tsx`：`vi.mock('./services/api')` 补 `getDonkeyUrl`（Issue #257 顶栏 Donkey 入口引入 `getDonkeyUrl` 后漏更新 mock，导致 3 项 App 测试失败）。
  - 测试同步：前端 vitest 21 文件 112 项通过、`tsc -b --noEmit`、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (64)

- feat(web-ui): 把 DC 头部静音/OTA/DEV/Donkey 四控件整合进 DonkeyDrifter 顶栏，重设计为 DD 风格，静音与车端 DC 双向同步
  - 背景：用户要求 DD 页面顶栏承担原 Drifter Console 头部的一部分控制——静音键放在 GitHub 图标右侧、主题切换左侧并与 DC 双向同步；OTA/DEV 开关放在语言切换右侧；Donkey 入口移入顶部导航栏并加图标（参考 Kimi/DeepSeek 入口样式）。
  - `web_ui/frontend/src/hooks/useConsoleDevice.ts`（新增）：模块级去重 + `sessionStorage` 缓存 ESP32 IP，导出 `useConsoleDevice()`（返回 `{ip, resolving}`），供静音/OTA/DEV 复用设备发现结果。
  - `web_ui/frontend/src/components/ConsoleControls.tsx`（新增）：`ConsoleMuteButton`（lucide `Volume2/VolumeX`，5s 轮询 `/api/console/proxy/<ip>/api/mute` 双向同步）、`ConsoleOtaButton`（新标签页打开 `http://<ip>/update`）、`ConsoleDevToggle`（DEV 滑块，5s 轮询 `/api/devmode`，直接切换无确认弹窗，与内嵌 `/console` 页一致）。
  - `web_ui/frontend/src/services/api.ts`：新增 `getDonkeyUrl()`（`${protocol}//${hostname}:8090/`）。
  - `web_ui/frontend/src/components/EnterButtons.tsx`：新增 `DonkeyEntryLink`（lucide `Car` 图标 + 导航链接样式，参考 Kimi/DeepSeek 入口）。
  - `web_ui/frontend/src/components/Layout.tsx`：桌面右上角顺序 `VersionBadge → GitHubLink → ConsoleMuteButton → ThemeSwitcher → LanguageSwitcher → ConsoleOtaButton → ConsoleDevToggle`；桌面导航最左侧加入 `DonkeyEntryLink`；移动端第二行与汉堡菜单面板同步接入。
  - `web_ui/frontend/src/i18n/messages/common.ts`：新增 `common.enterButtons.donkey` / `donkeyTitle`（zh/en）；`web_ui/frontend/src/i18n/messages/console.ts`：新增 `console.muteAria` / `unmuteAria` / `otaOpen` / `unreachable`（zh/en）。
  - 测试同步：新增 `ConsoleControls.test.tsx`（6 项）；`EnterButtons.test.tsx` 补 Donkey 入口断言并 mock `getDonkeyUrl`；前端 `npm run check`（tsc）、vitest 相关 13 项、`npm run build` 全部通过。
  - 注：Firmware 侧同步移除 DC 头部 Donkey/OTA/DEV 并补静音轮询（v1.8.17），见 Firmware CHANGELOG。

## 2026-08-19 (63)

- fix(web-ui): Drive 页遥测曲线图改「有新帧才重绘 + 10fps 节流」，消除空闲 60fps 空转长任务——修复 #135 切换标签页卡顿（尤其 Drive → Drifter Console）
  - 根因：`TelemetryChart` 用 `requestAnimationFrame` 每帧无条件 `setRenderTick` 触发 chart.js 重绘（60fps），即使遥测为空也持续渲染。CPU 4x 实测 Drive 页空闲 10s 产生 25 个 longtask（峰值 ~1s），主线程被连续占满，点击其它标签时路由切换/卸载被饿死，表现为「点了很久才动、一动就瞬跳」。
  - `web_ui/frontend/src/components/drive/TelemetryChart.tsx`：移除 rAF 60fps 空转循环，改为「收到新遥测帧写入环形缓冲后，按 `CHART_REDRAW_INTERVAL_MS`（100ms，~10fps）节流 `setRenderTick`」；空闲无遥测时 chart.js 不再重绘。
  - 实测（CPU 4x）：Drive 页空闲 10s longtask 0（修复前 25 个、峰值 ~1s）；Drive → `/console` 路由切换 336ms、切换后 FlowPage 干净卸载、无 longtask；FlowPage 四段导航滑动仍精准落位（err 0/1/1/0）、每段仅 1 个 ~150-180ms longtask。
  - 测试同步：前端 vitest 20 文件 105 项通过、`tsc -b --noEmit`、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (62)

- fix(web-ui): Drive 页 Park 锁定移到驾驶模式选择器左侧
  - `web_ui/frontend/src/pages/DrivePage.tsx`：顶栏左组顺序由「驾驶模式 → 模型 → Park 锁定」改为「Park 锁定 → 驾驶模式 → 模型」，Park 锁定作为状态指示置于手动/半自动/全自动选择框左侧。
  - 测试同步：前端 vitest 20 文件 105 项通过、`tsc -b --noEmit`、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (61)

- fix(web-ui): Drive 流程节标题副标题垂直对齐并复刻 SectionCardTitle 悬停动画（Issue #233 补充）
  - `web_ui/frontend/src/pages/FlowPage.tsx`：`FlowSectionHeader` 的标题 `h2` 补 `leading-none`、副标题补 `leading-none`，消除小字相对标题偏高；副标题展开宽度 `max-w-[400px]` → `max-w-[300px]`，与 `SectionCardTitle` 动画参数完全一致（`transition-all duration-300 ease-in-out`）。

## 2026-08-19 (60)

- fix(launcher): Donkey 菜单页主题按钮去掉「跟随系统」显示器图标，改为深/浅两态互切（默认仍跟随浏览器，但不显示跟随系统状态）（Issue #230 最终形态）
  - 背景：上一步三态修复后，主题按钮为 跟随系统/浅色/深色 三态，其中「跟随系统」显示显示器（电脑）图标；用户要求默认仍跟随浏览器，但按钮只保留太阳/月亮两态、去掉电脑图标。
  - `donkeycar/launcher/server.py`：
    - 删除 `icon-monitor` 显示器 SVG 与相关 CSS；图标显隐改由生效主题 `html[data-theme]` 驱动（浅色显太阳、深色显月亮），不再写 `html[data-mode]`。
    - `toggleTheme()` 由三态循环改回深↔浅两态互切（按当前生效主题取反）；`renderThemeBtn()` 的 aria-label/title 改为仅 `theme.toggleLight` / `theme.toggleDark`。
    - `initTheme()` 仍保留 `system` 默认态（无存储时跟随浏览器 `prefers-color-scheme` 并监听变化）；首屏防闪烁脚本只写生效主题 `html[data-theme]`，v3 一次性清除旧残留逻辑不变。
    - i18n 删除 `theme.followSystem` / `theme.toggleSystem`（中英）。
  - `tests/test_launcher_theme_single_button.py`：由三态用例改为两态用例，断言移除 `icon-monitor`/`data-mode`/`followSystem`/`toggleSystem`，保留默认跟随浏览器与 v3 迁移覆盖。
  - 测试同步：launcher 相关测试 138 项全部通过；`python -m py_compile donkeycar/launcher/server.py` 通过。
  - 注：仅 Donkey launcher（8090）改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (59)

- fix(drive): Drive 页右侧抽屉改为贴视频画面右侧并 sticky 顶部对齐，滚动时留在顶部不跟走（Issue #232 第四次微调）
  - `web_ui/frontend/src/pages/DrivePage.tsx`：移除 `createPortal` 与基于 scroll/resize 的把手 `top` 动态对齐逻辑（`cameraWrapRef`/`drawerRef`/`handleRef` 及对应 `useEffect` 全部删除）；视频+遥测与抽屉改为 `flex` 左右并排（`lg:flex-row`），抽屉 `aside` 用 `lg:sticky lg:top-16` 锚定在视频右侧并随滚动保持在顶部，收起时面板 `w-0 border-0`、展开时 `w-[min(24rem,calc(100vw-3.5rem))]`；把手由 `absolute right-full` 改为并排独立按钮；面板四角圆角 `rounded-lg` 对齐视频边框（`border border-zinc-800`）。
  - 测试同步：前端 vitest 20 文件 105 项通过、`tsc -b --noEmit`、`npm run build` 通过。
  - 注：本次在 `Tony-issue232-joystick-drawer-v4` 功能分支（worktree `session-issue232-v4` 作业）完成。仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (58)

- fix(web-ui): Drive 流程节标题悬停副标题字号进一步调小到 `text-xs`（12px）
  - `web_ui/frontend/src/pages/FlowPage.tsx`：`FlowSectionHeader` 悬停副标题字号 `text-sm` → `text-xs`，让灰色小字更明显变小。

## 2026-08-19 (57)

- fix(web-ui): Drive 页顶栏右组顺序调整 + Park 锁定对齐模型选择器高度并缩短文案
  - `web_ui/frontend/src/pages/DrivePage.tsx`：右组由「录制按钮 → 已录制条数」改为「已录制条数 → 录制按钮」；Park 锁定徽标由小号 `px-2 py-0.5 rounded` 改为与 `ModelSelector` 同高同大小的 `px-3 py-1.5 rounded-lg border`（红色语义保留）。
  - `web_ui/frontend/src/i18n/messages/drive.ts`：`drive.recordedCount` 中文「已录制条数 {count}」→「已录制条数: {count}」；`drive.parkLocked` 中文「Park 锁定 · 油门被钳 0」→「Park 锁定」、英文「Park locked · throttle clamped to 0」→「Park locked」。
  - 测试同步：前端 vitest 20 文件 105 项通过、`tsc -b --noEmit`、`npm run build` 通过。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (56)

- fix(launcher): Donkey 菜单页「跟随系统」仍不生效——清除旧二选一遗留的显式主题，首次访问自动恢复跟随系统（Issue #230）
  - 根因：上一版三态修复后，用户浏览器里 8090 origin 的 `localStorage['donkeydrifter.ui.theme']` 仍残留旧二选一时期的显式 `light`/`dark`，页面加载时 `initTheme()` 优先读到显式值，`mode` 不再是 `system`，因此仍不跟随系统。
  - `donkeycar/launcher/server.py`：首屏防闪烁脚本加入一次性迁移——首次访问若 `donkeydrifter.ui.theme.v3 !== '1'`，先 `removeItem('donkeydrifter.ui.theme')` 清掉旧显式残留并写入 `donkeydrifter.ui.theme.v3='1'`，之后尊重用户后续手动选择（仅清一次旧残留）。
  - `tests/test_launcher_theme_single_button.py`：新增首屏迁移字符串断言，覆盖旧残留清除逻辑。
  - 测试同步：launcher 相关测试 138 项全部通过；`python -m py_compile donkeycar/launcher/server.py` 通过。
  - 注：仅 Donkey launcher（8090）改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (55)

- fix(web-ui): Drive 流程节标题悬停副标题字号回调为 `text-sm`，与全站副标题标准一致（Issue #233 补充）
  - `web_ui/frontend/src/pages/FlowPage.tsx`：`FlowSectionHeader` 的悬停副标题（如「驾驶并采集训练数据」）字号由 `text-base` 改为 `text-sm`，避免灰色小字过大。

## 2026-08-19 (54)

- fix(drive): Drive 页右侧抽屉把手真正贴屏幕最右并对齐摄像头画面顶部（Issue #232 第三次微调）
  - 根因：上层 section 的 `content-visibility:auto` 带来 paint containment，导致把手 `fixed right-0` 实际相对 section（摄像头画面右缘）而非 viewport 定位。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：整个抽屉（把手+面板）改用 `createPortal(..., document.body)` 挂到 body，脱离 section containment；新增 `cameraWrapRef`/`drawerRef`/`handleRef`，在 scroll/resize 时用 `requestAnimationFrame` 量出「摄像头画面顶部 - 抽屉顶部」并直接写把手 `style.top`（ref 直写 DOM，避免每次滚动触发整页重渲染、复现 #135 卡顿），使把手顶部与摄像头画面顶部水平对齐。
  - 测试同步：前端 vitest 20 文件 105 项通过、`tsc -b --noEmit`、`npm run build` 通过。
  - 注：本次在 `Tony-issue232-joystick-drawer-v3` 功能分支（worktree `session-issue232-v3` 作业）完成。仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (53)

- fix(web-ui): Drive 流程节标题副标题改为悬停淡入并放大字号，抽屉「虚拟摇杆」标题统一到 SectionCardTitle 标准（Issue #233 补充）
  - `web_ui/frontend/src/pages/FlowPage.tsx`：`FlowSectionHeader` 的副标题（如 Drive 的「驾驶并采集训练数据」）由常驻 `<p class="text-sm">` 改为 `group-hover` 悬停淡入的 `<span>`，与全站卡片小标题交互一致；字号由 `text-sm` 放大到 `text-base`。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：右侧抽屉内「虚拟摇杆」标题由手写 group-hover 结构改用 `SectionCardTitle` 组件，字号/字重/颜色统一到全站标准（16px / font-semibold / text-white）。
  - 测试同步：前端 vitest 20 文件 105 项通过、`npm run check`（tsc）、`npm run build` 通过。

## 2026-08-19 (52)

- fix(web-ui): Drive 页顶栏左右分组——左侧驾驶模式/模型/Park 锁定，右侧录制/已录制条数
  - `web_ui/frontend/src/pages/DrivePage.tsx`：顶部工具栏由单组改为左右两组，`justify-between` 分居两端——左组 `DriveModeSelector` → `ModelSelector` → `rc_park` 驻车锁定徽标；右组录制按钮 → 已录制条数。模型选择器按逻辑与驾驶模式同属「车怎么开」配置，故归入左组。
  - 测试同步：前端 vitest 20 文件 105 项通过、`tsc -b --noEmit`、`npm run build` 通过（新 `DrivePage-*.js` bundle）。
  - 注：仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (51)

- fix(launcher): Donkey 菜单页主题不随浏览器深浅色同步——主题按钮改为三态（跟随系统 / 浅色 / 深色），手动选择后可切回"跟随系统"（Issue #230 同源，扩展到 Donkey 启动页）
  - 背景：Donkey 菜单页（8090 launcher）与 DD web_ui 修复前存在同一问题：手动单击主题按钮后显式主题被持久化到 localStorage（`donkeydrifter.ui.theme`），从此不再跟随浏览器，且按钮是"深/浅"二选一、没有"跟随系统"入口。
  - `donkeycar/launcher/server.py`：
    - 首屏防闪烁脚本接受 `system`，并把模式与生效主题分别写到 `html[data-mode]` / `html[data-theme]`。
    - 主题按钮新增显示器图标（`icon-monitor`），图标显隐由 `html[data-mode]` 驱动：跟随系统显显示器、浅色显太阳、深色显月亮；移除按钮上的 `data-i18n-aria/title`，改由 `renderThemeBtn()` 统一生成动态 aria-label/title，并在语言切换后重新渲染。
    - `applyTheme()` 同时写 `data-mode` 与 `data-theme`；`toggleTheme()` 由"深↔浅"二选一改为三态循环 `跟随系统 → 浅色 → 深色 → 跟随系统`；`initTheme()` 仍按存储值（含 `system`）初始化并监听 `prefers-color-scheme` 变化。
    - i18n 新增 `theme.followSystem` / `theme.toggleSystem`（中英）。
  - `tests/test_launcher_theme_single_button.py`：由"二选一"用例改为三态用例，覆盖 `data-mode` 图标显隐、三态循环、首屏 `system` 解析与 `data-mode`/`data-theme` 写入等。
  - 测试同步：launcher 相关测试 138 项全部通过；`python -m py_compile donkeycar/launcher/server.py` 通过。
  - 注：本次在 `Tony-issue230-donkey-theme-sync` 功能分支（worktree 作业）完成，仅动 DD 的 launcher 页面，Firmware 无改动、无需 OTA。

## 2026-08-19 (50)

- feat(drive): Drive 页右侧抽屉的「虚拟摇杆」触发把手改为竖排文字，贴屏幕最右缘（Issue #232 微调）
  - `web_ui/frontend/src/pages/DrivePage.tsx`：把手按钮由横向 `flex items-center` 改为 `flex flex-col items-center`，展开/收起 chevron 置顶，`t('drive.virtualJoystick')` 用 `[writing-mode:vertical-rl]` 竖排、`tracking-wider leading-none` 收紧字距；按钮 `px-1.5 py-2 rounded-l-md` 收窄为竖向窄条，仍通过 `absolute right-full` 贴屏幕右缘。
  - 测试同步：前端 vitest 全量 20 文件 105 项通过、`tsc -b --noEmit`、`npm run build` 通过。
  - 注：本次在 `Tony-issue232-joystick-drawer-v2` 功能分支（worktree `session-issue232-v2` 作业）完成。仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (49)

- feat(console): Drifter Console 完全集成进 DonkeyDrifter——当前标签页内进入 + UI 重绘为 DD 风格（Issue #234）
  - 前置修正：DD 入口按钮文案 `DrifterConsole` → `Drifter Console`（`web_ui/frontend/src/i18n/messages/common.ts` zh/en 两处）。
  - 交互：`components/EnterButtons.tsx` 的 `DrifterConsoleEntryLink` 由「扫描车端 + `window.open` 新标签页打开车端原版 DC」改为 `<Link to="/console">` 当前标签页内进入 DD 内嵌页面；`App.tsx` 新增 `/console` 懒加载路由与空闲预取。
  - 内嵌页面 `pages/DrifterConsolePage.tsx`：以 DD 组件（Card/CardTitle/Button/Input + zinc/cyan 主题）实现设备发现/手动 IP、状态 key=value 表格、遥测卡片（模式/驻车/漂移/电压/油门/转向/陀螺仪/6 通道/舵机/电调/中点/漂移补偿/偏航/油门模式）、终端（web/serial 命令 + `/api/log` 轮询）、Wi-Fi STA（扫描/连接/状态）、OTA 固件上传（`/update` multipart）、开发模式/静音开关。
  - 新增 `services/console.ts`：车端 HTTP 经 DD 后端同源代理的访问层；新增 `i18n/messages/console.ts` 并注册到 `messages/index.ts`。
  - 后端新增 `routers/console.py`：`/api/console/proxy/{ip}/{path:path}` 通用反向代理（GET/POST/PUT/DELETE/PATCH，仅 IPv4、urllib 转发、原样透传状态码/Content-Type/body，含车端 4xx/5xx 透传）；`main.py` 注册 `/api/console`。
  - 测试同步：后端新增 `tests/test_console.py`（路由注册 / IPv4 校验 / 转发方法体头透传 3 项），后端 pytest 96 passed；前端 `EnterButtons.test.tsx` 断言 Drifter Console 改为 `/console` 路由链接，vitest 20 文件 104 项、`tsc -b --noEmit`、`npm run build` 全过。
  - 注：仅 DD 改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (48)

- feat(web-ui): 全站卡片小标题统一为「左侧图标 + 悬停灰色副标题」，抽出 `SectionCardTitle` 组件（Issue #233）
  - 需求：以 TM「录制视频库」小标题为基准，把 DD 所有页面的卡片小标题统一成同款 UI——左侧语义图标 + 悬停淡入灰色副标题；副标题文案补充进 i18n 中英双语。
  - 新增 `web_ui/frontend/src/components/ui/SectionCardTitle.tsx`：复用 `CardTitle`，统一渲染图标 + 标题 + 可选副标题（`group-hover` 淡入展开，`transition-all duration-300`），并支持 `children` 追加标题行内徽标。
  - 全站替换：
    - `TubLibrary.tsx`、`TubEditor.tsx`：基准实现改为复用 `SectionCardTitle`。
    - `TubLoader.tsx`、`ConfigLoader.tsx`、`SimulatorConfig.tsx`：补齐悬停副标题。
    - `PilotArenaPage.tsx`：当前数据 / 飞行员名称 / 图像处理 / Tub 绘图 / 变换前 / 变换后。
    - `CarConnectorPage.tsx`：连接配置 / 拉取 Tub / 推送 Pilots / 远程驾驶 / 任务日志。
    - `TrainerPage.tsx` 及 trainer 组件：训练配置 / 云端训练 / 本机训练 / 环境检测 / 训练状态 / 训练日志 / 已训练模型。
    - `DrivePage.tsx`：虚拟摇杆区块标题。
  - i18n 新增副标题文案（`arena.ts` / `common.ts` / `connector.ts` / `drive.ts` / `trainer.ts` / `tubnav.ts` 中英双语）。
  - 测试同步：`npm run check`（tsc）、`npm run build`、前端 vitest 20 文件 104 项全部通过。
  - 注：本次在 `Tony-issue233-section-card-titles` 功能分支（worktree `session-issue233` 作业）完成。仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (47)

- feat(drive): 虚拟摇杆折叠框改为贴屏幕最右的抽屉，收起时摄像头画面与遥测曲线占满整页宽度（Issue #232）
  - 需求：原布局是 `grid grid-cols-1 lg:grid-cols-3`，摄像头+遥测占左 2/3、控制面板占右 1/3；折叠只是隐藏右列内部内容、右列容器仍在，画面不会放大。改为右侧抽屉后，收起时控制面板完全退出布局流，画面占满整页宽度；展开时抽屉从屏幕最右往左滑出，画面同步缩小让位。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：
    - 移除三列 grid，摄像头+遥测改为单列全宽容器；抽屉展开时在 lg 屏加 `lg:mr-[24rem]` 让位（`transition-all` 与抽屉滑动同 duration/easing，画面随抽屉缩放）。
    - 控制面板改为 `fixed right-0` 右侧抽屉（`top-[143px] lg:top-16 h-[calc(100vh-143px)] lg:h-[calc(100vh-4rem)] z-40`，与左侧 SidePanel 的偏移/层级对齐），展开 `w-[min(24rem,calc(100vw-3.5rem))]`、收起 `w-0`；面板内容区 `overflow-y-auto` 可滚动。
    - 抽屉左缘新增常驻浮动触发把手（`absolute right-full`，`rounded-l-md`）：收起时贴屏幕右缘、展开时随抽屉左缘移动；`ChevronLeft`/`ChevronRight` 表示展开/收起方向，title 复用 `drive.expandJoystick`/`drive.collapseJoystick` 文案。
    - 输入源选择、摇杆、油门条、可编程按钮、参数面板、快捷键提示整体迁入抽屉；`joystickOpen` 状态与折叠语义保持不变。
  - 测试同步：前端 vitest 全量 20 文件 104 项通过、`tsc -b --noEmit`、`npm run build` 通过。
  - 注：本次在 `Tony-issue232-joystick-drawer` 功能分支（worktree `session-issue232` 作业）完成。仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (46)

- fix(web-ui): 页面主题不随浏览器深浅色同步——主题切换改为三态（浅色 / 深色 / 跟随系统），手动选择后可切回"跟随系统"（Issue #230）
  - 背景：首次访问默认跟随浏览器 `prefers-color-scheme`；但手动单击主题切换按钮后，显式主题被持久化到 localStorage（`donkeydrifter.ui.theme`），从此不再跟随浏览器；且切换按钮是"深/浅"二选一，用户没有入口选回"跟随系统"。
  - `web_ui/frontend/src/lib/theme.ts`：新增 `THEME_MODE_CHANGE_EVENT` 与 `useThemeMode()`（订阅当前模式 `system/light/dark`）；`setTheme()` 在持久化并应用后广播模式变化事件，供切换按钮反映三态。
  - `web_ui/frontend/src/components/ThemeSwitcher.tsx`：单按钮改为三态循环 `跟随系统 → 浅色 → 深色 → 跟随系统`；图标随模式显示 `Monitor` / `Sun` / `Moon`，aria-label 说明当前模式与下一次点击动作；挂载时仍按本地存储再应用一次，与 index.html 首屏内联脚本保持一致。
  - `web_ui/frontend/src/components/ThemeSwitcher.test.tsx`：由"静音式二选一"用例改为三态用例，覆盖默认跟随系统、循环三态、切回跟随系统后恢复同步、手动选择后不再跟随、持久化挂载与未知值回退等 10 项。
  - 测试同步：前端 vitest 全量 20 文件 106 项、`tsc -b --noEmit`、`npm run build` 全部通过。
  - 注：本次在 `Tony-issue230-theme-sync` 功能分支（worktree 作业）完成，仅动 DD 前端，Firmware 无改动、无需 OTA。

## 2026-08-19 (45)

- fix(web-ui): 把 Drive 页 Park 锁定徽标从顶栏控制组中间移到顶栏右侧，作为独立状态指示（不再夹在模式选择器与模型选择器之间）
  - `web_ui/frontend/src/pages/DrivePage.tsx`：移除顶栏左组里 `DriveModeSelector` 与 `ModelSelector` 之间的 Park 徽标；在顶栏右端（`justify-between` 空位）单独渲染，`rc_park === 1` 时显示红色「Park 锁定 · 油门被钳 0」，并加 `whitespace-nowrap` 防止窄屏换行。
  - 测试同步：前端 `npm run check`、`vitest`（20 文件 104 项）与 `npm run build` 全过，无新增测试文件。
  - 注：本次在 `Tony-park-btn-pos` 功能分支（worktree `park-btn-pos` 作业）完成；仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (44)

- fix(drive): 修正 complete 模板 DriveApiBridge 输出错位，让 car/mode_cmd 真正到达 ArdModeCmd（Issue #223 后续）
  - 根因：`DriveApiBridge.run_threaded` 返回 7 元组 `(angle, throttle, mode, recording, buttons, reconnect_simulator, car_mode_cmd)`，但 `donkeycar/templates/complete.py` 的输出列表只有 6 项、缺 `reconnect_simulator` 占位，导致第 6 个返回值 `reconnect_simulator` 错接到 `car/mode_cmd`、真正的车控模式命令（第 7 个返回值）被丢弃，「前端选模式 → 车端切模式」仍不生效。
  - `donkeycar/templates/complete.py`：DriveApiBridge outputs 由 6 项补为 7 项，按返回顺序加入 `reconnect_simulator`，使 `car/mode_cmd` 落到第 7 位。
  - 测试同步：`donkeycar/tests/test_template_drive_api_bridge.py` 新增 `test_complete_template_drive_api_bridge_outputs_include_car_mode_cmd` 断言输出顺序；`test_template_drive_api_bridge.py` + `test_actuator.py` 共 34 passed / 2 skipped。
  - 注：本次在 `Tony-issue223-fix-mode-outputs` 功能分支（worktree `issue223-mode-protocol` 作业）完成；仅 DD 模板改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (43)

- fix(web-ui): 导航切换改为快速平滑滑动并修复卡死后瞬跳与滚动锚定顶走（Issue #135 第六轮）
  - 需求：点导航标签后不是瞬跳，而是像快进的手动翻页一样滑到目标分区；此前实测点击后主线程冻结、动画被压成一次瞬跳，部分场景滚动被浏览器按回原地。
  - `web_ui/frontend/src/pages/FlowPage.tsx`：
    - 自定义 rAF 滑动替代 `scrollIntoView(smooth)`：时长按距离 250–750ms + easeOutCubic，快而有翻页感；动画进度按每帧限幅增量（≤48ms）推进，主线程被数据加载占住几秒导致 rAF 全程饿死时，恢复后不会一步跳到终点（"点了很久才动、一动就瞬跳"的根源）。
    - section 常驻 `overflow-anchor:none` + 滑动期间锁 html/body：目标/途经 section 因 content-visibility 展开产生布局位移时，Chrome 滚动锚定会把视口反向顶走或把程序化滚动按回原地（实测 drive→tub 被钉在顶部约 2s、pilot→drive 先反向跳 665px 再滑回）。
    - 落定后 250/750/1500ms 三次校验：目标被布局展开推走 >32px 时补一次短滑，保证精准落位。
    - 滑动期间冻结 scroll-spy、点击瞬间激活目标 section：途经分区不再反复启停视频流/WebRTC/WebSocket（此前 IO 翻转风暴的放大链）；手动滚动时 spy 提交去抖 100ms，消除边界抖动。
    - 用户滚轮/触摸/按键立即接管：取消滑动并作废在途会话与后续校验；prefers-reduced-motion 或首次深链直接落位。
  - 实测（Playwright CPU 4x 节流）：Drive↔TM↔Trainer↔PA 四段切换全部精准落位（err=0）、滑动 0.8–1.2s 单调平滑、每段仅 1 个 ~140–175ms longtask（第五轮基线单段 836ms 峰值且落位错 936–3182px）。
  - 测试同步：前端 vitest 20 文件 104 项全过、`tsc --noEmit` 与 `npm run build` 通过（无新增测试文件，滑动动画由 Playwright 实测脚本覆盖）。
  - 注：本次在 `Tony-issue135-nav-glide-round6` 功能分支（worktree `.worktrees/issue135-r6` 作业）完成。仅 DD 前端改动，Firmware 无改动、无需 OTA。

## 2026-08-19 (42)

- fix(drive): 车控模式下行协议对齐 Firmware#111——DD 下发 `MODE <m>` 而非 `C<m>`（Issue #223 端到端修复）
  - 根因：Issue #223 DD 侧 `Arduino.set_car_mode()` 写 `C<m>\n`，但 Firmware #111 的 `CommandDispatcher` 只解析 `MODE ` / `MODE:` 前缀，两端协议不一致，导致「前端选模式 → 车端切模式」这条链路永远不通。
  - `donkeycar/parts/actuator.py`：`set_car_mode()` 下发帧由 `C{mode}\n` 改为 `MODE {mode}\n`；docstring 与 `ArdModeCmd` 注释同步由 `C<m>` 改为 `MODE <m>`。
  - 测试同步：`donkeycar/tests/test_actuator.py` `test_arduino_set_car_mode_writes_cmd_frame` 断言由 `C2\n` 改为 `MODE 2\n`；本文件 28 passed / 2 skipped。
  - 注：本次在 `Tony-issue223-fix-mode-protocol` 功能分支（worktree 作业）完成，仅 DD 改动、Firmware 无改动、无需 OTA。

## 2026-08-19 (41)

- fix(launcher): 打开 Kimi Code Web 仍反复弹「选择语言/主题」欢迎页、置顶看似丢失——入口 URL 追加 `?kimi_onboarded=1` 跳过首次 onboarding 并写入 localStorage（Issue #168 后续）
  - 根因：KCW 前端把 onboarding 完成态存 `localStorage` 键 `kimi-web.onboarded`、按 origin 隔离；置顶也是 `kimi-web.pinned-sessions`、同样按 origin。前几轮已把 origin 稳定到 `tony007.local:58640`（固定端口 + mDNS 主机名），但迁移到新 origin 后，老 origin 的 onboarding 标记不会跟随——用户每次打开都停在欢迎页、且因不敢点「下一步」而永远进不去，误以为置顶又丢了。
  - 修复：`donkeycar/launcher/kimi_web.py` 新增 `_mark_onboarded(url)`，给入口 URL 追加 `?kimi_onboarded=1`（KCW 前端在 URL 带该参数时会把 `kimi-web.onboarded` 写进当前 origin 的 localStorage 并直接进主界面，之后不带该参数也不再弹欢迎页，等效于 KCW 自己的桌面→Web 迁移通道）；`launch_kimi_code_web` 三条成功返回路径（复用、冷启动、冷启动兜底复用）统一套用 `_mark_onboarded(_lan_url(url))`。
  - 测试同步：`tests/test_launcher_kimi_web.py` 新增 `TestMarkOnboarded`（追加参数保留 `#token=` 片段、保留已有 query、已有参数不去重）3 项；`TestLaunchKimiCodeWeb` 3 处 URL 断言更新为带 `?kimi_onboarded=1`。`test_launcher_kimi_web.py` + `test_launcher_dsh_web.py` 共 81 项通过。
  - 注：本次在 `Tony-kcw-onboarding-skip` 功能分支（worktree 作业）完成。仅 DD 改动，Firmware 无改动、无需 OTA。

## 2026-08-18 (40)

- fix(trainer): 训练器 SSH 凭据不再明文落盘/入库，my-PC 默认配置不再指向云服务器（Issue #219）
  - 根因：`train_my_pc.conf` 与 `train_online.conf` 明文存 `password = dkc@2026`，且 my-PC 配置直接复制云服务器 `haowenpi.com`/`ubuntu`；`donkeycar/management/train_online.py` 的 `_load_config()` 在配置缺失时硬编码生成云服务器默认值，是 my-PC 被污染的来源。
  - 后端：
    - `donkeycar/management/train_online.py`：`_load_config()` 默认 host/user/password 全部置空，去掉硬编码云服务器与密码；`connect_ssh(credentials=None)` 支持调用方传入会话内凭据（host/user/password/key_filename），空密码改走默认 SSH 密钥认证。
    - `web_ui/backend/web_online_trainer.py`、`web_ui/backend/trainer_engine.py`：新增 `ssh_credentials` 参数并透传到 `connect_ssh`，凭据仅内存传递、不落盘。
    - `web_ui/backend/routers/trainer.py`：新增 `SSHCredentials` 模型；`OnlineTrainRequest`/`MyPcTrainRequest` 增加 `ssh` 字段；`GET /trainer/config` 不再返回真实密码（固定 `""`）；`POST /trainer/config` 不再写 `password`；训练启动把 `ssh` 凭据透传给引擎。
  - 前端：
    - `store/useStore.ts`：`trainerOnlineConfig` 默认去掉明文密码与云服务器（改空）；`trainerMyPcConfig` 保持空默认。
    - `services/api.ts`：`TrainerConfig` 去掉 `password`、新增 `SSHCredentials`；`startOnlineTrain`/`startMyPcTrain` 增加 `ssh` 参数。
    - `hooks/useTrainingJob.ts`：非敏感项仍写 conf，密码改随训练请求 `ssh` 会话内传递。
    - `components/trainer/RemoteConfigForm.tsx`、`pages/TrainerPage.tsx`、`i18n/messages/trainer.ts`：my-PC 首次使用显示填写引导提示。
  - 配置与 gitignore：`web_ui/backend/train_online.conf` 移除密码并取消 git 跟踪；新增 `web_ui/backend/train_my_pc.conf.example` 空模板；`.gitignore` 忽略两个 `.conf`。
  - 测试同步：`tests/test_trainer_mypc.py` 新增/更新——ssh 凭据透传、config 不写密码、get 返回空密码、自动创建的默认配置不含明文密码；trainer 相关 17 项通过；前端 `tsc -b --noEmit` 通过。
  - 注：历史已提交过该明文密码（`train_online.conf`、前端构建产物、`train_online.py`、`useStore.ts` 等多处），建议轮换该密码；历史清洗（filter-repo + 强推）属破坏性/共享操作，需用户另行授权后处理，本次未动历史。本次在 `Tony-issue219-trainer-ssh-credentials` 分支（worktree 作业）完成。

## 2026-08-18 (39)

- feat(drive): Drive 模式选择器与车端模式双向同步，删除「固件模式」徽标并上移 Park 徽标（Issue #223）
  - 需求：驾驶页模式选择器（user/local_angle/local）与车端实际运行模式双向同步；删除顶部只读「固件模式」徽标，Park 锁定徽标上移到模式选择器旁。
  - 协议契约（下行 Pi→ESP32，仅定义契约 + 落地 DD 侧；Firmware 侧 #111 尚未实现，端到端打通需等 Firmware）：Serial1 `Arduino.ard_device` 写 `C<m>\n`，m∈{0,1,2}（0=手动/1=半自动/2=全自动），加 `ard_lock`，非法值忽略并 warning。
  - `donkeycar/parts/drive_api_bridge.py`：新增粘滞 `car_mode`（非 latch，避免主循环漏读单次值）；`_handle_message` 收到 `car_mode` 校验 0/1/2 后存值，非法值 warning；`run_threaded` 输出元组追加第 7 元素 `car/mode_cmd`。
  - `donkeycar/parts/actuator.py`：`Arduino` 新增 `set_car_mode()`（校验 0/1/2 + `ard_lock` + `write(f"C{mode}\n")`）；新增 `ArdModeCmd` Part（变化去重后调 `controller.set_car_mode`，缺 controller 抛 ValueError）。
  - `donkeycar/templates/complete.py`：`DriveApiBridge` outputs 追加 `'car/mode_cmd'`；`ARDUINO_CONTROLLER` 分支在 `ArdRc` 后新增 `ArdModeCmd` 接线（`inputs=['car/mode_cmd']`）。
  - `web_ui/backend/routers/drive.py`：`control_fields` 追加 `car_mode`，前端 `car_mode` 透传到 bridge。
  - 前端：`DriveModeSelector.tsx` 新增 `driveModeToRcMode`/`rcModeToDriveMode` 映射（user↔0、local_angle↔1、local↔2）；`DrivePage.tsx` 发送时附带 `car_mode`、新增 effect 按 `telemetry.rc_mode` 反向同步本地模式；删除「固件模式」徽标区、Park 徽标上移到模式选择器旁；`i18n/messages/drive.ts` 删除 `drive.firmwareMode`/`drive.unknownMode`（保留 `drive.parkLocked`）。
  - 测试同步：`test_drive_api_bridge.py` 输出元组断言更新为 7 元素；`test_drive_api_bridge_telemetry.py` 新增 car_mode 粘滞返回与非法值拒绝；`test_actuator.py` 新增 `set_car_mode` 写 `C2\n`/非法不写、`ArdModeCmd` 去重、缺 controller 抛错；`web_ui/backend/tests/test_drive.py` 新增 car_mode 转发；`DriveModeSelector.test.tsx` 新增两组映射测试。已验证：`test_drive_api_bridge.py`+`test_drive_api_bridge_telemetry.py`+`test_actuator.py` 共 83 passed/2 skipped、`test_drive.py`+`test_drive_telemetry_forward.py` 共 24 passed、`test_template_drive_api_bridge.py` 5 passed；前端 vitest 20 文件 102 passed、`npm run check`/`npm run build` 通过。
  - 注：本次在 `Tony-issue223-drive-mode-sync` 功能分支（worktree `.worktrees/issue223-drive-mode-sync` 作业）完成，PR 合并前 rebase 到最新 `origin/Tony` 解 CHANGELOG 冲突（条目重编号为 (39)）。Firmware 无改动，无需 OTA。

## 2026-08-18 (38)

- fix(web-ui): Drive 页摄像头偶发卡死在「正在连接摄像头...」——MJPEG 首帧无超时、WebRTC 收到 track 却无首帧、carOnline 门控竞态三处叠加（Issue #221）
  - 背景：进入 Drive 页后偶发既没切到 WebRTC、也没回退到 MJPEG，永远停在「正在连接摄像头...」，FPS 显示 `-`。三条失效路径：① MJPEG `<img src="/drive/video">` 只有 `onError` 才重试，后端无首帧时既不触发 `onLoad` 也不触发 `onError`，`status` 永远 `loading`；② WebRTC 在 `ontrack` 即置 `connected`、`videoReady` 要等 `onloadeddata`，首帧不解码时 `webRtcConnected=true` 会重置 MJPEG 回退计时器但 `webRtcVisible` 永为 false（黑屏 + 遮罩不消失）；③ `carOnline` 初值 `null` 被 `?? false` 压成 `false`，挂载时不启动 WebRTC，随后 `null→true` 又触发整体 `closePeer` 重启会话。
  - `web_ui/frontend/src/components/drive/VideoStream.tsx`：新增 `DRIVE_VIDEO_MJPEG_FIRST_FRAME_TIMEOUT_MS=5000`，MJPEG `loading` 首帧超时按 `onError` 同路重试；fallback 门控由 `webRtcConnected` 改为 `webRtcVisible`；`carOnline` 直接传 `null`（不再 `?? false`）。
  - `web_ui/frontend/src/hooks/useDriveWebRtcVideo.ts`：新增 `DRIVE_WEBRTC_VIDEO_READY_TIMEOUT_MS=8000` 与 `videoReadyTimeoutMs` 选项，`ontrack` 后首帧迟迟不解码则超时降级重试；`carOnline` 类型放宽为 `boolean | null`，挂载生命周期与 `carOnline` 门控拆成两个 effect（`shouldRunRef` 只在「应运行」状态翻转时 start/stop，挂载 cleanup 复位兼容 StrictMode）。
  - 测试同步：`VideoStream.test.tsx` 新增「MJPEG 首帧超时后自动重试」；`useDriveWebRtcVideo.test.tsx` `HookProbe` 透传 `videoReadyTimeoutMs` 并新增「收到 track 但首帧未就绪时超时降级」。前端 vitest 全量 20 文件 102 项、`tsc -b --noEmit` 通过；相关文件 eslint 0 error、无新增警告。
  - 注：本次在 `Tony-fix-issue-221` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (37)

- fix(tm): 摄像头画面与边框贴合——容器 aspect-ratio 跟随当前帧实际宽高比，消除画面与边框空隙（Issue #220）
  - 根因：TM 摄像头预览容器固定 `aspect-video`（16:9），而摄像头帧实际比例（如 640×240=8:3）不同，canvas `object-contain` 等比缩放后在边框内留黑边。
  - `web_ui/frontend/src/components/TubLibrary.tsx`：
    - 新增 `frameAspect` 状态，`draw()` 内用 `image.width / image.height` 更新；无图/加载态回落 16:9（`setFrameAspect(null)`）；
    - 容器由 `aspect-video` class 改为内联 `style={{ aspectRatio: frameAspect != null ? String(frameAspect) : '16 / 9' }}`，保留边框/圆角/FPS 角标样式；
    - 顺带移除未使用的 `fields` 变量（修复既有 lint 报错）。
  - 验证：`npm run check`（tsc）通过；`npm run lint` 0 error（7 个既有 warning 与本次无关）；`npm run test` 100/100 通过。Firmware 无改动、无需 OTA。
  - 注：本次在 `Tony-fix-issue-220-tm-camera-fit` 功能分支（worktree 作业）上完成，PR #224 合入 `Tony`。

## 2026-08-18 (36)

- feat(trainer): 「我这台电脑」训练模式开箱即用——新增一键环境检测（SSH/平台/Python/donkeycar）与 Windows/Mac 适配引导（Issue #218）
  - 背景：mypc 训练档此前只是"能用 SSH 的高级用法"，用户需自己开 SSH、装 donkeycar、手写 `train_my_pc.conf`，页面无引导；远端命令是 POSIX 风格（`tar`/`cd`/bash），Windows 原生 SSH 基本要 WSL，Mac 未适配，且连接/缺依赖时只看到训练 job 失败、无修复提示。
  - `web_ui/backend/mypc_probe.py`（新增）：轻量、无副作用的预检模块——SSH 连通性检测、`uname -s`/`wsl.exe` 平台探测（Linux/macOS/Windows + WSL）、Python 解释器探测（先验配置 `python_path`，再按 `python3`/`python`/`~/miniconda3/envs/donkey/bin/python`/`/opt/homebrew/bin/python3` 等常见顺序自动探测）、`donkeycar` 包与 `donkey` CLI 校验；每项返回 `ok/warn/fail` + 可操作修复提示，汇总 `suggestions`。
  - `web_ui/backend/routers/trainer.py`：新增 `POST /api/trainer/mypc/probe`（`asyncio.to_thread` 跑阻塞的 paramiko 探测），入参为 host/user/password/port/remote_dir_base/python_path。
  - `web_ui/frontend/src/services/api.ts`：新增 `MyPcProbeResult`/`MyPcProbeCheck` 类型与 `probeMyPc()`。
  - `web_ui/frontend/src/components/trainer/MyPcProbePanel.tsx`（新增）：mypc 表单下的「环境检测」面板——检测按钮、加载态、逐项结果（绿勾/黄警告/红叉/蓝信息 + 修复提示）、检测到的 Python 一键回填表单、修复建议列表。
  - `web_ui/frontend/src/pages/TrainerPage.tsx`：mypc 模式在 RemoteConfigForm 下接入 MyPcProbePanel，`onApplyPythonPath` 回填 `python_path`。
  - `web_ui/frontend/src/i18n/messages/trainer.ts`：zh/en 各新增 10 条检测相关词条（`myPcProbe*`）。
  - `docs/guide/web-drive-console-user-guide.md`：新增「本机训练（This Computer）」章节，说明首次使用准备（SSH 开启方式）、Windows（推荐 WSL）/macOS/Linux 平台支持与默认 Python 路径、连接失败/缺依赖时的排查指引。
  - 测试同步：新增 `web_ui/backend/tests/test_trainer_mypc_probe.py`（6 项：Linux 就绪、SSH 失败、macOS 自动探测、Windows 无 WSL、缺 donkeycar、配置 python_path 优先）；`test_trainer_mypc.py` 新增探测路由端点测试。后端 pytest 全量 89 项、前端 vitest 20 文件 100 项、`tsc -b --noEmit` 全部通过。
  - 注：本次在 worktree `.worktrees/issue218-trainer-mypc-ootb` 基于最新 `origin/Tony` 建功能分支 `Tony-issue218-trainer-mypc-ootb` 作业，主工作区在 `Tony-joystick-default-collapsed` 分支有并行会话未提交改动（`main.py` SPA 深链 + 未跟踪 `train_my_pc.conf`），全程未触碰。Firmware 无改动，无需 OTA。

## 2026-08-18 (35)

- feat(web-ui): 虚拟摇杆面板默认折叠——每次进入/刷新 Drive 页都折叠为「虚拟摇杆」标题一行
  - `web_ui/frontend/src/pages/DrivePage.tsx`：`joystickOpen` 初始状态由 `useState(true)` 改为 `useState(false)`；点击标题行展开/收起交互不变。
  - 验证：`npm run build`（含 `tsc -b`）通过；无 Firmware 改动、无需 OTA。
  - 注：主工作区有并行会话在制改动，本次在 worktree（`.worktrees/joystick-default-collapsed`）基于最新 `origin/Tony` 重做（cherry-pick 原提交），分支 `Tony-joystick-default-collapsed-v2`。

## 2026-08-18 (34)

- fix(launcher): KCW 入口 URL 用 mDNS 主机名后被 kimi 的 DNS-rebinding 栅栏 403 拦截——冷启动加 `--allowed-host` 放行入口 host，复用前重探入口 host 跳过未放行的旧实例（Issue #168 后续）
  - 根因：上一轮把 KCW 入口 URL 的 host 从 DHCP 局域网 IP 改为稳定 mDNS 主机名 `tony007.local` 以稳定 origin；但 `kimi web --host`（绑 0.0.0.0）只自动放行本机接口 IP（`192.168.3.57` 返回 200），mDNS 主机名是主机名而非接口 IP、不会被自动放行——浏览器用 `Host: tony007.local` 访问即被 40301（Invalid Host header）拦下。实测 `127.0.0.1:58640` 与 `192.168.3.57:58640` 均 200、`tony007.local:58640` 403 复现。
  - `donkeycar/launcher/kimi_web.py`：
    - `_mdns_hostname()` 主机名统一小写化（`hostname.split('.')[0].lower()`），让 URL / 浏览器 Host 头 / `--allowed-host` 三者保持同一小写形式（浏览器本就把 host 小写化放进 Host 头，origin 的 host 也按小写归一，不影响 localStorage 归属）；
    - 新增 `_allowed_host_values()` 收集入口 host（mDNS 主机名）与局域网 IP（mDNS 解析不到时的回退 host），去重；
    - `_spawn_and_capture()` 冷启动命令逐项追加 `--allowed-host <host>`，放行 mDNS 主机名与局域网 IP；
    - `_live_instance_url()` 复用本机实例、把 host 改写为入口 host 后，若入口 host 与已探测 host 不同则再对入口 host 探一次——老实例（没带 `--allowed-host`）对局域网 IP 通、对 mDNS 403，直接跳过而不是返回打不开的 URL。
  - 测试同步：`tests/test_launcher_kimi_web.py` 新增 `TestMdnsHostnameAndAllowedHosts`（小写化 + allowed-host 三种组合 4 项）、`test_entry_host_must_pass_rebind_gate`（复用重探跳过 403 实例）、`test_spawn_passes_mdns_and_lan_allowed_hosts`；更新 `test_spawn_success_captures_url_and_keeps_proc` 的启动命令断言。本文件 48 项、launcher 相关 86 项全部通过。
  - 验证：手动以 `kimi web --no-open --host --port 58646 --allowed-host tony007.local --allowed-host 192.168.3.57` 起测试实例，`curl http://tony007.local:58646/api/v1/meta`（小写）与 `http://TONY007.local:58646/...`（大写）均 200，修复生效。
  - 注：本次在 `Tony-kcw-allowed-host` 功能分支（worktree 作业）上完成。Firmware 无改动，无需 OTA。

## 2026-08-18 (33)

- fix(launcher): DSH 局域网 mDNS 主机名入口被 `/api` 通用信任栅栏 403——`--trusted-host` 同时声明局域网 IP 与 mDNS 主机名（Issue #164 追加）
  - 根因：`_lan_url()` 把 dsh web 入口 URL 的 host 从回环/局域网 IP 改写为 mDNS 主机名 `TONY007.local`（`_entry_host()` mDNS 优先，issue #168 稳定 origin 设计）；但 `--trusted-host` 之前只传了局域网 IP（`_lan_ip()`）。浏览器打开 `http://TONY007.local:<port>` 时 `Host` 头是 `tony007.local:<port>`，dsh-client-connection 的 `/api` 通用信任栅栏（`isTrustedApiRequest(req, trustedHosts)`，`trustedHosts` 由 `webserver.host=0.0.0.0` 自动派生的局域网 IP + `--trusted-host` 组成）里没有 `TONY007.local` → 所有 `/api/*` 请求 403（`host.listDirectory` 只是第一个暴露的症状，随后设置页/其他功能同样不可用）。
  - `donkeycar/launcher/dsh_web.py`：
    - 从 `kimi_web` 引入 `_mdns_hostname`；
    - `_spawn_and_capture()` 参数由 `lan_ip` 改为 `trusted_hosts`（authority 列表），逐项追加 `--trusted-host`；
    - `launch_dsh_web()` 新增 `mdns_fn` 测试钩子（默认 `_mdns_hostname`），构造 `trusted_hosts = [lan_ip, mdns]`（去空、去重）后传给 `_spawn_and_capture`；
    - 模块 docstring 的 `--trusted-host` 说明同步更新。
  - 测试同步：`tests/test_launcher_dsh_web.py` `_fake_lan_ip` fixture 默认 patch `dsh_web._mdns_hostname` 返回 None（隔离真实 mDNS 探测）；新增 `test_spawn_adds_mdns_host_to_trusted_host`（断言 `--trusted-host 192.168.3.10 --trusted-host TONY007.local`）；文件 30 项全部通过。
  - 验证：本地复现——仅 `--trusted-host 192.168.3.57` 时，`Host: TONY007.local` 的 `/api/host.listDirectory` 返回 403、`Host: 192.168.3.57` 返回 200；补上 `--trusted-host TONY007.local` 后 mDNS host 返回 200（修复生效）。
  - 注：本次在 `Tony-issue164-dsh-auto-enter-projects` 功能分支（worktree 作业）追加提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。此前 (32) 的 UUID polyfill 与本次 mDNS trusted-host 是 issue #164 的两个独立根因，均需线上 launcher 更新部署后生效。

## 2026-08-18 (32)

- fix(launcher): DSH 局域网非安全上下文 `crypto.randomUUID` 缺失导致连接永不就绪、不自动进 Projects——client.js 注入 UUID 兜底（Issue #164 收尾）
  - 根因：DSH 客户端 `dsh-client-connection/lib/client.js` 用 `crypto.randomUUID()` 铸造 RPC id（`AbstractApiClient.mintRpcId()`），但浏览器经局域网 IP（`http://192.168.3.x:<port>`）访问时处于非安全上下文，`crypto.randomUUID` 为 undefined，调用抛 `TypeError` → `ConnectionController.loop()` 的 `host.describe` 被 reject → 连接永远到不了 connected → `workspaces.startInitialSelection()` 不触发 → 停在"选择工作区"不自动进 Projects（回环 `127.0.0.1` 是 secure context，正常）。
  - `donkeycar/launcher/dsh_web.py`：
    - 新增 `_connection_client_path()`（定位 client.js，与 `_connection_index_path` 同布局）；
    - 新增 `_PATCH_UUID_OLD`/`_PATCH_UUID_NEW` 锚点与 `_patch_client_uuid_polyfill()`——启动前在 client.js 顶部 CommonJS 桩之后注入 `getRandomValues` 版 RFC4122 v4 UUID 兜底，幂等自愈（已打过的跳过、源码升级未命中旧锚点也跳过、失败只告警）；
    - `launch_dsh_web()` 冷启动前在 `_patch_privileged_methods()` 之后调用 `_patch_client_uuid_polyfill()`。
  - 测试同步：`tests/test_launcher_dsh_web.py` 新增 `TestPatchClientUuidPolyfill`（补丁注入/幂等/未命中跳过/缺包跳过/launch 调用时机 5 项），文件 29 项全部通过。
  - 验证：headless Chromium 打开 `http://192.168.3.57:36600/`，`isSecureContext=False` 但 `typeof crypto.randomUUID=function`（polyfill 生效）、页面自动进入 `projects`、不再显示"选择工作区"，console 无错误；回环 `127.0.0.1` 行为一致。
  - 注：本次在 `Tony-issue164-dsh-auto-enter-projects` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。此前错误的 `sec-fetch-site` 放宽补丁已一并删除（实测浏览器发 WebSocket 不带该头，与真实根因无关）。

## 2026-08-18 (31)

- feat(launcher): D 启动菜单 0 号「Drifter Console」移到 7 号、删 0 号位，6 号改名 DonkeyDrifter（小字「打开 DonkeyDrifter」）
  - 需求：D 启动页菜单中 0 号「Drifter Console」（打开 DC）移到 7 号位置、删掉 0 号位；6 号「Donkey Drifter」改名「DonkeyDrifter」，小字（desc）改为「打开 DonkeyDrifter」。
  - `donkeycar/launcher/server.py`（MENU_HTML）：
    - `menuItems`：删除 0 号「Drifter Console」条目；6 号 name「Donkey Drifter」→「DonkeyDrifter」、descZh/descEn「打开 DonkeyDrifter」/「Open DonkeyDrifter」；7 号由占位行改为「Drifter Console」（cat drive、favorite true）；编号 1-12。
    - `selectItem()`：删除 `no === 0 → openDrifterConsole()` 分支，新增 `no === 7 → openDrifterConsole()`；移除占位行轻提示分支。
    - `renderMenu()`：移除占位行渲染分支与 `.menuItem.placeholder` CSS（占位概念随 7 号恢复为真实 DC 项而移除）。
    - 键盘：数字键 `0` 不再触发 `selectItem(0)`（0 号位已删）；`2-9` 仍直选对应项，`1`+`0/1/2` 仍组合选 10/11/12。
    - 帮助文案：`数字键 0-12：选择对应菜单项（7 号已并入 6 号）` → `数字键 1-12：选择对应菜单项`（zh/en 同步）。
  - 测试同步：`tests/test_launcher_menu_actions.py` 删除 `test_menu_6_7_merged_placeholder`，新增 `test_menu_6_renamed_and_dc_moved_to_7`；模块 docstring 与注释同步。launcher 相关测试 155 项全部通过，MENU_HTML 内嵌 JS `node --check` 通过。
  - 注：本次在 `Tony-menu-reorder-dc-7` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (30)

- perf(web-ui): 流程页导航切换仍卡顿——四个 section 常驻挂载导致整页每次滚动都重算/重绘 + 父组件重渲染连坐所有子页面，加 `content-visibility` 与 `React.memo` 隔离（Issue #135 五轮）
  - 背景：#201/#204 已把 Drive 视频流/WS/遥测图/PA 循环按主导 section 门控，但四个 section（Drive/TM/Trainer/PA）仍常驻挂载在同一个滚动页里，且 `FlowPage` 的 `inView` 每次变化会触发父组件重渲染、默认连带所有子页面一起重渲染——切导航平滑滚动时既有视口外 section 的布局/绘制开销，又有 TM/Trainer 等重页面的无效重渲染。Playwright CPU 4x 实测：切换 PA→Drive 单次 longtask 峰值 836ms。
  - `web_ui/frontend/src/pages/FlowPage.tsx`：新增 `SECTION_STYLE`（`content-visibility: auto` + `contain-intrinsic-size: auto 640px`）应用到四个 `<section>`——DOM 与组件状态保留（保住 #135 常驻保活），但浏览器跳过视口外 section 的布局/绘制，只按占位尺寸撑开滚动高度。
  - `web_ui/frontend/src/pages/TubManagerPage.tsx` / `TrainerPage.tsx` / `DrivePage.tsx` / `PilotArenaPage.tsx`：四个页面组件用 `React.memo` 包裹（无 props 的 TM/Trainer 永不随父组件重渲染；带 `active` 的 Drive/PA 仅在 `active` 变化时重渲染）。
  - 效果：Playwright CPU 4x 实测导航切换 longtask 峰值从 836ms 降至约 170ms；视频流滚出卸载回归通过（Drive 滚到 TM 后 `img[src*=drive/video]`/`video` 卸载、占位符出现）；nav href 正确（`#/drive`/`#/tub`/`#/trainer`/`#/pilot`）。
  - 测试同步：前端 vitest 全量 20 文件 100 项、`tsc -b --noEmit`、`npm run build` 全部通过。
  - 注：本次在 `Tony-issue135-nav-lag-round5` 功能分支（worktree 作业，基于最新 origin/Tony）完成，仅动前端。Firmware 无改动，无需 OTA。已部署到 8000（从该 worktree 起后端），用户需硬刷新浏览器。

## 2026-08-18 (29)

- fix(web-ui): 修复 DD 前端深链（`/connector`、`/drive` 等）刷新/直达返回 404——根静态文件挂载改为 SPA fallback 兜底
  - 根因：`main.py` 用 `app.mount("/", StaticFiles(html=True))` 服务根目录静态文件，它注册在 `@app.get("/{full_path:path}")` SPA fallback 之前，拦截了所有路径——前端深链（无扩展名、非真实文件）被 StaticFiles 判为 404，fallback 永远轮不到，导致用户在 `/connector` 等页面刷新或直接访问时得到 `{"detail":"Not Found"}`（Issue #177 收尾时用户反馈"看不到改动/无法连接服务器"暴露）。
  - `web_ui/backend/main.py`：去掉根目录 `StaticFiles` 挂载，`spa_fallback` 改为——① 真实存在的根目录静态文件（favicon、robots.txt 等）经 `realpath` 越界校验后直接 `FileResponse`；② 不存在的 API 路径（`api`/`api/*`）保持 404；③ 其余一律回退到 `index.html` 交给前端路由。`/assets/*` 仍由独立 mount 服务，不受影响。
  - 测试同步：后端 pytest 全量 82 项通过；手动验证 `/connector`、`/drive`、`/` 返回 200、`/assets/*.js` 200、`/api/provisioning/status` 404、`/api/connector/config` 200。

## 2026-08-18 (28)

- fix(trainer): Trainer 三档标签改为「本机 / 车载电脑 / 云端」，让「本机」明确指用户自己的电脑、「车载电脑」指跑 DD 后端的 Linux 机器（Issue #170 收尾）
  - 背景：上一轮「我的电脑 / Linux 电脑」仍不够直观——「我的电脑」与「本机」语义易混，且「Linux 电脑」过于技术化、普通用户难以和"本机"区分。改为「本机」（用户浏览器/SSH 客户端所在机）、「车载电脑」（跑 DD 后端的机器）、「云端」（远端服务器）三档。
  - `web_ui/frontend/src/i18n/messages/trainer.ts`：`tabMyPc`「我的电脑」→「本机」、`tabLocal`「Linux 电脑」→「车载电脑」、`startMyPcTraining`→「在本机上训练」、`startLocalTraining`→「在车载电脑上训练」、`myPcTraining`→「本机训练」；en 同步 `This Computer / Car Computer / Train on This Computer / Train on Car Computer / This Computer Training`（`tabCloud` 云端 / Cloud 不变）。
  - `web_ui/frontend/src/components/trainer/ModeTabs.test.tsx`：三档渲染与点击断言同步新短名。
  - 测试同步：前端 vitest `ModeTabs.test.tsx` 3 项通过、`tsc -b --noEmit` 通过。
  - 注：本次改动在 `Tony-issue170-trainer-mode-naming3` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (27)

- fix(trainer): Trainer 三档标签由「客户端/本机/云端」改为「我的电脑 / Linux 电脑 / 云端」，消除用户对前后两档语义的混淆（Issue #170 收尾）
  - 背景：上一轮「客户端/本机」对普通用户不够直观——「本机」在用户自己电脑上操作时易被误读为"我的电脑"，与「客户端」难以区分。
  - `web_ui/frontend/src/i18n/messages/trainer.ts`：`tabMyPc`「客户端」→「我的电脑」、`tabLocal`「本机」→「Linux 电脑」、`startMyPcTraining`→「在我的电脑上训练」、`startLocalTraining`→「在 Linux 电脑上训练」、`startCloudTraining`→「在云端训练」、`myPcTraining`→「我的电脑训练」；en 同步 `My Computer / Linux PC / Train on My Computer / Train on This Linux PC / Train on Cloud / My Computer Training`（`tabCloud` 云端 / Cloud 不变）。
  - `web_ui/frontend/src/components/trainer/ModeTabs.test.tsx`：三档渲染与点击断言同步新短名。
  - 测试同步：前端 vitest `ModeTabs.test.tsx` 3 项通过、`tsc -b --noEmit` 通过。
  - 注：本次改动在 `Tony-issue170-trainer-mode-naming2` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (26)

- feat(web-ui): DeepSeek Harness 入口同样改为导航链接样式，放在 Kimi Code Web 右侧（Issue #175 延续）
  - `web_ui/frontend/src/components/EnterButtons.tsx`：删除已无引用的 `DshButton` 胶囊组件与 `useResolvedTheme` 导入，DeepSeek Harness 统一走 `DshEntryLink` 导航链接样式。
  - `web_ui/frontend/src/components/Layout.tsx`：桌面导航行末尾 Kimi Code Web 右侧新增 `DshEntryLink`；右上角胶囊区移除 `DshButton`（现在只保留版本号/GitHub/主题/语言切换）；手机端汉堡菜单高级入口分组顺序不变（Drift Console / Kimi Code Web / DeepSeek Harness）。
  - 测试同步：`EnterButtons.test.tsx` 删除 DSH 胶囊样式断言，DSH 成功/失败路径测试由 `DshButton` 迁至 `DshEntryLink`；vitest 全量 20 文件 99 项、`tsc -b --noEmit` 全部通过。
  - 注：Firmware 无改动，无需 OTA。

## 2026-08-18 (25)

- fix(web-ui): 流程页滚动卡顿收尾补刀——遥测图 60fps 空转、PA 播放循环、Drive UI 50ms 同步与同导航项重复点击滚动（#178 后续）
  - 背景：#201 已把 Drive 的视频流/WebSocket 按主导 section 门控（滚走即断），但仍有几处后台空转：`TelemetryChart` 的 `requestAnimationFrame` 循环在 section 滚走后仍每帧 `setRenderTick` 重绘（无数据也空转 60fps）；`PilotArenaPage` 播放时滚走仍持续 rAF 推帧与预测轮询；`DrivePage` 的 50ms UI 同步 `setInterval` 未随 `active` 停表；且顶部导航点「与当前 path 相同的项」时 `location.pathname` 不变、滚动 effect 不触发，用户点后无反应。
  - `web_ui/frontend/src/components/drive/TelemetryChart.tsx`：新增 `active` prop（默认 true）——`active=false` 时跳过遥测写缓冲与 rAF 重绘循环，滚回后自动恢复。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：50ms UI 同步 `useEffect` 加 `if (!active) return` 并补 `active` 依赖；`<TelemetryChart>` 传入 `active={active}`。
  - `web_ui/frontend/src/pages/PilotArenaPage.tsx`：播放 rAF 循环与评测调度 `useEffect` 加 `!active` 早退并补 `active` 依赖（播放中滚走即冻结，滚回续播）。
  - `web_ui/frontend/src/pages/FlowPage.tsx`：滚动 effect 依赖从 `location.pathname` 改为 `pathname + location.key`——点同一导航项（path 不变但 location.key 变）也能再次 `scrollIntoView`，修复"点了没反应"。
  - 测试同步：前端 vitest 全量 20 文件 101 项、`tsc -b --noEmit`、`npm run build` 全部通过；eslint 改动文件 0 警告。Playwright headless 实测：点 Trainer 后 Drive 区 video/img 卸载、点同 path 导航项可再次滚回目标 section。
  - 注：本次在 `Tony-issue178-flow-perf` 分支完成，基于已合入 Tony 的 #201 增量修改，仅动前端。无 Firmware 改动，无需 OTA。

## 2026-08-18 (24)

- fix(launcher): DC 点击进入 DD 报"无法连接服务器"——web 进程启动失败仍报 launched 并重定向死端口，改为报错 + 跳转页就绪轮询（用户口述报障，journalctl 实锤）
  - 背景：`donkey web` 冷启动时前端生产构建失败（源码在制改动致 `tsc -b && vite build` 报错）直接退出，但 `_wait_for_web_ready` 对"进程提前退出"只带 warning 不报错，`_launch_drive` 仍返回 `launched` + 兜底前端端口 5188；而生产模式（bundled web ui，#135）前端由后端 8000 端口托管、5188 从不监听——跳转页拿到 URL 立即重定向，Safari 报"无法连接服务器"。三个叠加缺陷：进程死了仍报 launched / 兜底端口在生产模式必死 / 跳转页无就绪轮询（2026-08-12 加过的轮询被 c613ce73 菜单页重写吞掉）。
  - `donkeycar/launcher/server.py` `_launch_drive`：`_wait_for_web_ready` 返回 warning 时区分两种情况——web 进程已退出（`poll()` 非 None）必然失败，改返回 `status:"error"` 并附具体原因与日志查看命令，不再起车进程、不写 PID 文件；进程仍在但超时、且登记未出现时，生产模式兜底前端端口从入参 5188 修正为后端端口（开发模式 vite 确实监听 5188，保持不变）。
  - `donkeycar/launcher/server.py` `LAUNCH_DRIVE_HTML`：跳转前加就绪轮询（30 次 × 1s，`mode:'no-cors'` fetch 探测目标可连，复用菜单页 launchDrive 既有模式），就绪才重定向；超时不通则停下显示"Web UI 未就绪，未跳转（可稍后重试）"并透出 warning，不盲目跳死端口；i18n 补 `waiting`/`notready` 中英词条。
  - 测试同步：`tests/test_launcher_drive_launch.py` 新增 3 项——web 进程提前退出报 error 且不起车进程不写 PID、生产模式超时前端端口修正为后端端口、开发模式超时保持入参端口；`tests/test_launcher_language_autodetect.py` 跳转页双语断言同步（新词条、3 处 failed 文案、轮询语句）。本文件 12 项全部通过，launcher/webui 相关 135 passed（terminal 2 项失败为 origin/Tony 基线遗留，与本次无关）；另起临时 launcher 实例实测 `/launch/drive` 页面含轮询逻辑与双语提示。
  - 注：本次改动在 `Tony-fix-launch-dead-port` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`（合并时 CHANGELOG 与多条会话条目解冲突，最终重编号为 (24)）。Firmware 无改动，无需 OTA。

## 2026-08-18 (23)

- fix(launcher): DC 上位机终端"放一会儿仍被断开"根因修复——移除应用层 PING/PONG 判死，改用内核 TCP keepalive 保活与死链检测（Issue #173 后续）
  - 背景：#173 首轮把 PTY 会话与 WS 连接解耦、断线宽限期 + sid 重连 + 自动退避重连，但服务端仍保留 #151 的"60s 无 PONG 判死"心跳——浏览器标签页冻结 / 手机锁屏时应用层 PONG 会停，服务端照样在 60s 后主动断开，用户视角"放一会儿仍断"依旧存在。
  - `donkeycar/launcher/terminal.py`：删除 `_heartbeat_loop` 应用层心跳线程与 `_PING_INTERVAL`/`_PONG_TIMEOUT` 判死逻辑；新增 `_enable_tcp_keepalive`，在 WS 连接套接字上启用内核 TCP keepalive（`SO_KEEPALIVE` + Linux `TCP_KEEPIDLE=30`/`TCP_KEEPINTVL=15`/`TCP_KEEPCNT=3`）。keepalive 探测由内核发送、对端内核 ACK，与应用层无关：冻结/锁屏的浏览器内核照常 ACK，不再被误判断线；探测包同时刷新 NAT 表项防空闲断链；只有真正的死链才会在约 75s 后让 socket 报错触发会话 detach。主读循环仍响应客户端 PING（回 PONG），只是不再主动发 PING。
  - `donkeycar/launcher/terminal_static/terminal.html`：注释同步（断线原因改为"任何原因，含 TCP keepalive 判死"）。
  - `donkeycar/tests/test_launcher_terminal.py`：删除"服务端心跳 PING"与"空闲超时断开"两个 #151 用例，新增 `test_terminal_ws_idle_keeps_connection`（空闲不判死断连）与 `test_enable_tcp_keepalive_sets_socket_options`（keepalive 参数落地）。
  - `tests/test_launcher_terminal.py`：静态断言从旧的 `lost`/`failed`/`reconnect` 文案改为新的"断线自动退避重连 + session sid 接回 + 清屏"断言。
  - 测试同步：两个 terminal 测试文件 26 项通过。

## 2026-08-18 (22)

- fix(launcher): KCW 入口 URL host 用 mDNS 主机名，置顶/模式/语言主题不再随 DHCP 换 IP 被清空（Issue #168 后续）
  - 背景：Issue #168 已固定端口 58640、缺省 cwd 落到 Projects 工作区，但浏览器把 KCW 的置顶等 UI 偏好存在 localStorage、按 origin（协议+host+端口）隔离；host 用上位机 DHCP 局域网 IP（近期从 .41 漂到 .57）时，IP 一变 origin 就变，置顶聊天仍会"全部消失"。
  - `donkeycar/launcher/kimi_web.py`：
    - 新增 `_mdns_hostname()`（`socket.gethostname()` 拼 ``<hostname>.local``，仅当 mDNS 解析到本机局域网 IP 时才采用）与 `_entry_host()`（mDNS 优先、局域网 IP 回退）。
    - `_lan_url()`：回环/通配 host 与本机局域网 IP 统一改写为稳定入口 host，mDNS 可用时入口 URL 的 host 稳定、不随 IP 漂移。
    - `_live_instance_url()`：本机实例（登记回环/通配或本机 IP）组装入口 URL 时改用 `_entry_host()`；其它远程 host 不受影响。
    - 模块 docstring 更新为"三处约束"（cwd 校验 / 固定端口 / mDNS host）。
  - 测试同步：`tests/test_launcher_kimi_web.py` 新增 4 项 mDNS 优先与 foreign host 不误改断言，autouse fixture 默认钉 `_mdns_hostname` 为 None 保持既有断言稳定；本文件 42 passed、launcher 相关 116 passed。
  - 注：本次改动在 `Tony-kcw-origin-stable` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (21)

- fix(web-ui): 修复流程页滚出 Drive 后视频流/WebSocket 仍在后台运行，拖慢整页切换（Issue #135 收尾）+ 后端静态资源缓存头
  - 根因：#178 把 Drive/TM/Trainer/PA 合并为纵向滚动大页后，Drive 区的视频流与 WebSocket 未按 section 可见性门控——用户滚到 TM/Trainer/PA 后，Drive 的 MJPEG 图片流、WebRTC 视频、车端 WebSocket 遥测仍在后台持续收发与 setState 重渲染，持续占主线程，导致无论切到哪个标签都卡顿（#135 用户仍报"非常卡顿"）。
  - `web_ui/frontend/src/pages/FlowPage.tsx`：滚动 spy 的 `inView` 判定从「`isIntersecting` 有任何交集即视为可见」改为「可见比例最大的主导 section 才算活跃」——原先 section 之间有 `space-y` 间距与 `scroll-mt` 滚动边距，滚走后仍留 32px 交集使 `active` 永不翻 false；改为主导 section 后，滚到 TM 时 Drive 的 `active` 正确变为 false。
  - `web_ui/frontend/src/hooks/useDriveWebsocket.ts`：新增 `enabled` 选项（默认 true）；`enabled=false` 时主动断开 WebSocket、清定时器、`setConnected(false)`、`setCarState.online=false`，不再后台收发；重新 `enabled=true` 时重连。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：`useDriveWebsocket({ enabled: active })`；`useGamepadDrive` / `useGyroDrive` 的 `enabled` 追加 `active &&`；`<VideoStream>` 改为 `active` 条件渲染（滚走卸载视频组件、停止 MJPEG/WebRTC 与 1s 统计轮询），非活跃时渲染同宽高比占位符避免布局跳动。
  - `web_ui/backend/main.py`：新增 `apply_cache_headers` 与 `cache_control_middleware`——`/assets/*` 带内容哈希的静态资源返回 `Cache-Control: public, max-age=31536000, immutable`；`text/html`（index.html/SPA fallback）返回 `Cache-Control: no-cache`，避免浏览器启发式缓存旧 index.html 导致"前端已修复但仍在跑旧 bundle"（#135 用户侧反复卡顿的重要诱因）。
  - 测试同步：新增 `web_ui/backend/tests/test_cache_headers.py`（3 项：assets immutable / html no-cache / API 不受影响）；`web_ui/frontend/src/hooks/useDriveWebsocket.test.tsx` 新增 `enabled=false 不建立连接`（1 项）。后端 pytest 全量 82 项、前端 vitest 全量 20 文件 102 项、`tsc -b --noEmit`、`npm run build` 全部通过。
  - 实测（8021 测试实例 + chrome-headless-shell）：滚到 TM 后 Drive 区 `img[src*=drive/video]`/`video` 均卸载、占位符出现（修复前仍挂载）；`useDriveWebsocket` enabled 门控单测确认不建连。无 Firmware 改动，无需 OTA。

## 2026-08-18 (20)

- fix(web-ui): DD 驾驶页虚拟摇杆折叠后面板真正缩小——消除 grid 拉伸导致的"内容只剩一行但框未变小"
  - 背景：控制面板在 `grid grid-cols-1 lg:grid-cols-3` 中作为第三列 grid item，默认 `align-self: stretch` 被拉伸到与左侧摄像头区（视频流 + 遥测图，较高）同高；折叠后内容虽只剩标题一行，但灰色面板框仍保持满高，下方"空出来"的区域实际是面板内部空白，视觉上"没变小"。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：控制区外层 div 加 `self-start`，让面板高度随内容收缩——折叠后只剩标题一行、下方真正空出；展开时顶部对齐、高度由内容决定。
  - 测试同步：前端 vitest 全量 100 项通过，`tsc -b --noEmit` 通过。

## 2026-08-18 (19)

- fix(trainer): Trainer 训练位置三档文案由口语化长名改为正式短名——客户端 / 本机 / 云端（Issue #170 收尾微调）
  - `web_ui/frontend/src/i18n/messages/trainer.ts`：`tabMyPc`「我这台电脑」→「客户端」、`tabLocal`「当前这台 Linux 电脑」→「本机」、`startMyPcTraining`「开始训练（我这台电脑）」→「开始客户端训练」、`startLocalTraining`「开始本地训练」→「开始本机训练」、`myPcTraining`「在我这台电脑上训练」→「客户端训练」；en 同步 `Client / Local / Start Client Training / Start Local Training / Client Training`（`tabCloud` 云端 / Cloud 不变）。
  - `web_ui/frontend/src/components/trainer/ModeTabs.test.tsx`：三档文案断言同步为新短名。
  - 测试同步：前端 vitest `ModeTabs.test.tsx` 3 项通过、`tsc -b --noEmit` 通过。
  - 注：本次改动在 `Tony-issue170-trainer-mode-naming` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (18)

- feat(web-ui): 顶栏高级入口改为导航链接样式——Drift Console 移到品牌右侧/Drive 左侧、Kimi Code Web 移到 Car Connector 右侧，弱化处理一眼可辨为高级选项（Issue #175）
  - `web_ui/frontend/src/components/EnterButtons.tsx`：重写——原 `EnterButtons` 三合一胶囊组件拆分为 `DrifterConsoleEntryLink` / `KimiCodeWebEntryLink` / `DshEntryLink`（导航链接样式：`text-xs` 小字号 + `text-zinc-500` 淡色 + 图标 `SquareTerminal`/`Sparkles`/`FlaskConical`，无胶囊外壳、不做路由激活态）与 `DshButton`（DeepSeek Harness 胶囊按钮，保留在顶栏右侧，样式不变）；点击逻辑（扫描车端/launcher 启动/空白页句柄防弹窗拦截）与 loading 态原样保留，公共启动流程抽为 `useLauncherEntry` hook，console 扫描抽为 `useDrifterConsoleEntry` hook。
  - `web_ui/frontend/src/components/Layout.tsx`：桌面导航行顺序改为 品牌 → DrifterConsole → Drive → TM → Trainer → PA → CC → KimiCodeWeb，右侧区只留 `DshButton`；手机端原第二行 EnterButtons 删除，三个高级入口以分隔线分组的弱化链接收进汉堡菜单。
  - `web_ui/frontend/src/App.test.tsx`：`services/api` mock 补 `discoverConnectorConsoles` / `launchKimiCodeWeb` / `launchDsh`（新入口组件渲染期取这些引用，mock 缺导出会抛错进 ErrorBoundary）。
  - 测试同步：`EnterButtons.test.tsx` 重写为按新组件覆盖（弱化样式断言、DSH 胶囊样式断言、成功/失败路径 8 项）；vitest 全量 19 文件 96 项、`tsc -b --noEmit`、`npm run build` 全部通过。
  - 注：本次改动在 `Tony-issue175-webui-nav-links` 功能分支（独立 worktree）上完成。Firmware 无改动，无需 OTA。

## 2026-08-18 (17)

- fix(web-ui): DD 驾驶页虚拟摇杆折叠后只留标题一行——选择框随折叠一起收起，展开时恢复
  - 背景：上一轮把输入源选择框挪进摇杆面板标题栏并让摇杆区可折叠后，折叠态标题栏右侧仍常驻输入源选择框，且面板内「可编程按键 / 控制参数 / 快捷键说明」也仍在显示，折叠后并非用户期望的"只剩一行"。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：标题栏的 `InputSourceSelector` 包进 `joystickOpen` 条件渲染（展开才显示）；原先只包摇杆圆盘区的条件渲染扩大为包住整个面板主体（竖向油门条 + 摇杆圆盘 + 控制参数条 + 可编程按键 + 参数面板 + 快捷键说明），折叠态只保留"虚拟摇杆"标题 + 展开/收起箭头一行；标题栏 `mb-4` 改为折叠时 `mb-0`，避免底部留白。
  - 测试同步：前端 vitest 全量 19 文件 98 项通过，`tsc -b --noEmit` 通过；Playwright 实测折叠态面板文本仅剩「虚拟摇杆」，展开态选择框/油门/控制参数/快捷键说明全部恢复。

## 2026-08-18 (16)

- feat(trainer): Trainer 页训练位置从「本地/云端」两档扩为三档——我这台电脑 / 当前这台 Linux 电脑 / 云端（Issue #170）
  - 背景：旧「本地」档 = 在 DD 后端所在 Linux 机器上训练；旧「云端」档 = SSH 到 `train_online.conf` 配置的远端训练；缺少"在用户自己这台电脑（SSH 客户端/浏览器所在机）上训练"的选项。方案：「我这台电脑」档复用云端 SSH 管线，但方向相反——后端 SSH 回访用户电脑，用独立配置 `train_my_pc.conf`。
  - `web_ui/frontend/src/components/trainer/ModeTabs.tsx`：两档扩为三档（`mypc` 我这台电脑 / `local` 当前这台 Linux 电脑 / `online` 云端），导出 `TrainerMode` 类型。
  - `web_ui/backend/routers/trainer.py`：新增 `MyPcTrainRequest` 与 `POST /train/mypc`（缺省 `config_file=train_my_pc.conf`）。
  - `web_ui/backend/trainer_engine.py`：`TrainingJob.mode` 与 `create_job` 支持 `mypc`；`stop_job` 对 `mypc` 走 `stop_event`（同 online）；新增 `run_mypc` 复用 `run_online` 的 SSH 管线。
  - `web_ui/frontend/src/hooks/useTrainingJob.ts`：抽出 `startSshTraining` 共用 SSH 启动逻辑，新增 `startMyPc`（写 `train_my_pc.conf`）。
  - `web_ui/frontend/src/pages/TrainerPage.tsx`：`mode` 三档；online/mypc 各一套独立表单状态，mount 时分别加载 `train_online.conf` / `train_my_pc.conf`；启动按钮按档位显示文案。
  - `web_ui/frontend/src/components/trainer/RemoteConfigForm.tsx`：新增 `titleKey` prop（云端/我这台电脑标题复用）。
  - `web_ui/frontend/src/store/useStore.ts`：新增 `trainerMyPcConfig` + `setTrainerMyPcConfig` 并持久化。
  - `web_ui/frontend/src/services/api.ts`：新增 `startMyPcTrain`。
  - `web_ui/frontend/src/i18n/messages/trainer.ts`：新增/更新 mypc 相关词条（`tabMyPc`/`tabLocal`/`tabCloud`/`startMyPcTraining`/`myPcTraining`，zh/en）。
  - 测试同步：新增 `web_ui/backend/tests/test_trainer_mypc.py`（3 项：mypc 路由建 job、缺省参数、stop 触发 stop_event）+ `web_ui/frontend/src/components/trainer/ModeTabs.test.tsx`（3 项：三档渲染/选中高亮/点击回调）。后端 pytest 全量 79 项、前端 vitest 全量 20 文件 101 项、`tsc -b --noEmit` 全部通过。
  - 注：本次改动在 `Tony-issue170-trainer-3mode` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (17)

- feat(web-ui): Drive/TM/Trainer/PA 合并为纵向滚动大页面，点导航锚点平滑滚动到对应区域（Issue #178）
  - 需求：DD 四个页面（Drive/TM/Trainer/PA）原为独立路由（`/`、`/drive`、`/trainer`、`/pilot`），改为一个纵向连续滚动的大页面，顺序自上而下 Drive→TM→Trainer→PA，点顶部导航滑到对应 section，形成「开车采数据→管数据→训练→评测」的流程引导；Car Connector 保持独立路由、不在合并范围。
  - `web_ui/frontend/src/App.tsx`：删除 Home 占位页与 KeepAliveTubManager；路由改为「`/connector` → CarConnectorPage」+「`/*` → FlowPage」兜底——同一兜底路由保证 `#/drive`、`#/tub`、`#/trainer`、`#/pilot` 四个 hash 深链导航切换时只改 pathname、不重挂载 FlowPage（保住 #135 常驻保活）。
  - `web_ui/frontend/src/pages/FlowPage.tsx`（新增）：四 section 固定顺序堆叠，每段带编号徽标 + 标题 + 流程描述 + 分隔线；IntersectionObserver 滚动联动（scroll spy，可见比例最大者为 activeSection）；按 pathname 平滑 scrollIntoView 到对应 section（懒加载 chunk 未就绪时 rAF 轮询等待；jsdom 无 scrollIntoView 时跳过）。
  - `web_ui/frontend/src/store/useFlowStore.ts`（新增）：zustand 存 activeSection，供 Layout 高亮当前导航。
  - `web_ui/frontend/src/pages/TubManagerPage.tsx`（新增）：TubManagerPage 从 App.tsx 迁出，作为流程页 TM section，自身逻辑不变。
  - `web_ui/frontend/src/components/Layout.tsx`：四项导航改为锚点（`/drive`、`/tub`、`/trainer`、`/pilot`），激活态随滚动联动；CC 仍是独立路由高亮；手机菜单点击即收起（含同 path 重复点击）。#179 的标题链接改动保持不变。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：新增 `active` prop，`useDriveHotkeys`/`useKeyboardDrive` 仅在 drive section 可见时启用，避免同页常驻后 R/M/U/S/A/I/J/K/L 在其它区域误触；移除页内 `drive.title` 标题（上移到 section 头）。
  - `web_ui/frontend/src/pages/PilotArenaPage.tsx`：新增 `active` prop，空格播放/暂停仅在 pilot section 可见时启用；移除页内 `arena.pageTitle`/`arena.pageDescription` 标题块（上移到 section 头）。
  - `web_ui/frontend/src/pages/TrainerPage.tsx`：移除页内 `trainer.title` 标题行，ModeTabs 右对齐保留。
  - `web_ui/frontend/src/i18n/messages/common.ts`：新增 flow.drive/tubManager/trainer/pilotArena.desc 四条流程描述（zh/en）。
  - 测试同步：`App.test.tsx` 的 keep-alive 回归测试改为断言「TM 在流程页各 section 间常驻、切 /connector 卸载、回切因已加载不重拉 tub」；vitest 全量 19 文件 98 项、`tsc -b --noEmit`、eslint（改动文件）、`npm run build` 全部通过。
  - 注：本次改动在 `Tony-issue178-unified-flow-page` 功能分支完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (15)

- fix(launcher): DC 终端长时间无交互断线丢会话——PTY 会话与 WS 连接解耦，断线宽限期 + 按 sid 重连接回 + 断线输出回放补发 + 前端自动退避重连（Issue #173）
  - 背景：DC（Drifter Console）Web 终端的 PTY 会话与 WebSocket 连接一一绑定，浏览器闲置/休眠/网络抖动导致 WS 断开后服务端直接关闭 PTY，重新打开终端只能开新会话，现场输出与运行中进程全部丢失。
  - `donkeycar/launcher/terminal.py`：
    - `TerminalSession` 与连接解耦：不再持有固定 writer，新增 `attach(writer)`（接入新连接并补发回放缓冲）/ `detach(writer=None)`（定向解除，只 detach 属于本次连接的 writer，防旧连接收尾误清新 writer 的竞态）；断线期间子进程输出经 `_stash()` 存入回放缓冲（`_REPLAY_CAP` 1MiB 环形上限）。
    - 新增模块级 `_sessions` 注册表（sid→session，`_sessions_lock` 保护）、`_acquire_session(requested_sid)`（按 sid 复用存活会话或新建）、惰性启动的 `_ensure_sweeper()` 后台清扫线程（30s 周期调用 `_sweep_once()`）与 `_sweep_once(now)`（可单测的清扫单批）——断线后宽限期 `_SESSION_GRACE=900s` 内可重连接回，超时且无 writer 的会话才销毁回收。
    - `handle_terminal_ws` 解析查询参数 `?session=<sid>`，建连后首帧下发 `{"type":"session","id":..,"reattached":..}`；WS 断开只 `detach` 不 `close`，PTY 进程与输出缓冲保留；会话真正 `close()` 时从注册表注销。
  - `donkeycar/launcher/terminal_static/terminal.html`：记录服务端下发的会话 ID（`lastSid`），重连 URL 带 `?session=` 请求接回；断线后自动退避重连（500ms 起指数退避 ×2 封顶 10s，`visibilitychange`/`online` 事件立即重试）；收到 exit 帧置 `exited=true` 不再自动重连；重连未接回（新会话）时 `term.reset()` 清屏避免新旧输出混杂；断线 overlay 点击改为触发 `connect()` 而非整页 `location.reload()`；i18n 删 lost/failed 词条、新增 reconnecting。
  - 测试同步：`donkeycar/tests/test_launcher_terminal.py` fixture 适配新构造签名（`TerminalSession()` 手动注册 + attach），`_open_terminal_ws` 支持 `session_id` 参数，新增 `_read_json_control` 助手与 3 个 #173 测试——建连 session 帧下发、断线重连 reattach 保现场并补发回放缓冲、宽限期后 `_sweep_once` 销毁回收。本文件 22 项全部通过，launcher/server/terminal 相关 43 passed 2 skipped。
  - 注：本次改动在 `Tony-terminal-reattach` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (14)

- feat(web-ui): Trainer「高级选项」折叠行文案精简为「高级」（Issue #183 后续微调）
  - `web_ui/frontend/src/i18n/messages/trainer.ts`：`trainer.advancedOptions` 值 zh「高级选项」→「高级」、en「Advanced Options」→「Advanced」，词条 key 不变。
  - `web_ui/frontend/src/components/trainer/LocalConfigForm.tsx`：折叠行注释同步（Advanced Options → Advanced）。
  - 后续微调（同分支，PR #207）：高级折叠行改薄——去掉 `py-2` 纵向内边距、方向箭头 `w-4 h-4`→`w-3.5 h-3.5`、加 `transition-colors`，对齐 Drive 页虚拟摇杆折叠头薄款样式。
  - 测试同步：仅文案/样式变更，无测试引用旧文案；`tsc -b --noEmit` 通过。
  - 注：本次改动在 `Tony-trainer-advanced-label` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (13)

- feat(ui): DD/D 两个页面标题文字可点击跳转官网，效果与点击 logo 图标一致（Issue #179，跨仓库功能：DD/DC/D 三页面标题可点）
  - `web_ui/frontend/src/components/Layout.tsx`：顶栏「DonkeyDrifter」标题文字与 logo 合并进同一个 `<a href="https://www.donkeydrift.com" target="_blank" rel="noopener">`（logo `<img>` 与文字之间以 `gap-3` 保持原 12px 间距）；链接在 `font-bold text-xl` 容器内，文字继承深浅主题标题色，Tailwind reset 下无下划线/变色，仅新增指针手势。
  - `donkeycar/launcher/server.py`（Donkey 启动页）：`MENU_HTML` 中 `<h1>Donkey</h1>` 改为 `<h1><a class="titleLink" href="https://www.donkeydrift.com" target="_blank" rel="noopener">Donkey</a></h1>`；CSS 新增 `.titleLink{color:inherit;text-decoration:none}`——颜色继承 h1、无下划线，行为对齐 logoLink。
  - 测试同步：无标题专属测试需新增；验证 `tsc -b --noEmit` 通过、vitest App/components 14 文件 78 项通过、launcher `tests/test_launcher_menu_actions.py` 37 项通过。
  - DC（Drifter Console，ESP32 Web Console）侧同类改动在 Firmware 仓库同步提交（v1.8.9，已 OTA 上车）。
## 2026-08-18 (12)

- feat(launcher): 菜单 6/7 两项打通 DD 的入口合并为 6 号「Donkey Drifter」，7 号位置灰占位、其余序号一律不变（Issue #181）
  - 背景：launcher 菜单（`menuItems`，编号 0–12）中 6「Drive」与 7「Web」最终都进入同一 DD 应用（6 走 `/api/launch/drive` 进 Drive 页，7 走 `/api/launch/web` 起 DD 前后端跳首页）；用户要求合并为一个「Donkey Drifter」入口（进 DD Drive 页面），7 号位空出占位，8–12 序号保持原位不递补。
  - `donkeycar/launcher/server.py`（MENU_HTML）：
    - `menuItems`：6 号改名「Donkey Drifter」（cat 保持 drive、favorite 保持常用），desc 改为「进入 DonkeyDrift（Drive 页面）/ Enter DonkeyDrift (Drive page)」；7 号改为 `placeholder: true` 占位行（name "—"、无分类、无 favorite、desc「已合并至 6 号『Donkey Drifter』/ Merged into #6 Donkey Drifter」）；8–12 条目原样未动。
    - `renderMenu()`：占位行渲染分支——不可点击（无 onclick）、无分类 pill、无 favorite 标、`.menuItem.placeholder` 样式（置灰 opacity .45、虚线边框、无 hover/选中效果，深浅两主题各配覆盖）。
    - `selectItem()`：占位项只弹「已合并至 6」轻提示（复用 showError），不触发任何动作；删除原 `no === 7 → launchWebUI()` 分支（数字键 7 经同一入口，行为同步）。
    - 删除前端 `launchWebUI()` 函数与 `overlay.startingWeb` i18n 词条（zh/en）；帮助文案 `help.keyNumbers` 双语更新为「（7 号已并入 6 号）」。
    - 服务端：删除 `POST /api/launch/web` 路由与 `_launch_web_ui()`（排查确认无其它消费方——DD 前端/DC 均未调用，仅菜单自身与测试）；`/api/launch/drive` 与 `GET /launch/drive`（DC 入口）不动。
  - 测试同步：`tests/test_launcher_menu_actions.py` 删除 `TestLaunchWebUI`（3 项）及 `_fake_subprocess`/`_FakePopen` 助手、`_launch_web_ui` 导入；端点测试改为下线后 404 断言；前端断言类新增 `test_menu_6_7_merged_placeholder`（改名、占位标记、Web 链路不残留、8 号仍在原位）。pytest 全量 209 passed（`test_tub_manager_auto_refresh` 1 项既有失败在干净 origin/Tony 上同样失败，与本改动无关）；MENU_HTML 内嵌 JS 逐块 `node --check` 通过；临时实例实测 `/` 返回新菜单、`POST /api/launch/web` 404。


## 2026-08-18 (11)

- fix(web-ui): DD FAB 浮球群残留的菜单式语言入口移除，语言入口统一为顶栏静音式单按钮（Issue #139 遗留）
  - 背景：Issue #139 修复（PR #146）把 DD 顶栏 `LanguageSwitcher` 与 D 启动页语言入口改成了静音式单按钮，但 DD 右下角 FAB 浮球群（`FabActions.tsx`，镜像自 DC）里仍残留 🌐 语言球 + 弹出式 langMenu（中文/English 两项菜单），违反验收要点"移除原菜单式语言切换入口，不残留死代码"；DC 侧同源 FAB 群在 Firmware 侧修复时已彻底移除语言球只留 helpFab，DD 侧对齐。
  - `web_ui/frontend/src/components/FabActions.tsx`：删除 langFab（🌐 语言球）、langMenu 弹出菜单、`LANG_SEGMENTS`、`langMenuOpen` 状态与 `toggleLangMenu`/`chooseLanguage`，FAB 群只剩 fabToggle（发光圆点）+ helpFab（?）；`collapse` 外点收起逻辑同步简化。组件头注释更新为 `.fabToggle + .fabActions (.helpFab) + .helpModal`，注明语言入口在顶栏 LanguageSwitcher。
  - `web_ui/frontend/src/i18n/messages/fab.ts`：删除已无引用的 `fab.language` 词条（zh/en 各一条），头注释同步。
  - 测试同步：`FabActions.test.tsx` 新增 1 项"FAB 群不渲染任何语言按钮/菜单"（queryByRole 语言 + queryByText 🌐/中文/English 全空）；vitest 全量 19 文件 98 项通过，`npm run build` 通过。

## 2026-08-18 (10)

- feat(web-ui): Trainer 本地训练「高级选项」由勾选框改为点击展开的折叠面板（Issue #183）
  - 需求：Trainer 页本地训练配置的「高级选项」原为 checkbox 勾选形态，改为下拉折叠面板——点击整行在下方展开高级字段，再点收起，不再有勾选框。
  - `web_ui/frontend/src/components/trainer/LocalConfigForm.tsx`：勾选框替换为与 Drive 页「控制参数」面板（`ParameterPanel.tsx`）同款的整行按钮 + 右侧 ChevronDown/ChevronUp 方向箭头（lucide-react），点击切换 `advancedEnabled`，带 `aria-expanded` 无障碍标注；样式用 ParameterPanel 同款 `text-zinc-400 hover:text-zinc-200` 类名，深浅主题经 theme-light.css 类名级重映射自动适配。
  - 语义保持：`advancedEnabled` 仍是"高级覆盖生效"开关（展开=启用、收起=不启用），持久化（useStore）、`TrainerPage.tsx` 按 myconfig.py 覆盖自动置 true（面板默认展开）与训练时写 myconfig 的联动全部不动；收起时已填值保留不重置。i18n 沿用 `trainer.advancedOptions`，无新增词条。
  - 测试同步：无 LocalConfigForm 专属测试，无需新增；前端 vitest 全量 19 文件 97 项、`tsc -b --noEmit`、eslint（改动文件）、`npm run build` 全部通过。
  - 注：本次改动在 `Tony-trainer-advanced-collapse` 功能分支（worktree 作业）上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (9)

- fix(web-ui): Drive 页控制参数滑块轨道浅色模式下仍为黑色——theme-light 增补伪元素变体类名覆盖（Issue #169）
  - 根因：`ParameterPanel` 的 `ParamSlider` 把轨道色写在伪元素变体类上（`[&::-webkit-slider-runnable-track]:bg-zinc-800` / `[&::-moz-range-track]:bg-zinc-800`），Tailwind 生成的类名不是字面 `.bg-zinc-800`，`theme-light.css` 的类名级重映射（`html.theme-light .bg-zinc-800`）匹配不到，轨道在任何主题下都吃硬编码 zinc-800 黑色。
  - `web_ui/frontend/src/themes/theme-light.css`：组件级微调区新增两条覆盖规则——`html.theme-light .\[\&\:\:-webkit-slider-runnable-track\]\:bg-zinc-800::-webkit-slider-runnable-track` 与对应的 `::-moz-range-track`，颜色 `#e2e8f0`（文件中 raised controls 档，本就为滑块轨道设计的浅色）；只覆盖颜色不动尺寸，thumb（24×16px 纯白椭圆）与轨道高度（6px）均未改。
  - 测试同步：无 ParameterPanel 专属测试，无需新增；已核验产物 CSS 中 Tailwind 生成的转义类名与覆盖选择器逐字匹配、规则排序在后优先级压过原规则；vitest drive 组件 + ThemeSwitcher 6 文件 42 项、`npm run build` 全部通过。
  - 注：本次改动在 `Tony-issue169-drive-slider-track-light` 功能分支上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (10)

- refactor(web-ui): 清理 CC 页与 DC 重复的配置/选项——删除「扫描局域网找车」与无 UI 消费的 `/api/provisioning/*` 配网路由（Issue #177）
  - 背景：车端 IP 的发现/配网职责归 DC（Drifter Console，Wi-Fi 配网 + Network 卡片展示 AP/STA IP），CC（Car Connector）页另起一套「host + 局域网扫描找车」流程与之重复；DD 后端还挂了一套前端从未调用过的 `/api/provisioning/*` 配网路由，同为重复入口。
  - `web_ui/frontend/src/pages/CarConnectorPage.tsx`：「连接配置」卡删除「扫描局域网」按钮、候选 IP 列表与相关状态/回调（`foundCars`/`discovering`/`handleDiscoverCars`），host 改为纯手填；SSH 凭据、检查连接等 CC 独有职责保留。
  - `web_ui/frontend/src/services/api.ts`：删除 `discoverConnectorCars`（POST `/connector/discover`）；`discoverConnectorConsoles`（`/connector/discover_console`，launcher 页入口按钮）保留——它是"打开 DC"的入口而非配网配置。
  - `web_ui/backend/routers/connector.py`：删除 `POST /api/connector/discover`（扫 22 端口找 SSH 主机）端点。
  - `web_ui/backend/main.py` + 删除 `web_ui/backend/routers/provisioning.py`：整组 `/api/provisioning/*`（status/connect/scan/serial/scan）配网路由下线——Wi-Fi 配网由 DC 单一入口承担；`donkeycar/parts/provisioning.py`（WifiManager/ProvisioningPart 车端部件）不受影响。
  - `web_ui/frontend/src/i18n/messages/connector.ts`：zh/en 各删除 6 条只服务于扫描找车的词条（`connector.scanning`/`scanLan`/`foundHosts`/`carIpSelected`/`discoverFound`/`scanFailed`）。
  - 测试同步：`web_ui/backend/tests/test_connector.py` 删除 `/api/connector/discover` 路由断言与 2 个 discover 端点测试；`web_ui/backend/tests/test_provisioning.py` 随路由整体删除；后端 pytest 全量 76 项通过，前端 vitest 19 文件 97 项通过，`tsc --noEmit` 通过。

## 2026-08-18 (8)

- feat(web-ui): DD 驾驶页输入源选择框移入虚拟摇杆面板标题栏，摇杆区域支持折叠/展开
  - 背景：`InputSourceSelector`（摇杆/键盘/手柄/陀螺仪输入源切换）原挂在顶部工具栏（DriveModeSelector 前），与右侧虚拟摇杆面板分离——用户希望选择框与虚拟摇杆放在一起，且摇杆区域可折叠以腾出屏幕空间。
  - `web_ui/frontend/src/pages/DrivePage.tsx`：顶部工具栏删除 `InputSourceSelector`；右侧控制面板标题栏改为左侧可点标题按钮（"虚拟摇杆" + ChevronUp/ChevronDown 图标，点击切换 `joystickOpen`，默认展开），右侧放 `InputSourceSelector`——折叠后选择框仍可见可切换；摇杆主体区（`VerticalThrottleBar` + `VirtualJoystick` + `ControlBars`）包在 `joystickOpen` 条件渲染内，折叠时整块收起只留标题栏。原标题栏"支持鼠标/触屏"小字随之移除（i18n 词条 `drive.mouseTouchSupport` 保留未删）。
  - `web_ui/frontend/src/i18n/messages/drive.ts`：zh/en 各新增 `drive.collapseJoystick`（折叠虚拟摇杆/Collapse virtual joystick）、`drive.expandJoystick`（展开虚拟摇杆/Expand virtual joystick），用作折叠按钮的 aria-label/title。
  - 测试同步：前端 vitest 全量 20 文件 95 项通过，`tsc -b --noEmit` 通过；Playwright 截图验证展开/折叠两态布局正常（选择框始终在标题栏右侧、折叠后摇杆圆盘收起）。
## 2026-08-18 (7)

- fix(web-ui): 顶部导航切换 Tub Manager 严重卡顿三轮修复——TM 页常驻保活 + 懒加载 chunk 空闲预取 + 后台快捷键/播放守卫（Issue #135，二轮 dev→生产模式后用户仍报卡顿）
  - 根因（Playwright + PerformanceObserver(longtask) 对用户 8000 生产实例实测确认）：react-router 每次导航到 `/` 都完整卸载重挂载 TubManagerPage——TubLibrary（2282 条记录列表 + 图片 LRU）与 TubEditor（chart-vendor 图表）整树重建，每次切换产生 77-99ms 主线程 longtask，其余页面 0ms；用户真实浏览器（更多扩展、非无头）放大到数百 ms 体感卡顿。
  - `web_ui/frontend/src/App.tsx`：新增 `KeepAliveTubManager` 组件挂在 Routes 之外（Layout main 内、Suspense 外，ErrorBoundary 仍包住）——TubManagerPage 首次进入后常驻不卸载，用 `location.pathname === '/'` 切换 `hidden` class（面板挂 `<div data-tub-manager>` 且切走时 hidden，DOM 保留、状态不丢）；原 `<Route path="/">` 改为 `element={null}`；新增 `useIdlePrefetch` hook 空闲时（requestIdleCallback）预取 Drive/Trainer/Pilot/Connector 4 个懒加载 chunk，消除冷切换时的脚本解析卡顿。
  - `web_ui/frontend/src/components/TubLibrary.tsx`：新增 `isTubManagerRoute = useLocation().pathname === '/'` 守卫——空格键播放/暂停监听仅在 TM 页生效（切走不串页）；新增切走自动停播 effect（`isPlayingRef.current = false` + `setIsPlaying(false)`，防止后台页面持续预取图片耗资源）。
  - `web_ui/frontend/src/components/TubEditor.tsx`：全局键盘监听同样加 `isTubManagerRoute` 守卫。
  - 测试同步：`web_ui/frontend/src/App.test.tsx` 新增 keep-alive describe（mock 4 个懒加载页面组件）——TM 面板切走仍挂载且 hidden、切回恢复可见、不重拉 tub；`web_ui/frontend/src/components/TubLibrary.test.tsx` render 包 `MemoryRouter` 适配新 `useLocation` 依赖。vitest 全量 19 文件 95 项、`tsc -b --noEmit`、`npm run build` 全部通过。
  - 实测（8021 测试实例 + chrome-headless-shell，tub=/home/dkc/projects/mycar/data，2282 帧）：修复前 TM 每次切换 longtask 77-99ms；修复后热切换全部归零（R2 及 Drive↔TM 来回 x3 全 0ms），仅首轮冷加载一次性 70-84ms；功能抽查确认切走面板 hidden 仍挂载、切回立即可见、2282 帧数据完整保留不重拉。

## 2026-08-18 (6)

- feat(launcher/web-ui): DC 与 DD 页面新增「DeepSeek Harness」入口按钮；DSH 启动端点缺省进入 Projects 工作区；修复 DSH 设置页 Agents 预设/提供方目录 403（Issue #164 后续）
  - **DSH 启动端点与设置页 403 修复**：
    - `donkeycar/launcher/dsh_web.py`：新增幂等自愈补丁 `_patch_privileged_methods()`——dsh（rc.6/rc.7 相同）的 `dsh-client-connection/lib/index.js` 把 `settings.*`/`credentials.*`/`llm.discoverModels`/`agentPreset.read` 等特权方法硬编码 `isTrustedApiRequest(request, [])`（空信任表，`--trusted-host` 对其无效，上游有意设计），导致 LAN Host 访问 DSH 设置页时「正在加载/权限不可用」「加载提供方目录失败」。补丁在启动前把安装文件中的 `PRIVILEGED_METHODS.has(method) && !isTrustedApiRequest(request, [])` 替换为 `...trustedHosts)`（同函数闭包变量，即沿用 `--trusted-host` 信任表）；幂等（新代码段已存在则跳过）、dsh 升级还原文件后自动重打（未命中旧代码段则跳过仅告警）；`_connection_index_path()` 从 dsh bin realpath 定位 `<pkg>/node_modules/@deepseek-ai/dsh-client-connection/lib/index.js`，找不到返回 None 安全跳过。实机验证：打补丁重启后 LAN Host（192.168.3.57:3987）下 `settings.describe` 返回 200；伪造 Host（evil.example.com）仍 403；回环 200，安全性保持。
    - `donkeycar/launcher/server.py`：`_handle_launch_dsh` 未指定 cwd 时缺省 `/home/dkc/projects`——DSH 新会话默认工作区即 Projects（dsh-host-apiproxy 用 `process.cwd()` 作为新会话默认目录，已验证 workspace.list 返回 `/home/dkc/projects`），打开 DSH 后自动进入 Projects 工作区。
  - **DD 页面（DonkeyDrifter Web UI）新增 DSH 按钮**：
    - `web_ui/backend/routers/launch.py`：抽出 `_forward_launch(request, launcher_path)` 共用转发逻辑，新增 `@router.post("/dsh")` 转发 launcher `/api/launch/dsh`。
    - `web_ui/frontend/src/services/api.ts`：新增 `launchDsh`（复用 `LaunchKimiCodeWebResult`）。
    - `web_ui/frontend/src/components/EnterButtons.tsx`：新增 `dshLaunching` 状态与 `enterDsh`（about:blank 句柄 + 65s AbortController，交互与 Kimi Code Web 按钮同款）；按钮顺序 kimi → dsh → console（consoleFirst 时 console → kimi → dsh）。
    - `web_ui/frontend/src/i18n/messages/common.ts`：zh/en 各加 5 条 `common.enterButtons.dsh*` 词条。
    - 测试同步：`EnterButtons.test.tsx` 三按钮顺序断言更新 + 新增 dsh 启动成功/失败 2 项；`tests/test_launcher_dsh_web.py` 新增 TestPatchPrivilegedMethods（5 项：定位 index.js、命中替换、幂等、未命中跳过、锁保护）+ `test_endpoint_defaults_cwd_to_projects`。launcher 侧 24 passed，前端 vitest 全量 97 passed，`npm run build` 通过。
  - DC（ESP32 Web Console）侧同款按钮见 Firmware v1.8.7（`#openDshBtn`，POST `/api/launch/dsh`）。
## 2026-08-18 (5)

- fix(web-ui): Car Connector 页面删除顶部大标题——进入 CC 页不再显示重复的 "Car Connector" 标题
  - 背景：顶部导航已有 Car Connector 入口，页面内再显示同名大标题属于冗余信息，用户要求删掉。
  - `web_ui/frontend/src/pages/CarConnectorPage.tsx`：删除页面顶部 `<h1>{t('connector.pageTitle')}</h1>` 大标题，页面直接从「连接配置」卡片开始。
  - `web_ui/frontend/src/i18n/messages/connector.ts`：删除已无引用的 `connector.pageTitle` 词条（zh/en 各一处）。
  - 测试同步：无测试引用 `connector.pageTitle`，无需改动；vitest 全量 19 文件 94 项、`tsc -b`、`npm run build` 全部通过。
  - 注：本次改动在 `Tony-cc-remove-title` 功能分支上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (4)

- feat(web-ui): Trainer 页面 Tub 路径自动填充——进入页面自动定位正确 tub，无需每次手填
  - 背景：Trainer 本地训练的 Tub 路径输入框默认值硬编码 `./data`，与 Tub Manager / Tub Navigator 当前加载的 tub 脱节，用户每次训练前要手工复制路径。
  - `web_ui/backend/routers/trainer.py`：新增 `GET /tubs?working_dir=<dir>`——扫描 `<working_dir>/data` 本体、`data` 下每个含 `manifest.json` 的子目录（覆盖解压后的 `data/tub_xxx` 形式）及 `<working_dir>/data*` 兄弟目录，返回候选列表（`relative_path` ./data 风格 + `absolute_path`）与当前已加载的 `current_tub_path`（复用 `routers/tub.py` 全局状态）。
  - `web_ui/frontend/src/pages/TrainerPage.tsx`：mount / `configPath` / `tubPath` 变化时拉取候选并自动选中，优先级：当前加载的 tub（`store.tubPath` > 后端 `current_tub_path`，匹配后转为相对路径显示）> `./data`（若为合法 tub）> 唯一候选；用户手动编辑过（ref 标记 dirty）后不再自动覆盖。
  - `web_ui/frontend/src/components/trainer/LocalConfigForm.tsx`：Tub 路径改为「下拉选候选 + 文本框可手改任意路径」，当前已加载的 tub 在下拉中标注「当前已加载」。
  - `web_ui/frontend/src/services/api.ts`：新增 `listTrainerTubs()` 与 `TrainerTub` 类型；`web_ui/frontend/src/i18n/messages/trainer.ts`：新增 `trainer.tubPathManual` / `trainer.tubLoaded`（zh/en）。
  - 测试同步：新增 `web_ui/backend/tests/test_trainer_tubs.py` 4 项（data 目录与子 tub、无 data 为空、跳过非 tub 目录并识别 data* 兄弟、报告已加载 tub）；pytest 后端全量 85 项、前端 vitest 全量 20 文件 95 项、`tsc -b --noEmit`、eslint、`npm run build` 全部通过。
  - 注：本次改动在 `Tony-trainer-tub-autofill` 功能分支上完成并按分支流程提交、PR 合入 `Tony`。Firmware 无改动，无需 OTA。

## 2026-08-18 (3)

- feat(web-ui): Tub 导航器合入录制视频库——TM 页只保留「录制视频库」一个预览面板，TubNavigator 组件整体删除
  - `web_ui/frontend/src/components/TubLibrary.tsx`：集成原 Tub 导航器全部能力——
    - FPS 角标：播放中按实际换帧数每秒统计（#128 同款逻辑），画面冻结时角标跟随下降，暂停清零；
    - 转向/油门数值面板：读当前帧 `user/angle`（回退 `pilot/angle`）与 `user/throttle`（回退 `pilot/throttle`），无值显示「无」；
    - 帧控制排：首条/上一帧/播放/下一帧/末帧 + 刷新（`requestTubRefresh` 全量重拉，#135 手动刷新）+ 删除；
    - 标题 hover 展开「浏览 Tub 记录」副标题（`tub.subtitle`）；
    - 空格键播放/暂停快捷键（输入框聚焦时不触发）；
    - 全局图表联动（原 TN 核心职责）：换帧/播放把当前帧绝对索引 `_index` 写入全局 `currentIndex`（播放中 ~30ms 节流），Tub Editor 图表红线跟随；反向订阅 store，图表点选帧落在当前场次范围内时跳转预览（播放中不打断）；
    - 性能沉淀迁移：图片 LRU 缓存 240 条上限（#135）、预取 60 帧窗口 + 6 并发（#128）；
    - 播放行为改为单次播放（播放到末帧即停），按用户指示不迁移「播放后停止/循环播放」切换键与 M 键快捷键。
  - `web_ui/frontend/src/components/TubNavigator.tsx` / `TubNavigator.test.tsx`：删除（功能已由 TubLibrary 承接）。
  - `web_ui/frontend/src/App.tsx`：TubManagerPage 移除 `<TubNavigator />`，只渲染 TubLibrary + TubEditor。
  - `web_ui/frontend/src/App.test.tsx`：`vi.mock` 从 TubNavigator 换成 TubLibrary 桩组件。
  - `web_ui/frontend/src/i18n/messages/tubnav.ts`：删除纯 TN 键（`tub.title`/`tub.noRecordsLoaded`/`tub.timeline`/`tub.dragging`/`tub.indexLabel`/`tub.noImage*`/`tub.loop*`/`tub.playOnce*` 等 20 键 zh+en），保留 TubLibrary 在用的 `tub.subtitle`/`tub.steering`/`tub.throttle`/帧控制与刷新键、TubLoader/SimulatorConfig 全部键。
  - `web_ui/frontend/src/themes/theme-light.css`：注释里 TubNavigator index badge 措辞更新为 TubLibrary FPS badge。
  - 测试同步：`TubLibrary.test.tsx` 原有 2 项（自动选最新、pin 置顶）保持不变且通过；vitest 全量 17 文件 89 项通过，`npm run build`（tsc -b + vite build）通过。

## 2026-08-18 (2)

- fix(launcher): DC 打开 Kimi Code Web 后进入"全新状态"——复用路径不看运行目录、入口 URL origin 漂移导致 localStorage 偏好清空、缺省 cwd 落用户主目录（Issue #168）
  - `donkeycar/launcher/kimi_web.py`：①复用路径校验实例运行目录——实例登记条目无 cwd 字段，新增 `_proc_cwd(pid)` 读 `/proc/<pid>/cwd` 真实路径，`_live_instance_url` 新增 `cwd` 参数，给定 cwd 时逐一比对（`os.path.realpath` 规范化），不匹配（如在 mycar 里跑的 TUI 内嵌 server）或读不到（进程消失/无权限）都跳过不误复用，由调用方在目标目录另起；②冷启动固定专属端口——新增常量 `KIMI_WEB_PORT = 58640`，拉起命令追加 `--port 58640`（避开 kimi 默认 58627：TUI 内嵌 server 默认占它，撞上后 kimi 自动顺延端口反而漂移），入口 URL origin 固定 `http://<LAN IP>:58640`，KCW 存在 localStorage 的置顶/自主模式/语言主题等偏好不再"被清空"；③`launch_kimi_code_web` 快路径与冷启动失败兜底均以 `cwd=` 关键字调用 `live_url_fn`（首参是 instances_dir，位置传参会把 cwd 误绑到实例目录上导致复用永远失败——真实环境联调发现并已修）。
  - `donkeycar/launcher/server.py`：`_handle_launch_kimi_code_web` 缺省 cwd 从用户主目录改为 Projects 工作区 `/home/dkc/projects`（DC 按钮空体 POST 不带 cwd，此前落到主目录导致 KCW 进的是工作区列表而非 Projects；DD 菜单显式传同一目录不受影响）；显式传 cwd 仍优先；docstring 同步。
  - 测试同步：`tests/test_launcher_kimi_web.py` 更新与新增——`_live_instance_url` cwd 匹配复用/不匹配跳过/`/proc` 读不到视为不匹配 3 项；冷启动命令含 `--port <KIMI_WEB_PORT>` 断言；复用钩子改为只收关键字参数（抓位置传参回归）；端点测试 fixture 记录收到的 cwd，新增空体 POST 与显式 cwd 两项断言缺省值为 `/home/dkc/projects`。pytest `tests/test_launcher_kimi_web.py` 38 项、launcher 相关全量 113 项通过。
  - 真实环境验证：重启 launcher 服务后 DC 同款空体 POST 连发 3 次均返回 `http://192.168.3.57:58640/#token=…`（第 1 次冷启动、后 2 次日志确认复用同端口同实例），新实例 `/proc/<pid>/cwd` 确认为 `/home/dkc/projects`；固件侧无需改动（DC 按钮 JS 与 CORS 逻辑不变）。

## 2026-08-18 (1)

- fix(web-ui): DD 驾驶页输入源切换器「手柄/陀螺仪」永远灰色不可选——连接/支持检测被 `enabled` 门控形成先有鸡还是先有蛋的死锁
  - 根因：`InputSourceSelector` 中手柄项需 `gamepadConnected`、陀螺仪项需 `permissionState !== 'unsupported'` 才可点，但 `DrivePage` 传入的 `useGamepadDrive({ enabled: inputSource === 'gamepad' })` 与 `useGyroDrive({ enabled: inputSource === 'gyro' })` 都在 `!enabled` 时直接 return——未选中该输入源时检测逻辑根本不运行，状态停在初始值（`connected=false` / `permissionState='unsupported'`），按钮永远灰着点不了，形成死锁。
  - `web_ui/frontend/src/hooks/useGamepadDrive.ts`：`gamepadconnected`/`gamepaddisconnected` 监听拆为独立 effect，组件挂载即注册（不受 `enabled` 门控），选中手柄前插手柄即可点亮可选项；控制轮询 RAF 循环仍只在 `enabled` 时运行。
  - `web_ui/frontend/src/hooks/useGyroDrive.ts`：新增挂载即执行的支持性检测 effect（不受 `enabled` 门控）：无 `DeviceOrientationEvent` → `unsupported`；存在 `requestPermission`（iOS 13+）→ `prompt`；其余（Android/桌面）→ `granted`。原 `enabled` 门控的 orientation 监听 + RAF 循环不变。
  - 测试同步：新增 `web_ui/frontend/src/hooks/useGamepadDrive.test.tsx`（2 项：未 enabled 时连接检测仍运行、全部断开后复位）、`useGyroDrive.test.tsx`（3 项：非 iOS 挂载即 granted、iOS 初始 prompt、不支持时 unsupported）。前端 vitest 全量 20 文件 95 项通过，`tsc -b --noEmit` 通过。
  - 注：本次改动在 `Tony-fix-input-source-disabled` 功能分支上完成并按分支流程提交、PR 合入 `Tony`。

## 2026-08-17 (17)

- fix(launcher): Drifter Console 恢复 0 号置顶（#164 用户后续指示，撤销同日 (15) 条目的 DC 挪位）
  - `donkeycar/launcher/server.py`：menuItems 恢复 0 号 Drifter Console（`favorite: true`，置顶），DeepSeek Harness 保持 12 号（常用），编号回到 0-12；`selectItem` 恢复 `no===0 → openDrifterConsole()` 分支，删除 13 号分支；键盘恢复 0 键直达（`key==='0' → selectItem(0)`），两位输入只保留 10/11/12（按 1 后 0/1/2），删除 1+3 组合；i18n `help.keyNumbers` 改回「数字键 0-12」（zh/en + HTML data-i18n）。
  - 测试：`tests/` 全量 202 passed 无回归（菜单 HTML 无针对编号的断言，无需改测试）。

## 2026-08-17 (16)

- fix(terminal): 上位机终端页 WebSocket 连接加 10s 超时，连接卡死不再无限停在「正在连接上位机终端…」（#101，配合 Firmware v1.8.6 DC 侧探测超时）
  - `donkeycar/launcher/terminal_static/terminal.html` `connect()`：新增 `connectTimer` 10 秒定时器，超时时若 `ws.readyState===WebSocket.CONNECTING` 则清掉 `onclose`、主动 `ws.close()`，并 `showOverlay(t('failed')+' · '+t('reconnect'))` 提示连接失败可点击重连；`ws.onopen` 首行 `clearTimeout(connectTimer)` 取消定时器；`ws.onclose` 同样先 `clearTimeout` 再提示「连接丢失 · 新会话」。
  - 文案复用原 T 词典已有的 `failed` / `reconnect` 词条，中英文均无需新增。
  - 测试同步：`tests/test_launcher_terminal.py` 更新 `onclose` 断言为含 `clearTimeout` 版本；新增 `test_terminal_page_has_connect_timeout()` 断言 connectTimer/CONNECTING/ws.close/showOverlay 及中英文案存在。pytest `tests/test_launcher_terminal.py` 4 项、`donkeycar/tests/test_launcher_terminal.py`+`tests/test_launcher_menu_actions.py` 56 项全部通过。

## 2026-08-17 (15)

- feat(launcher): 启动器菜单新增「DeepSeek Harness」12 号项（常用），点击拉起/复用 `dsh web` 并跳转；Drifter Console 挪至 kimi 右侧 13 号（Issue #164）
  - `donkeycar/launcher/dsh_web.py`（新文件）：`launch_dsh_web(cwd, timeout_s=60)` 启动/复用 DeepSeek Harness web。dsh CLI 拒绝 `--host 0.0.0.0`（安全限制），用 `--patch` 临时层覆盖 webserver 配置（`host: 0.0.0.0` + `port: !!js ctx.webStartup.port ?? 3080`，port 不能省否则配置校验报缺值）实现局域网可达；`--port 0` 由 OS 分配空闲端口避免与默认 3080 冲突；`--trusted-host <本机局域网 IP>` 放行 dsh `/api` 的浏览器信任栅栏（裸 host 匹配任意端口）。就绪 banner 一行（`dsh web: http://127.0.0.1:<port> (LAN: …)`）抓 URL 后改写为局域网 IP（复用 kimi_web 的 `_lan_url`，issue #125 同款）；复用路径靠本模块 `_SPAWNED` 登记 + GET / 探测（dsh 无实例登记文件），死进程/僵死端口自动剔除后冷启动。`_resolve_dsh_binary` 先 PATH 后当前 Python 解释器同目录（systemd 干净 PATH 回退）。
  - `donkeycar/launcher/server.py`：do_POST 新增 `/api/launch/dsh` 路由与 `_handle_launch_dsh`（可选 JSON body `cwd`，非法 cwd 直接报错不回退，响应带 `_KIMI_WEB_CORS_HEADERS` 供 DC 跨域）；menuItems 重排为 1-13——1-11 不变，新增 12 号 DeepSeek Harness（`favorite: true`），DC 从 0 号置顶改 13 号（kimi 右侧）；`selectItem` 新增 12→`launchDshWeb()`、13→`openDrifterConsole()`，删除 no===0 分支；键盘两位输入扩展支持 12/13（按 1 后 400ms 内按 2/3），删除 key==='0' 分支；前端新增 `launchDshWeb()`（POST `/api/launch/dsh`，cwd 固定 `/home/dkc/projects`，成功跳转 `data.url`）；i18n `help.keyNumbers` 改「数字键 1-13」（zh/en + HTML data-i18n），新增 `overlay.startingDshWeb`（zh/en）。
  - 测试同步：新增 `tests/test_launcher_dsh_web.py` 21 项——patch 文件内容、复用不起子进程、冷启动抓 URL 且改写 LAN IP、命令行含 `--patch`/`--port 0`/`--trusted-host`、无局域网 IP 省略 trusted-host、cwd 透传、cwd 非法、binary 缺失、超时杀进程、提前退出报现场、`_SPAWNED` 死条目/僵死探测剔除、端点 200/400/500 与 CORS 头、cwd 透传；`tests/` 全量 201 passed 无回归。

## 2026-08-17 (14)

- fix(web-ui): DD 语言/主题切换按钮字体逐值对齐 DC/D——三页面按钮完全一致（#92 四轮返工：字体差异收口）
  - 根因（两处）：其一，D 页面（本机 8090）launcher 为改版前启动的旧进程，内存仍是旧 zinc 配色（#27272a），仓库源码已正确，重启进程即恢复，无需改码；其二，DD 根布局 `div.font-sans` 被主题 css 的 `.font-sans` 规则重映射为 `system-ui` 前置栈，语言/主题按钮经 preflight `font:inherit` 继承该栈，与 D/DC 显式锁定的 `:root` 栈（`-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",…,"Apple Color Emoji","Segoe UI Emoji"`）不同，用户实测字体不一致。
  - `web_ui/frontend/src/themes/theme-mus4.css` / `theme-light.css`：`.theme-switcher-btn, .language-switcher-btn` 皮肤规则追加字体锁定——`:root` 完整字体栈 + `font-synthesis:none;text-rendering:optimizeLegibility;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale` + `font-size:12px;font-weight:600`（主题按钮原为 16px/400，一并统一为 12px/600）。
  - 验证：Playwright 三页面实测（D=127.0.0.1:8090、DD=dev 服务器、DC=车 192.168.3.46 v1.8.5）深浅两主题语言按钮 10 项计算样式（背景/边框/内圈/字色/字体栈/字号/字重/宽/高/圆角）D vs DC、DD vs DC 全部 IDENTICAL；vitest 14 项、pytest 全量 183 项、`npm run build` 通过。Firmware 侧无改动，车上 v1.8.5 即最新，无需 OTA。


## 2026-08-17 (13)

- feat(web-ui): 补齐 DD 中文翻译——`common`、`arena`、`driveviz` 三个 i18n 命名空间的 zh 词条全部翻译为中文，顶部导航栏按要求保持英文不译
  - `web_ui/frontend/src/i18n/messages/common.ts`：zh 从"镜像当前中英混合 UI"改为完整中文——App shell（出错了/刷新 Tub 失败/错误前缀/加载中）、ConfigLoader（配置加载器标题、选择车辆目录、浏览、加载、配置已加载、未加载配置、各类加载失败、路径占位与 aria）、FileBrowserModal（选择目录、返回、未找到目录、取消、选择当前目录）、SidePanel（加载器/连接器）、GitHubLink（`DonkeyDrift GitHub 仓库`）。顶部导航五项（Tub Manager/Trainer/Drive/Pilot Arena/Car Connector）按用户要求保持英文。
  - `web_ui/frontend/src/i18n/messages/arena.ts`（Pilot Arena）：zh 补译——User/Pilot 标签（用户/Pilot）、Angle/Throttle（角度/油门）、Brightness/Blur（亮度/模糊）、Pre/Post Transformations（前置/后置变换）、Tub Plot（Tub 曲线图）、Record index（记录索引）；`configLabel`/`recordsLabel`/plot 数据集名（user angle 等）等技术术语保留原文。
  - `web_ui/frontend/src/i18n/messages/driveviz.ts`（Drive 可视化）：zh 补译——Connecting/Disconnected（连接中/已断开）、Camera feed（摄像头画面）、12 条遥测曲线名（油门/转向/陀螺仪 X/Y/Z/加速度 X/Y/Z/RC 转向/RC 油门/Pilot 角度/Pilot 油门）。
  - en 词条与组件代码均未改动。
  - 测试同步：`TelemetryChart.test.tsx` 数据集断言（dataset testid、waitForDataset、复选框标签）改用中文曲线名；`VideoStream.test.tsx` alt/aria 断言改 `摄像头画面`/`WebRTC 摄像头画面`；`GitHubLink.test.tsx` 链接名断言改 `DonkeyDrift GitHub 仓库`。前端 vitest 全量 18 文件 90 项通过，`tsc -b` 与 `npm run build` 通过。
  - 注：本次改动在 `Tony-complete-zh-translations` 功能分支上完成并按分支流程提交、PR 合入 `Tony`。

## 2026-08-17 (12)

- style(web_ui/trainer): 已训练模型删除按钮改为红色（#148 后续）
  - `web_ui/frontend/src/components/trainer/ModelsList.tsx`：模型行删除按钮配色从 `text-zinc-500 hover:text-red-400` 改为常红 `text-red-400 hover:text-red-300`，与删除语义一致、更醒目。
  - 测试：`npm run build`（tsc -b + vite build）通过。

## 2026-08-17 (11)

- fix(launcher): 上位机终端 WebSocket 增加服务端心跳保活与空闲超时判死，长时间空闲不再悄悄断连丢会话（#151）
  - 根因：`donkeycar/launcher/terminal.py` 的 WebSocket ↔ PTY 桥无任何 keepalive——只在收到客户端 PING 时回 PONG，从不主动发 PING；长时间无数据的空闲连接被 NAT 表项老化/浏览器回收悄悄断开，而协议规定断连即杀 PTY 子进程，原 shell 会话连同现场全部丢失。
  - `donkeycar/launcher/terminal.py`：新增 `_heartbeat_loop` 心跳线程（`terminal-ws-heartbeat`，随 `handle_terminal_ws` 每连接一条）——每 `_PING_INTERVAL=25s` 向客户端发 WebSocket PING 帧（浏览器协议层自动回 PONG，无需前端配合，周期性帧同时刷新 NAT 表项）；主读循环每收到一帧刷新 `last_rx`，超过 `_PONG_TIMEOUT=60s` 无任何客户端帧则置 `writer.closed` 并 `shutdown(SHUT_RDWR)` 唤醒阻塞的主读循环，走原有 finally 清理 PTY 会话；连接结束时 `stop_hb` 事件退出心跳线程。模块 docstring 帧协议说明同步补心跳帧与保活语义。
  - `donkeycar/launcher/terminal_static/terminal.html`：断连 overlay 从「连接已断开 · 点击重连」改为明确提示现场丢失——新增 `lost`/`newSession` 双语文案（zh：「连接已断开 · 终端会话已丢失 · 点击重连（将开启新会话）」；en 同义），`ws.onclose` 改用新文案；shell 正常 exit 的 overlay 维持原文案。
  - 测试同步：`donkeycar/tests/test_launcher_terminal.py` 新增 2 项端到端用例（`_open_terminal_ws` 握手辅助 + 缩短心跳参数后断言收到服务端 PING、空闲超时后服务端主动断开读到 EOF）；`tests/test_launcher_terminal.py` 新增断连 overlay 会话丢失文案静态断言 1 项。相关测试 22 项全部通过。

## 2026-08-17 (10)

- feat(web_ui/trainer): 已训练模型列表每行最右侧新增删除按钮（Issue #148）
  - `web_ui/frontend/src/components/trainer/ModelsList.tsx`：模型行操作按钮区（Copy 按钮之后）新增 Trash2 图标按钮，样式与现有按钮一致（`p-1 text-zinc-500 hover:text-red-400 transition-colors`），点击 `e.stopPropagation()` 后 `setConfirmDelete(m)` 打开已有删除确认弹窗；lucide-react 导入补 `Trash2`。删除链路此前已完整实现（`deleteModel` API、`deleting`/`confirmDelete` state、`handleDelete`、确认弹窗及中英文 i18n 文案），本次仅补缺失的触发入口。
  - 测试：`npm run build`（tsc -b + vite build）通过；vitest 全量 89/90 通过，唯一失败的 `TubNavigator.test.tsx` 为并行会话在制修改（stash 本改动后复测同样失败），与本改动无关。

## 2026-08-17 (9)

- feat(web-ui): 完成 Tub Manager（TM）页面中文翻译——`tubnav` 与 `tubeditor` 两个 i18n 命名空间的 zh 词条全部翻译为中文（#157）
  - `web_ui/frontend/src/i18n/messages/tubnav.ts`（TubNavigator + TubLoader + SimulatorConfig）：zh 从"镜像当前中英混合 UI"改为完整中文——导航器标题/副标题、未加载记录、转向/油门、时间轴、拖动中、索引标签、无图像/图像加载失败、首条/上一条/下一条/末条及 aria、播放/停止及 aria、循环/单次播放模式 aria、刷新 aria（`刷新 Tub 记录`）；TubLoader 标题/副标题/路径占位/输入框 aria/浏览/加载/请先加载配置/加载成功/未加载 Tub/选择目录/两类加载失败；SimulatorConfig 的 simHost/simMode/discover/save 四个 aria 与 `notAvailable`（`无`）。文件头注释同步改为"zh 为完整中文翻译"。
  - `web_ui/frontend/src/i18n/messages/tubeditor.ts`（TubEditor）：zh 同上改完整中文——标题/副标题、实时更新、空图表占位/空态、开始/结束索引 aria 与占位、`至`、删除中…/删除、恢复中…/恢复、缩放标签、tooltip 帧/转向/油门、数据集名 转向/油门、六条英文错误提示（范围内无记录/删除失败/恢复失败/范围无效/无可用记录/无有效记录）。文件头注释同步更新。
  - en 词条与组件代码均未改动。
  - 测试同步：`web_ui/frontend/src/components/TubNavigator.test.tsx:39` 刷新按钮定位串从 `Refresh tub records` 改为新 zh aria `刷新 Tub 记录`；前端 vitest 全量 18 文件 90 项通过。

## 2026-08-17 (8)
- style(web_ui/launcher): 三页面语言按钮配色统一为 DC/D 主题按钮（深浅切换）样式（#92 后续统一，与 Firmware v1.8.5 同批）
  - `donkeycar/launcher/server.py`（D 启动页）：`.langBtn` 基类（语言 `#langBtn` 与主题 `#themeBtn` 共用）从 DD 原生 zinc 配色（#27272a/#3f3f46/#d4d4d8，浅色 zinc-100/200/500/900）改为主题按钮配色——深色 `background:#111820;border:1px solid #344154;box-shadow:inset 0 0 0 1px #2b3441;color:#b9c5d3`、hover `#e8edf2`；浅色 `background:#f4f6f9;border-color:#ccd5df;box-shadow:inset 0 0 0 1px #d5dce4;color:#3f4f63`、hover `#1a2330`；32×32 圆形、DD 字体栈、字号/字重不变；`#themeBtn` 的 ID 颜色覆盖与基类重合（保留仅承载布局与图标尺寸），浅色段同步换值。
  - `web_ui/frontend/src/components/LanguageSwitcher.tsx`（DD）：按钮加皮肤类 `language-switcher-btn`；`web_ui/frontend/src/themes/theme-mus4.css` / `theme-light.css` 末尾新增皮肤规则（与并行主题按钮分支同款模式）——深色 #111820/#344154/#2b3441 内圈/#b9c5d3、hover #e8edf2；浅色 #f4f6f9/#ccd5df/#d5dce4 内圈/#3f4f63、hover #1a2330；`outline:none` 抵消 `.bg-zinc-800` 通用 inset 描边，保证 border+内圈双层视觉与 DC/D 一致。
  - 测试：pytest 全量 182 项通过（`.langBtn` 无精确串断言）；vitest `LanguageSwitcher.test.tsx` 6 项通过（不锁类名）；`npm run build` 通过。D/DD 页面主机（192.168.3.41:8090）本轮不在线，D/DD 侧按源码逐值对齐 + DD 构建验证，最终视觉由用户验收。
## 2026-08-17 (7)

- style(web-ui): DD 主题切换按钮显式复刻 DC/D 渲染值，三页面（DC/D/DD）主题按钮逐值一模一样（#140 后续统一收口）
  - `web_ui/frontend/src/components/ThemeSwitcher.tsx`：按钮追加 `theme-switcher-btn` 钩子类，渲染值不再依赖主题 css 对 Tailwind zinc 类的重映射。
  - `web_ui/frontend/src/themes/theme-mus4.css` / `theme-light.css`：新增 `.theme-switcher-btn` 显式规则并置于文件末尾——深色 `outline:none;background:#111820;border-color:#344154;box-shadow:inset 0 0 0 1px #2b3441;color:#b9c5d3`、hover `#e8edf2`；浅色 `#f4f6f9/#ccd5df/#d5dce4/#3f4f63`、hover `#1a2330`。修复要点：ThemeSwitcher 是 `<button>`，此前不匹配主题 css 的 `div.rounded-full.bg-zinc-800.border` 胶囊规则，漏吃到通用 `.bg-zinc-800` 的 `outline:1px solid` 压边描边而非 DC/D 的 border+inset 内圈双层视觉；显式规则同时压过该 outline，与 DC/D 完全一致（DC：Firmware v1.8.4 `.themeButton`；D：launcher `#themeBtn`，本仓 (6) 条目）。图标不变（lucide Moon/Sun 16px、stroke 2、currentColor，深色显月亮/浅色显太阳）。
  - 测试：前端 vitest 全量 90 项通过、`tsc -b` 通过、`npm run build` 通过，构建产物 dist/assets/index-*.css 中 `.theme-switcher-btn` 规则逐值核实与 DC/D 一致。语言按钮不受影响（未动 LanguageSwitcher）。

## 2026-08-17 (6)

- style(launcher): D 启动页主题按钮皮肤与 DD 渲染值逐值统一——三处（DC/D/DD）深浅切换按钮一模一样（#140 后续统一，与 Firmware v1.8.4 同批）
  - `donkeycar/launcher/server.py`：`#themeBtn` 此前复用 `.langBtn` 基类（同批 #149 语言按钮改版后基类变为 DD 原生 zinc 值 #27272a/#3f3f46），主题按钮与 DD 实际渲染脱钩；现改用 ID 覆盖独立锁定 DD 主题按钮渲染值（已核实 DD 构建产物：深色 `theme-mus4` 将 `bg-zinc-800/border-zinc-700/text-zinc-300` 重映射为 #111820/#344154/#b9c5d3，浅色 `theme-light` 为 #f4f6f9/#ccd5df/#3f4f63）：深色 `background:#111820;border-color:#344154;box-shadow:inset 0 0 0 1px #2b3441;color:#b9c5d3`、hover `#e8edf2`；浅色 `background:#f4f6f9;border-color:#ccd5df;box-shadow:inset 0 0 0 1px #d5dce4;color:#3f4f63`、hover `#1a2330`；图标 16px lucide Moon/Sun、深色显月亮/浅色显太阳不变。语言按钮 `.langBtn` 本批不动。
  - 测试同步：`tests/test_launcher_theme_single_button.py` 新增深/浅两套皮肤逐值断言（8 条精确串），pytest 全量 173 项通过。

## 2026-08-17 (5)

- style(launcher): 语言/主题按钮字体逐值复刻 DD（#92 返工：字体栈补齐）
  - `donkeycar/launcher/server.py`：`.langBtn`（语言 `#langBtn` 与主题 `#themeBtn` 共用）补 DD `web_ui/frontend/src/index.css` :root 完整字体栈（`-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",Helvetica,Arial,sans-serif,"Apple Color Emoji","Segoe UI Emoji"`）及 `font-synthesis:none;text-rendering:optimizeLegibility;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale`，按钮渲染字体与 DD 完全一致，不再继承页面级 `system-ui,sans-serif`（用户实测指出 D 按钮字体与 DD 不同）。
  - 测试：launcher 相关 42 项通过（无 `.langBtn` 精确串断言，仅 docstring 提及）；D 启动页设备（192.168.3.41:8090）本轮不在线，按源码逐值对齐，最终视觉由用户验收。

## 2026-08-17 (4)

- fix(launcher): `donkey web` 默认以生产模式启动 Web UI，顶部导航切换从 ~500ms 降到 ~50ms（#135 二轮修复）
  - 根因：`donkey web` 此前始终用 `npm run dev` 起 Vite dev 服务器给最终用户，dev 模式跑未优化代码 + React dev 运行时，实测顶部导航切换 400-550ms（Playwright + CPU profile 证实热点在 chart.js option 解析，为生产构建的 10 倍）；首轮修复（commit 30012564，loadedTubPath 守卫）的前端优化仍在但无法抵消 dev 模式开销，issue 被重开。生产构建由后端直接托管 dist 后实测同一 tub 仅 43-63ms（10k 记录大 tub 同样 43-77ms）。
  - `donkeycar/management/base.py`：
    - `_launch_web_ui` 重写为默认生产模式——新增 `_frontend_needs_build()`（dist/index.html 缺失或 src/public/配置文件比 dist 新则需重建），需要时先 `npm run build`，随后 uvicorn 不带 `--reload` 单进程同时托管 API 与 dist 静态文件（`frontend_port = backend_port`、`frontend_proc = None`）。
    - 新增 `--dev` 参数（Web 与 Drive 命令）：显式传入时走原有逻辑（Vite dev 服务器 + uvicorn `--reload`），供前端开发使用；端口选择逻辑同步调整为仅 dev 模式下独立选 frontend_port。
    - `run()` 的 supervise 进程列表过滤 `None` 前端进程；Drive 命令同步加 `--dev` 防止 `args.dev` AttributeError。
    - `donkeycar/launcher/server.py` 无需改动：实例登记读 `~/.donkeycar/webui.json`，生产模式下登记的 frontend_port 即 backend_port，`/` 探测依然成立。
  - 验证：新增 `tests/test_web_production_mode.py` 9 项（默认生产模式 build→单进程/无 --reload/frontend_port==backend_port、dist 新鲜跳过 build、build 失败 SystemExit、--dev 起 Vite、`_frontend_needs_build` 4 例、`--dev` 默认 False）；pytest 全量 182 项通过、前端 vitest 全量 90 项通过；端到端实测（8020 端口直接调 `_launch_web_ui`）：SPA 与 API 同端口正常服务、无前端子进程。用户需重启现有 Web UI 实例后生效。

## 2026-08-17 (3)

- fix(web-ui): Tub Library（录制视频库）Pin 按钮与删除按钮间距过大，收拢为右侧相邻按钮组（#131 迭代）
  - `web_ui/frontend/src/components/TubLibrary.tsx`：列表行原为 `justify-between` 三段布局，中间文本块与 Pin、删除图标分列两端之间，导致 Pin 悬在行中部、与垃圾桶距离过远；现将 Pin 与删除两个 `<span>` 包进同一 `flex items-center gap-1 shrink-0` 容器，两图标固定相邻、整体靠右，行内文本仍占左侧剩余空间。
  - 测试：前端 vitest 全量 90 项通过、`npm run build` 通过（TubLibrary 置顶/删除既有用例不受影响）。

## 2026-08-17 (2)

- style(launcher): 三页面（DC/D/DD）语言切换按钮样式统一为 DD 原生样式（#92 后续统一，与 Firmware 侧同批）
  - `donkeycar/launcher/server.py`：`.langBtn` 从主题重映射值（#111820 底、#344154 边框、1px #2b3441 内描边、#c3cbd6 字色、13px、hover #e8edf2、active 高亮态）改为逐值复刻 DD `LanguageSwitcher` 原生渲染——32×32 圆形、#27272a 底、1px #3f3f46 边框、12px/600、#d4d4d8 字色、hover #f4f4f5，无内描边/active 态；JS `applyLanguage` 移除 `classList.toggle('active',…)`；浅色覆盖改用同族 zinc 值（底 #f4f4f5、边框 #d4d4d8、字色 #52525b、hover #18181b）。`.langBtn` 同时被 `#themeBtn` 主题按钮复用，主题按钮样式随之统一；样式块注释同步更新为 DD 原生值说明。
  - 测试同步：launcher 相关 42 项通过（`test_launcher_language_autodetect.py`/`test_launcher_menu_actions.py`/`test_launcher_theme_single_button.py`，后两者仅 docstring 提及 `.langBtn` 无样式断言）。

## 2026-08-17 (1)

- feat(web-ui,launcher): 深浅主题切换改为静音式单按钮，单击深/浅互切，默认跟随浏览器深浅（#140）
  - `web_ui/frontend/src/components/ThemeSwitcher.tsx`：从"浅色/跟随系统/深色"三段式分段控件改为静音式单图标按钮（与 #139 语言切换同形态：32×32 圆形胶囊）——图标反映当前生效主题（深色显月亮、浅色显太阳，lucide `Moon`/`Sun`），单击在深↔浅之间互切；默认跟随浏览器 `prefers-color-scheme` 与 localStorage 持久化（沿用键 `donkeydrifter.ui.theme`）由 `src/lib/theme.ts` 已有实现承担，未手动单击前不写入存储、实时跟随浏览器切换，手动单击后持久化显式选择且不再跟随；`aria-label` 提示切换目标主题。
  - `web_ui/frontend/src/components/ThemeSwitcher.test.tsx`：测试重写为单按钮断言 8 例——月亮/太阳图标与 aria-label 反映当前主题、单击切浅色并持久化、双击回深色、默认跟随系统深浅实时变化（跟随期间不写存储）、手动单击后不再跟随系统、挂载恢复持久化皮肤、非法存储值回退跟随系统。
  - `donkeycar/launcher/server.py`（D 启动页 :8090）：移除 `#themeTabs` 浅色/跟随系统/深色三态菜单及 `renderThemeTabs`、`theme.light/auto/dark` 双语文案，改为 `#themeBtn` 静音式单图标按钮（复用 `.langBtn` 圆形样式，内联 lucide 太阳/月亮 SVG 按 `html[data-theme]` 显隐），单击 `toggleTheme()` 按当前生效主题取反并经 `setTheme` 持久化；`renderThemeBtn()` 同步更新 aria-label/title 为切换目标主题（新增 `theme.toggleLight/toggleDark` 双语文案）；首屏防闪烁与 'system' 态跟随浏览器逻辑不变。
  - 测试：前端 vitest 全量 90 项通过、`tsc -b` 通过；新增 `tests/test_launcher_theme_single_button.py` 源码断言 3 例（单按钮入口与三态移除、toggle 深浅互切与持久化、默认跟随浏览器/手动后不跟随），pytest 全量 173 项通过。

## 2026-08-16 (19)

- feat(web-ui,launcher): 语言切换改为静音式单按钮，默认跟随浏览器语言（#139）
  - `web_ui/frontend/src/components/LanguageSwitcher.tsx`：从中文/English 两段式 pill 控件改为单图标按钮——显示当前语言（中文显示"中"、英文显示"EN"），单击在中/英之间切换；`aria-pressed` 反映当前是否中文、`aria-label` 提示切换目标语言；跟随浏览器语言与 localStorage 持久化逻辑由 i18n Provider 已有实现，无需改动。
  - `web_ui/frontend/src/components/LanguageSwitcher.test.tsx`：测试同步更新为单按钮断言（按钮文字、aria-pressed、单击切换、双击回切、持久化、浏览器语言跟随），6 项通过。
  - `donkeycar/launcher/server.py`（D 启动页 :8090）：移除桌面端 `langTabs` 分段式语言切换和移动端 `langFab`+`langMenu` 弹出菜单，统一改为 `#langBtn` 单按钮——显示"中"/"EN"，单击调 `toggleLanguage()` 切换；新增 `.langBtn` CSS（深色/浅色变体）、移除 `.langTabs`/`.langFab`/`.langMenu` 全部相关 CSS 与 JS（`toggleLanguageMenu`/`closeLanguageMenu`）；`applyLanguage()` 中更新按钮文字与 active 状态；跟随浏览器语言与 localStorage 持久化逻辑不变。
  - DD 前端 `npm run build` 通过、`npm test` 93 项通过；D 启动页 `pytest tests/test_launcher_language_autodetect.py` 2 项 + `tests/test_launcher_menu_actions.py` 37 项通过。

## 2026-08-16 (18)

- feat(web-ui): Pilot Arena 自动扫描模型，唯一模型时自动选中并加载预测（#136）
  - `web_ui/frontend/src/pages/PilotArenaPage.tsx`：
    - 新增 `autoScanDoneRef`/`autoLoadDoneRef` 两个 ref 跟踪每个 viewer 的自动扫描/自动加载状态。
    - 新增 useEffect：当 `hasRecords` 且 `configPath` 可用时，自动为每个未扫描过的 viewer 调用 `refreshModels`（即自动执行"扫描模型"），无需手动点击。
    - 新增 useEffect：扫描结果只有一个模型时（`models.length === 1`），自动调用 `loadViewer`（即自动执行"加载并预测"），画面上出现预测转向线。
    - 多个模型时只自动扫描填充列表，不自动选择/加载，保留现有手动流程。
    - `unloadViewer` 中同步清理 `autoScanDoneRef`/`autoLoadDoneRef`，移除 viewer 后重建不会残留状态。
  - 前端 `npm run build` 通过。

## 2026-08-16 (17)

- feat(web-ui): 完成 Trainer 页面中文翻译（#137）
  - `web_ui/frontend/src/i18n/messages/trainer.ts`：全部 zh 词条（约 65 条）从英文原文翻译为中文，包括标题、标签页、配置项、日志、状态、删除确认弹窗等；带插值参数的词条（`{name}`/`{count}`/`{path}`/`{loss}`/`{message}`）占位符保持不变；状态标签译为 待开始/运行中/已完成/失败/已停止。
  - 文件头注释更新：原"zh values mirror the current UI strings verbatim"已失效，改为说明 zh 为完整中文翻译。
  - en 词条保持不变。前端 `npm run build` 通过。

## 2026-08-16 (16)

- feat(web-ui): DD 顶部导航标签顺序调整为 Drive → TM → Trainer → PA → CC（#138）
  - `web_ui/frontend/src/components/Layout.tsx`：`navItems` 数组重新排序为 Drive（`/drive`）→ Tub Manager（`/`）→ Trainer（`/trainer`）→ Pilot Arena（`/pilot`）→ Car Connector（`/connector`），桌面导航与手机汉堡菜单共用该数组同步生效；路由路径不变，仅改显示顺序。
  - 前端 `npm run build` 通过。

## 2026-08-16 (15)

- feat(launcher): D 页（launcher 菜单）1-5、7-10 号菜单项全部接线，点按不再弹"未实现"，与 TUI 各命令行为对齐（#126）
  - `donkeycar/launcher/server.py` 后端新增（对齐 `donkeycar/management/tui.py` 各 Command，不 import tui 依赖链，按需精简实现）：
    - 菜单 1 `_create_car`：`donkey createcar --path ~/projects/<folder>`，项目名白名单 `^[A-Za-z0-9_\-]+$`（400）、目录已存在不覆盖（409）、成功后切换当前项目并持久化 `last_project_path`（写 `~/.donkeyrc`，失败静默不阻塞）。
    - 菜单 2 `_open_project` + `_find_valid_projects_local`：只允许打开 `~/projects` 下一层的有效项目（manage.py+myconfig.py），越界或无效一律 400。
    - 菜单 3 `_clear_data`：data 不存在/为空返回 skipped；可选 zip 备份到 `data_backups/data_backup_<ts>.zip`；清空走"先 move 到 `.data_trash_<ts>` 再 rmtree"，任一步失败自动回滚（对齐 TUI trash 逻辑）。
    - 菜单 4 `_backup_data`：tar.gz 备份到 `<project>/data_cache/data-<yymmdd>-<NNN>.tar.gz`（arcname 相对路径不带 `data/` 前缀，序号当日递增）；磁盘剩余 < 数据体积×1.1+1MB 时拒绝（507），失败清理半成品。
    - 菜单 5 `_restore_data` + `_list_backups`：备份名白名单 `^data-\d{6}-\d{3}\.tar\.gz$`（防穿越）、损坏归档校验（500）、解压前磁盘检查、现有 data 先移 trash 失败回滚；`_is_safe_member_local` 拒绝绝对路径/`..` 穿越；兼容 `tar czf x.tar.gz data/` 带前缀归档（全成员 data/ 前缀则解到上级目录）。与 TUI 恢复的已知差异：不做 DataMigrator 嵌套数据整理（flatten_nested_data，依赖链重），按原样恢复。
    - 菜单 7 `_launch_web_ui`：与 #127 实例登记打通——`find_live_instance()` 存活直接复用返回 URL；否则默认端口 8000/5188 新起 `donkey web`（捆绑 web_ui --path），PID 写入登记文件供 Drive 链路清理复用。
    - 菜单 8/9/10 终端命令下发（前端经 terminal `?cmd=` 执行，后端提供支撑端点）：`GET /api/train/next-model` 扫 `<project>/models/pilot_<数字>` 取 max+1 供菜单 9 拼 `donkey train --tub ./data --model ./models/pilot_N --type linear`；菜单 8 为 `cd '<project>' && donkey ui`，菜单 10 为 `python -m donkeycar.management.train_online`。
    - 新路由：GET `/api/projects`、`/api/data/backups`、`/api/train/next-model`；POST `/api/launch/web`、`/api/createcar`、`/api/projects/open`、`/api/data/clear|backup|restore`；`LauncherHandler._read_json_body()` 统一 JSON 请求体解析（坏 JSON 400）。
  - `donkeycar/launcher/server.py` 前端（MENU_HTML）：
    - `selectItem` 全 12 项分发接线（1→createCar、2→openProject、3→clearData、4→backupData、5→restoreData、7→launchWebUI、8→launchDonkeyUI、9→launchTrainLocal、10→launchTrainOnline），删除 `overlay.notImplemented` 分支（I18N 键保留作无害兜底）。
    - 新增 I18N zh/en 键：`overlay.startingWeb/working/done`、`menu.createcar.prompt/exists`、`menu.open.prompt/none`、`menu.clear.confirm/confirmNoBackup`、`menu.train.openTerminal`、`menu.donkeyui.openTerminal`。
    - 交互：createCar prompt 项目名+已存在探测询问覆盖；openProject 列表编号选择；clearData 两次确认（含"不备份继续"分支）；restoreData 备份列表选择+确认；launchWebUI 复刻 Drive 的 30×1s 就绪轮询后跳转；8/9/10 经 `window.open('/terminal?cmd='+encodeURIComponent(cmd))` 下发。
  - `donkeycar/launcher/terminal_static/terminal.html`：支持 `?cmd=` 查询参数（decodeURIComponent + `+`→空格），WebSocket hello 之后自动发送并回显该命令一次，用于菜单 8/9/10 的终端命令自动执行。
  - 测试：新增 `tests/test_launcher_menu_actions.py` 37 项——`_launch_web_ui`（复用/新起/PID 登记/缺 donkey 二进制）、`_create_car`（非法名/已存在 409/成功切换项目/命令行与 TUI 一致/失败带 stderr）、`_open_project`（越界/无效/成功）、数据往返（backup→clear→restore 文件回来）、restore 穿越名/损坏归档/data 前缀归档、`_next_train_model` 递增、HTTP 端点（内存 ThreadingHTTPServer 全路由）、前端静态断言（接线函数、I18N 键、terminal.html autoCmd）；fixture 统一打桩 `_save_last_project_path_local` 防止测试写真实 `~/.donkeyrc`。全量 `pytest tests/` 136 项通过。
  - 涉及文件：`donkeycar/launcher/server.py`、`donkeycar/launcher/terminal_static/terminal.html`、`tests/test_launcher_menu_actions.py`（新增）

- feat(web-ui): 录制视频库支持 Pin 置顶（#131 迭代）
  - `web_ui/frontend/src/components/TubLibrary.tsx`：每条录制项右侧（删除图标左边）新增 Pin 按钮（lucide `Pin`）——点击置顶到列表最上方，已置顶项图标填充并高亮 cyan 色，再点取消；置顶组与非置顶组内部均保持时间降序（最新在上）。
  - 置顶状态按 tubPath 存 `localStorage`（key `tubLibrary.pinned.<tubPath>`，存 session_id 数组），纯前端状态、不涉及后端 API；localStorage 不可用（隐私模式等）时置顶仅本次会话内生效，不报错。删除录制时同步从置顶集合移除该 session。
  - i18n：`tublibrary.ts` 新增 `tubLibrary.pinAria`（置顶这条录制 / Pin this recording to top）、`tubLibrary.unpinAria`（取消置顶 / Unpin this recording）。
  - 测试：`TubLibrary.test.tsx` 新增置顶用例——点击较旧录制的 Pin 后移到列表首位并写入 localStorage，取消置顶后恢复最新在前顺序；前端 `npm test` 18 文件 92 例、`npm run build` 均通过。
  - 涉及文件：`web_ui/frontend/src/components/TubLibrary.tsx`、`web_ui/frontend/src/components/TubLibrary.test.tsx`、`web_ui/frontend/src/i18n/messages/tublibrary.ts`

## 2026-08-16 (14)

- fix(complete,actuator): RC 手动驾驶时将手柄实际控制量合并进 tub 录制通道（#133）
  - 根因：固件 MANUAL 模式下车由 RC 接收机直驱，Web/手柄通道 `user/angle`、`user/throttle` 全程为 0，TubWriter 只录这两个键，导致问题 tub（11656 帧）9942 条有效记录全为 0.0、Tub Editor 曲线贴 0 轴；固件串口 T 帧上行的实际控制量已由 ArdRc 发布到 `rc/steering`、`rc/throttle`（-1..1）但未进录制通道。
  - `donkeycar/parts/actuator.py`：新增 `RcRecordMerge` part——仅 `rc/mode==0`（MANUAL）、非 park 锁定且 rc 值有效（数值、非 bool）时用 `rc/steering`、`rc/throttle` 覆盖 `user/angle`、`user/throttle` 供 TubWriter 记录；SEMI/FULL AUTO、park、`rc/mode` 未知（仿真等）时原样透传，不改变既有录制行为，避免"RC 怠速值覆盖跳 0"问题复发。
  - `donkeycar/templates/complete.py`：TubWriter 注册前接入 RcRecordMerge（与 mycar 运行实例对齐）；ARDUINO_CONTROLLER 传动链补齐 ArdRc 块（发布 `rc/steering`、`rc/throttle`、`rc/mode`、`rc/park`）。
  - 不新增 tub 字段，既有 tub manifest inputs/types 一致性断言不受影响；修复不回溯历史数据，既有全 0 tub 需重新录制；SEMI_AUTO（rc/mode==1）录制仍走旧逻辑。
  - 测试：新增 `tests/test_rc_record_merge.py` 8 项单元测试（MANUAL 合并、SEMI/FULL AUTO/park/未知模式/无效值透传、bool 拒绝、模板接线断言），全部通过；真实 donkeycar Vehicle 循环仿真验证 MANUAL 下合并、SEMI 下透传；回归 `pytest tests` 107 项通过、与改动相关套件（test_actuator/test_template/test_tubwriter/test_vehicle/test_launch）39 过 2 跳、`donkeycar/tests` 排除 test_launch 全过——完整连跑在本机及 origin/Tony 基线均于 test_provisioning 附近忙转挂起，系既有环境问题，与本次改动无关。
  - 涉及文件：`donkeycar/parts/actuator.py`、`donkeycar/templates/complete.py`、`tests/test_rc_record_merge.py`（新增）

## 2026-08-16 (13)

- feat(web-ui): Loader 多 mycar 项目时自动 Browse 上次用过的项目（#129 增强）
  - 后端 `web_ui/backend/routers/config.py`：新增 `~/.donkeycar_web_loader.json` 状态文件（命名惯例同 connector 的 `~/.donkeycar_web_connector.json`）——`POST /api/config/load` 加载成功后记录 `last_car_path`；`GET /api/config/discover_projects` 返回 `last_project`（上次项目在扫描根之外但仍含 config.py+manage.py 时一并并入 projects 供前端参考；状态文件损坏/缺失时回退 None 不报错）。
  - 前端 `web_ui/frontend/src/components/ConfigLoader.tsx`：自动发现逻辑扩展——唯一项目→自动加载；多个项目且 `last_project` 在列表中→自动加载上次项目（与 localStorage 记忆互补，跨浏览器/清缓存后仍有效）；否则回退手动 Browse。`api.ts` 的 `discoverProjects` 返回类型同步补 `last_project`。
  - fix(web-ui): 顺手修复 `handleManualLoad` 中硬编码的本机路径 `/home/dkc/projects/mycar/data` 特判——其它机器上曾持久化该 tub 路径时会被误判为“需要保留的旧 tub”，现仅按 `<path>/data` 归一化比较。
  - 测试：后端 `test_config.py` 新增 `last_project` 链路 1 项（无记录 None→load 成功记录→扫描根之外并入→损坏文件回退）；前端 `ConfigLoader.test.tsx` 扩至 6 项（新增：多项目时自动加载上次项目、上次项目不在列表回退手动）。后端全量 pytest 77 项、前端全量 vitest 86 例（16 文件）、`tsc --noEmit` 均通过。
  - 涉及文件：`web_ui/backend/routers/config.py`、`web_ui/backend/tests/test_config.py`、`web_ui/frontend/src/services/api.ts`、`web_ui/frontend/src/components/ConfigLoader.tsx`、`web_ui/frontend/src/components/ConfigLoader.test.tsx`
- feat(web-ui): 进入录制视频库后自动选中最新一条录制
  - `web_ui/frontend/src/components/TubLibrary.tsx`：`refreshSessions` 拉到列表后，若当前无选中（或选中的录制已不存在，如刚被删除）则自动选中 `sessions[0]`（API 已按最新在前排序），进入页面即可直接预览最新录制；已有有效选中时保持不变。
  - 测试：新增 `web_ui/frontend/src/components/TubLibrary.test.tsx` 2 项——加载后自动请求最新录制的记录并显示帧计数、未加载 tub 时不请求列表；前端 `npm run build` 无错误，`npm test` 18 文件 89 例通过。
  - 涉及文件：`web_ui/frontend/src/components/TubLibrary.tsx`、`web_ui/frontend/src/components/TubLibrary.test.tsx`（新增）

## 2026-08-16 (12)

- fix(web-ui,templates): 修复 Tub Navigator 播放录制视频卡顿（#128），并让 WEBCAM 接受 CAMERA_FRAMERATE 配置
  - 排查结论（issue 内已实测）：录制侧帧间隔均匀（17ms 中位、>25ms 零次）无丢帧；卡顿全部在播放侧——后端每帧全量磁盘读 + 前端帧推进与图片加载解耦导致画面冻结跳帧。
  - 后端 `web_ui/backend/routers/tub.py`（`GET /api/tub/image`）：
    - 新增按 `(mtime_ns, size)` 校验的字节级 LRU 缓存（128 MiB 预算），命中直接从内存回图不再碰磁盘；超预算淘汰最旧条目。
    - 响应加 `ETag` 与 `Cache-Control: private, max-age=86400`，支持 `If-None-Match` 304 协商；重复播放同一 tub 时浏览器 disk cache 参与命中。
    - 原先两处 `FileResponse` 路径统一收敛为缓存读取逻辑，404 分支不变。
  - 前端 `web_ui/frontend/src/components/TubNavigator.tsx`：
    - 预取窗口 10 帧 → 60 帧（PREFETCH_AHEAD，覆盖 ~1s），并用 pump 模式加并发上限（PREFETCH_CONCURRENCY=6，对齐 HTTP/1.1 同源连接数），预取完成一个补位一个，不再几十个请求挤占连接。
    - 解码位图缓存复用 #135 的 LRU 上限（`touchImageCache`，240 条、命中刷新位置、超限淘汰最旧），预取写入同一缓存，长 tub 播放不再无限吃内存。
    - FPS 角标改为统计 canvas 实际换帧率（drawImage 时按 URL 去重累计），画面冻结时角标如实下降，可自检卡顿；原先统计 rAF 回调频率（恒 ~60）的问题一并去除。
    - 绘制路径去掉多余的一层 `requestAnimationFrame` 包裹，未就绪帧的加载回调直接绘制，减少一帧延迟。
  - 附带修复 `donkeycar/templates/complete.py`、`basic.py`：`Webcam` 创建传入 `framerate=cfg.CAMERA_FRAMERATE`（原先 WEBCAM 用默认 20Hz，60fps 主循环里同一帧被重复记录约 3 次）；顺带修复 complete.py stereo 分支 `Webcam(..., iCam=...)` 传了不存在的参数（一实例化即 TypeError）改为 `camera_index=0/1`，basic.py 用 `getattr(cfg, 'CAMERA_INDEX', 0)` 兜底（cfg_basic 未定义该项）。
  - 测试：新增 `tests/test_tub_image_cache.py` 5 项（ETag/Cache-Control 头、缓存命中不读磁盘、If-None-Match 304、文件变更失效、LRU 超预算淘汰）与 `tests/test_webcam_framerate.py` 3 项（complete/basic 模板 Webcam 必传 framerate、stereo 分支不得再用 iCam）；rebase 到 #135 后发现其漏更新的 `tests/test_tub_manager_auto_refresh.py` 断言仍指向旧路由刷新逻辑（在 Tony 上即失败），同步改为断言 `loadedTubPath`/`tubRefreshToken` 新逻辑；前端 `tsc -b --noEmit` 通过、vitest 89 例（18 文件）通过、eslint 无告警、后端 `tests/` 125 项全过。
  - 涉及文件：`web_ui/backend/routers/tub.py`、`web_ui/frontend/src/components/TubNavigator.tsx`、`donkeycar/templates/complete.py`、`donkeycar/templates/basic.py`、`tests/test_tub_image_cache.py`（新增）、`tests/test_webcam_framerate.py`（新增）、`tests/test_tub_manager_auto_refresh.py`

## 2026-08-16 (11)

- feat(web-ui): 录制视频库列表改为最新录制排在最上面
  - `web_ui/backend/routers/tub.py`：`GET /sessions` 返回排序由 `first_index` 升序改为降序（最新一次录制排第一，最旧排最后）；前端 TubLibrary 按返回顺序渲染，无需改动。
  - 测试：`web_ui/backend/tests/test_tub_sessions.py` 分组测试补充排序断言（最新的 `first_index` 更大、必须排在首位）；4 项通过。
  - 涉及文件：`web_ui/backend/routers/tub.py`、`web_ui/backend/tests/test_tub_sessions.py`

## 2026-08-16 (10)

- revert(tub-editor): 回退 #130 的选区框最小宽度修复，恢复 TubEditor 原有选区绘制与单击判定逻辑（用户要求撤销）
  - `git revert d63fe8e2`：`web_ui/frontend/src/components/TubEditor.tsx` 恢复原始实现（移除 `MIN_SELECTION_BOX_WIDTH` 最小框宽与 `handleMouseUp` 的 `indexDelta === 0` 判定），删除随该修复新增的 `web_ui/frontend/src/components/TubEditor.test.tsx`；同时移除原「2026-08-16 (4)」中对应的日志条目。
  - 测试：删除测试文件后不影响其它用例，前端 vitest 全量通过。
  - 涉及文件：`web_ui/frontend/src/components/TubEditor.tsx`、`web_ui/frontend/src/components/TubEditor.test.tsx`（删除）

## 2026-08-16 (9)

- feat(web-ui): 录制视频库移除循环播放按键，改为始终循环播放
  - `web_ui/frontend/src/components/TubLibrary.tsx`：删除 `isLooping` 状态与播放/暂停旁的循环切换按钮（含 `Repeat` 图标导入），播放到最后一帧后始终回到第 0 帧继续播放，不再播完自动停止；循环相关 i18n 键（`tub.loop*`）为 Tub Navigator 共用，未改动。
  - 测试：无已入库测试断言该循环按钮；前端 `npm run build`（tsc -b + vite）无错误，`npm test` 18 文件 89 例通过。
  - 涉及文件：`web_ui/frontend/src/components/TubLibrary.tsx`

## 2026-08-16 (8)

- fix(web-ui): 修复 DD 顶部导航（Tub Manager / Trainer / Drive 等）切换非常卡顿的问题（#135）
  - 根因：`TubManagerPage` 的 effect 以 `location.pathname === '/'` 为条件，每次从其它页切回 Tub Manager 都全量重拉整个 tub（上千条记录时需全量下载 + 整包写 store + TubNavigator/TubEditor 两个重组件全量重渲染，期间还有全屏 loading 遮罩），切换体验即"每次都卡"。
  - `web_ui/frontend/src/store/useStore.ts`：新增 `loadedTubPath`（当前 store 中已加载完成的 tub 路径标记，`setTub` 时写入）与 `tubRefreshToken`（手动刷新令牌）及 `requestTubRefresh()`（清空已加载标记并递增令牌）；均不参与 persist。
  - `web_ui/frontend/src/App.tsx`：`TubManagerPage` 改为仅在 `tubPath !== loadedTubPath`（首次加载或 tub 变更，含刷新页面后从持久化恢复 tubPath 的场景）或 `tubRefreshToken` 递增（手动刷新）时拉取数据，并补 `cancelled` 清理避免组件卸载后 setState；顶部导航来回切换不再触发网络请求与全量重渲染。
  - `web_ui/frontend/src/components/TubNavigator.tsx`：图片缓存增加上限 `MAX_IMAGE_CACHE_ENTRIES = 240` 与 LRU 淘汰（Map 插入序，命中刷新位置、超限淘汰最旧），长会话播放/预取不再让缓存无限增长拖慢切换；播放控制行新增手动"刷新"按钮（调用 `requestTubRefresh`，loading 时旋转禁用），替代原来导航切换隐式重拉的刷新途径。
  - `web_ui/frontend/src/i18n/messages/tubnav.ts`：新增 `tub.refresh` / `tub.refreshAria` / `tub.refreshTitle` 中英文案。
  - 测试：新增 `web_ui/frontend/src/App.test.tsx`（4 例：首次加载拉取并标记 loadedTubPath、已加载不重拉、requestTubRefresh 触发重拉、无 tubPath 不拉取）与 `web_ui/frontend/src/components/TubNavigator.test.tsx`（1 例：刷新按钮触发 requestTubRefresh 且清空 loadedTubPath）；前端 vitest 全量 83 例（16 文件）通过，`npm run build`（tsc -b + vite）无错误。
  - 涉及文件：`web_ui/frontend/src/App.tsx`、`web_ui/frontend/src/store/useStore.ts`、`web_ui/frontend/src/components/TubNavigator.tsx`、`web_ui/frontend/src/i18n/messages/tubnav.ts`、`web_ui/frontend/src/App.test.tsx`（新增）、`web_ui/frontend/src/components/TubNavigator.test.tsx`（新增）

## 2026-08-16 (7)

- feat(web-ui): Tub 页面新增"录制视频库"分区，按 session 列出每次录制的视频并可整条播放/删除（#131）
  - 需求：Web UI Tub 页面新增录制视频库——左侧列出 mycar 录制的每条视频（同一 Tub 内按 `_session_id` 分组，一次 drive 启动 = 一条录制），右侧播放器逐帧播放该 session 图像，支持整条删除（带确认弹窗），删除后 Navigator/Editor 等其它板块不再显示对应帧。
  - 后端 `web_ui/backend/routers/tub.py`：
    - `GET /sessions?tubPath=`：以只读 Tub 迭代 live records 按 `_session_id` 分组，返回每条录制的 `session_id`/`record_count`/`first_index`/`last_index`/`start_time_ms`/`end_time_ms`，按 `first_index` 排序（写入时间序），用完即 `close()`。
    - `GET /session_records?tubPath=&sessionId=`：返回单条录制全部 live records，供播放器逐帧取图（图片仍走既有 `GET /api/tub/image`，未改动）。
    - `POST /delete_session`：收集该 session 所有 `_index`（空则 404），用可写 Tub 实例调 `delete_records(indexes)` 做 manifest 软删（与逐帧删除同机制）；若删的是当前已加载 tub，则重建全局 `current_tub`/`current_records`，其它板块数据即刻同步。
    - 新增 `SessionDeleteRequest`（`tub_path` + `session_id`）Pydantic 模型。
  - 前端：
    - `web_ui/frontend/src/services/api.ts`：新增 `TubSession`/`TubRecord` 接口与 `listTubSessions`/`getSessionRecords`/`deleteTubSession` 三个 API 函数。
    - `web_ui/frontend/src/components/TubLibrary.tsx`（新增）：左列 session 列表（选中高亮、每项带删除图标、显示 `_timestamp_ms` 格式化的开始时间与帧数）+ 右侧 canvas 播放器：预取 30 帧（Navigator 仅 10 帧）、图片未就绪时停在当前帧等待而不跳帧（吸取 #128 播放卡顿教训）、支持播放/暂停/循环/逐帧步进/进度条拖动；底部整条删除按钮触发自绘确认弹窗（fixed 遮罩 + zinc-900 卡片，项目无现成 Modal 组件），确认后调 `delete_session` 并刷新列表 + 重新 `loadTub` 同步全局 store。
    - `web_ui/frontend/src/i18n/messages/tublibrary.ts`（新增）：zh/en 各 19 条 `tubLibrary.*` 文案；`web_ui/frontend/src/i18n/messages/index.ts` 注册该模块。
    - `web_ui/frontend/src/App.tsx`：TubManagerPage 中 `<TubNavigator />` 之后插入 `<TubLibrary />`。
  - 测试：新增 `web_ui/backend/tests/test_tub_sessions.py` 4 项——两次独立 Tub 实例各写 3+2 帧模拟两条录制，验证 sessions 列表分组/排序/时间戳、session_records 过滤、delete_session 软删后 sessions 与全局加载记录均不再包含已删帧（注意同一 Tub 实例不会产生新 session_id，测试须每次新开实例）；4 项通过。前端 `npm run build`（tsc -b + vite）无错误，`npm test` 14 文件 78 例通过。
  - 涉及文件：`web_ui/backend/routers/tub.py`、`web_ui/backend/tests/test_tub_sessions.py`（新增）、`web_ui/frontend/src/services/api.ts`、`web_ui/frontend/src/components/TubLibrary.tsx`（新增）、`web_ui/frontend/src/i18n/messages/tublibrary.ts`（新增）、`web_ui/frontend/src/i18n/messages/index.ts`、`web_ui/frontend/src/App.tsx`
## 2026-08-16 (6)

- fix(launcher): D 页点 6 打开 Drive 后页面加载不出来——跳转不等前端就绪 + 端口可能被二次改选（#134）
  - 根因：`_launch_drive` 在 `Popen` 返回后立即报 launched，跳转页重定向到尚未监听的 vite 端口（Vite 冷启动/首次 npm 依赖检查需数秒甚至更久），浏览器连接拒绝/白屏；且 launcher 预选端口与 `donkey web` 内部二次改选后的实际端口可能不一致，跳转到错误端口。
  - `donkeycar/launcher/server.py`：新增 `_wait_for_web_ready(web_proc, frontend_port, backend_port, timeout=90s)`——等 `donkey web` 就绪写入实例登记（`~/.donkeycar/webui.json`，登记里是 vite/uvicorn 实际监听端口，天然覆盖端口被占二次改选；以 `started_at` 不早于本次调用起点判定为本次启动写入），再 GET 实际 frontend_port 的 `/` 直到可访问才返回；web 进程提前退出或超时不报错，透出 warning 照常跳转。
  - `_launch_drive`：新起 web 时先等就绪、回读实际端口再返回 launched（跳转页拿到响应时前端已能服务页面）；车进程改在就绪后启动，`DRIVE_API_SERVER_URL` 连接实际后端端口；返回 url/端口均为实际值；复用存活实例路径行为不变（不起 web、不等就绪）。
  - `donkeycar/webui_instance.py`：新增 `probe_http_ok` 公开别名（原 `_probe_http_ok`），供 launcher 跨模块复用 HTTP 探测。
  - 测试：新增 `tests/test_launcher_drive_launch.py` 9 项——`_wait_for_web_ready` 新登记回读实际端口、vite 二次改选跟随登记端口、web 提前退出带 warning、登记不出现超时带 warning、早于调用起点的陈旧登记不认；`_launch_drive` 冷启动顺序（先 web 后车、env 连实际后端、url 用实际前端端口）、就绪超时透出 warning、复用实例跳过 web 与等待、无 mycar 项目直接报错；全量 `pytest tests/` 108 项通过。
  - 涉及文件：`donkeycar/launcher/server.py`、`donkeycar/webui_instance.py`、`tests/test_launcher_drive_launch.py`（新增）

## 2026-08-16 (5)

- feat(web-ui): Loader 自动发现唯一 mycar 项目并自动加载，无需人工 Browse（#129）
  - 后端 `web_ui/backend/routers/config.py`：新增 `GET /api/config/discover_projects?root=<dir>` 接口与 `find_car_projects()` 扫描函数——BFS 扫描 root 下含 `config.py` + `manage.py` 的目录（默认 root 为用户 home，最多下探 2 层，跳过隐藏目录与 `node_modules`/`venv`/`__pycache__` 等），返回 `{projects, count}`；扫描经 `run_in_threadpool` 不阻塞事件循环。
  - 前端 `web_ui/frontend/src/services/api.ts`：新增 `discoverProjects()` API 封装。
  - 前端 `web_ui/frontend/src/components/ConfigLoader.tsx`：新增自动发现 effect——store 无 `config` 且无已记住 `configPath` 时调用 `discoverProjects()`，恰好发现 1 个项目则复用 `handleBrowserSelect` 链路自动加载（config + `<carPath>/data` tub）；多个项目或扫描失败时静默回退现有手动 Browse 流程；`useRef` 防重复触发。
  - 测试：后端 `web_ui/backend/tests/test_config.py` 新增 3 项（唯一项目发现、多项目/无项目、隐藏目录跳过+项目内不下钻+缺 manage.py 不算项目）；前端新增 `web_ui/frontend/src/components/ConfigLoader.test.tsx` 4 项（唯一项目自动加载 config+tub、多项目不自动加载、发现失败静默回退、已有 configPath 跳过发现）。后端全量 pytest 76 项、前端全量 vitest 82 例（15 文件）、`tsc --noEmit` 均通过。
  - 涉及文件：`web_ui/backend/routers/config.py`、`web_ui/backend/tests/test_config.py`、`web_ui/frontend/src/services/api.ts`、`web_ui/frontend/src/components/ConfigLoader.tsx`、`web_ui/frontend/src/components/ConfigLoader.test.tsx`（新增）

## 2026-08-16 (3)

- fix(launcher): 修复 DC/DD/D 三处「打开 Kimi Code Web」与 DC 终端手动 `/web` 返回的链接打不开的问题（#125）
  - 根因：`kimi_web.py` 返回的 URL host 是上位机本机视角的 `localhost`/`127.0.0.1`，消费方是用户电脑/手机上的浏览器，`localhost` 指向浏览器自己自然打不开；且冷启动的 `kimi web` 默认只绑回环（banner `Network: off`），即使改写 host 局域网也访问不到。
  - `donkeycar/launcher/kimi_web.py`：
    - 冷启动命令改为 `kimi web --no-open --host`（`--host` 裸传 = 绑 `0.0.0.0`，实测 kimi ≥ 0.36 支持），局域网设备可达。
    - 新增 `_is_loopback_host`/`_lan_url`：返回前把回环/通配 host（`localhost`/`127.x`/`::1`/`0.0.0.0`）改写为本机局域网 IP（复用配网模块 `detect_lan_ip` 的 VPN/TUN 感知探测），保留端口、路径与 `#token=` 片段；探测不到局域网 IP 或 host 本就远程可达时原样返回。复用、冷启动、失败兜底三条返回路径统一改写。
    - `_live_instance_url`：登记 host 是回环的实例（如 TUI 内嵌 server）先对局域网 IP 探测 `/api/v1/meta`，通了（实际监听 0.0.0.0 只是登记写了 127.0.0.1）改用局域网 host 返回；不通视为不可复用，由调用方另拉监听 0.0.0.0 的新实例。
  - `donkeycar/launcher/server.py`：`_handle_launch_kimi_code_web` docstring 同步（移除过时的"注入 /web"描述，注明 URL 已改写为局域网 IP）；端点行为无变化，DC/DD/D 三端消费同一返回值，改 launcher 一处全部修复。
  - 测试同步：`tests/test_launcher_kimi_web.py` 新增 `_fake_lan_ip` autouse fixture 隔离真实网络探测；新增 `TestLanUrl` 6 项（回环/通配 host 识别、改写保留端口与 token、远程 host 不动、无局域网 IP 原样返回）与 `_live_instance_url` 回环实例双探测 3 项；既有断言按局域网改写更新（复用/冷启动/兜底返回 URL、启动命令含 `--host`）；全量 `pytest tests/` 108 项通过。
  - 端到端实测：本机（192.168.3.x 网段）真实拉起 `kimi web`，返回 `http://192.168.3.57:<port>/#token=...`，局域网 IP 上 HTTP 探测可达（未带 token 的 `/api/v1/meta` 返回 401，证明服务真实监听）。
  - 涉及文件：`donkeycar/launcher/kimi_web.py`、`donkeycar/launcher/server.py`、`tests/test_launcher_kimi_web.py`

## 2026-08-16 (2)

- fix(launcher,web,management): Web UI 实例登记与复用，修复 D 页按 6 号（Drive）后 Tub Manager 打不开、需再按 7 号（Web）才可用的问题（#127）
  - 根因：launcher `_launch_drive` 启动前 `pkill -f "donkey web"` 与 PID 文件全杀互杀已运行的 Web UI；且各链路动态选端口（backend 从 8100 漂移），与 7 号默认端口（8000/5188）不一致，浏览器/前端代理指向漂移端口导致页面不可用。
  - 新增 `donkeycar/webui_instance.py` 共享模块（模式参考 `kimi_web.py`）：
    - 实例登记 `~/.donkeycar/webui.json`（pid/backend_port/frontend_port/started_at，原子写入）：`read_instance`/`write_instance`/`remove_instance(only_pid)`——`only_pid` 仅清除属于自己 pid 的登记，避免误删他人后来覆盖的登记。
    - `find_live_instance()`：登记 pid 存活 + 后端 `/docs` 与前端 `/` 探测均通才算存活；失效自动清陈旧登记。
    - 车进程 PID 文件（`~/.donkeycar/drive.pid`）读写与 `kill_previous_car_processes()`：读 `/proc/<pid>/cmdline` 只杀 `manage.py drive` 车进程（释放摄像头等硬件），web 前后端进程保留复用；非 Linux 无 /proc 时退化为按 PID 全杀（与旧行为一致）。
  - `donkeycar/management/base.py`：
    - `Web.run`：先 `find_live_instance()`，存活则复用并按 `--route` 打开已有前端端口，不再重复拉起；新起路径等后端端口就绪再登记实例，退出 `finally` 按 `only_pid` 清除。
    - `Drive.run`：先只杀车进程（web 进程保留），存活实例则复用其 backend_port 注入 `DRIVE_API_SERVER_URL`、只起新车进程（PID 文件只记车进程）；无实例才新起 Web UI 并登记。
  - `donkeycar/launcher/server.py`：`_launch_drive` 删除 `_kill_orphaned_donkey_processes()`（pkill 互杀元凶）及本地 PID 副本函数，收敛到 `webui_instance`；复用存活实例只起车进程，无实例用默认端口 8000/5188 新起 `donkey web`（不再 8100 漂移）；`_get_status` 未跟踪进程时优先读实例登记，其它链路启动的 Web UI 也算 running。
  - `donkeycar/management/tui.py`：`DriveCommand.execute()` 同步复用逻辑（删除本地 PID 副本函数，探测存活实例→复用只起车进程→无则默认端口 8000 新起）；`monitor_processes` 兼容复用时无 web 进程；命令预览对复用场景显示"复用已有实例，不重复启动"。
  - 测试：新增 `tests/test_webui_instance.py` 18 项——登记读写与容错、`only_pid` 条件清除、`find_live_instance` 判定链（pid 不存活/探测失败清陈旧登记）、PID 文件往返、`kill_previous_car_processes` cmdline 过滤只杀车进程与非 Linux 退化全杀、`Web.run`/`Drive.run` 复用路径（mock 后断言不重复 Popen、车端 URL 指向复用后端端口、PID 文件只记车进程）；全量 `pytest tests/` 99 项通过。
  - 涉及文件：`donkeycar/webui_instance.py`（新增）、`donkeycar/management/base.py`、`donkeycar/launcher/server.py`、`donkeycar/management/tui.py`、`tests/test_webui_instance.py`（新增）

## 2026-08-16 (1)

- feat(launcher,web-ui): 点击 D/DD 页面左上角 logo 图标，在新标签页打开 https://www.donkeydrift.com
  - `donkeycar/launcher/server.py`（D 页 MENU_HTML）：`.headerLogo` 的 `<img>` 包进 `<a class="logoLink" href="https://www.donkeydrift.com" target="_blank" rel="noopener">`；`.headerLogo` 规则旁新增 `.logoLink{display:inline-flex}`，避免锚点行内基线问题，flex 的 `.headerRow` 视觉布局不变。
  - `web_ui/frontend/src/components/Layout.tsx`（DD 顶栏）：标题左侧 `<img src="/logo.png">` 包进 `<a href="https://www.donkeydrift.com" target="_blank" rel="noopener" className="flex items-center">`，img 原有 className 原样保留，布局/样式无可见变化。
  - 测试同步：无已入库测试断言该 logo 标记，无需修改；launcher 相关 pytest（test_launcher_terminal/test_launcher_service_unit/test_launcher_language_autodetect/test_launcher_kimi_web）30 项通过，前端 vitest 78 例（14 文件）通过，`npm run build`（tsc -b + vite）无错误。
  - 验证：worktree 临时 8190 端口启动 D 页，`curl /` 确认锚点与 CSS 均输出；DD 构建产物 `dist/assets/*.js` 含 donkeydrift.com。
  - 涉及文件：`donkeycar/launcher/server.py`、`web_ui/frontend/src/components/Layout.tsx`

## 2026-08-15 (11)

- fix(packaging): 排查并修复 macOS 上 `pip install donkeycar\[pc\]` 后 `donkey` 命令功能与 DonkeyDrifter 不一致的问题
  - 根因分析（实证验证）：
    - `donkeycar[pc]` 与 `donkeycar\[pc\]` 两种写法装出的东西**完全相同**——bash/zsh 会消耗 `\`，pip 收到的需求字符串一致；zsh 下裸 `[pc]` 触发 glob 报 `no matches found`，`\[pc\]` 只是让方括号存活到 pip 的转义写法。
    - 若反斜杠真的传给 pip（PowerShell/cmd/复制 Markdown 转义源码），新旧 pip（实测 26.1.2 / 23.3.2）均把它当本地目录，安装直接失败，不存在"装出功能不同版本"的路径。
    - 真正根因：PyPI 上 `donkeycar` 是官方上游包（autorope）。macOS 上执行该命令装的是**官方 donkeycar**——它覆盖 DonkeyDrifter 提供的 `donkeycar` 兼容包并重新生成 `donkey` console script，`tui`/`web`/`drive`/`installweb` 等 DonkeyDrifter 命令全部消失，裸 `donkey` 从进入 TUI 退化为打印 usage。
  - 修复：
    - `donkeydrifter/__init__.py`：导入时探测环境中是否存在名为 `donkeycar` 的发行包（本项目发行名是 donkeydrifter，正常安装不会注册该名），命中即向 stderr 输出醒目警告与恢复指引（`pip uninstall -y donkeycar` 后重装 `donkeydrifter[macos]`/`[pc]`）；元数据异常不阻塞导入。
    - `README.md`：Quick Start 改为 `pip install "donkeydrifter[pc]"`（引号形式，zsh 安全）；新增"安装 donkeydrifter 而非 donkeycar"醒目警告与冲突恢复命令；新增 Platform extras 小节说明 `pc`/`macos` 差异与 zsh 三种等价写法。
    - `docs/guide/donkeycar-compatibility.md`：新增"PyPI 包名与 donkey 命令"章节（两个发行包对照表、覆盖症状、恢复步骤）与"关于 `[pc]` vs `\[pc\]`"章节（三种 shell 行为实测结论）。
  - 测试：新增 `tests/test_upstream_override_warning.py` 3 项——无 donkeycar 发行包时零输出、误装后 stderr 含版本号与恢复指引、元数据异常不破坏导入；全部通过。
  - 涉及文件：`donkeydrifter/__init__.py`、`tests/test_upstream_override_warning.py`、`README.md`、`docs/guide/donkeycar-compatibility.md`

## 2026-08-15 (10)

- feat(web_ui): D/DD 切换胶囊外框统一为 DC 粗框语言——border 1px 外圈 + box-shadow inset 1px 内圈（两条相加，视觉 2px），取代与 border 重叠只剩 1px 的 outline 负偏移描边
  - `donkeycar/launcher/server.py`（D 页 MENU_HTML；主题 #themeTabs 与语言 #langTabs 两胶囊共用 .langTabs）：
    - 深色基础：`outline:1px solid #2b3441;outline-offset:-1px` → `box-shadow:inset 0 0 0 1px #2b3441`；浅色变体（`html[data-theme="light"] .langTabs`）：`outline-color:#d5dce4` → `box-shadow:inset 0 0 0 1px #d5dce4`。色值不变，只改描边实现。
  - `web_ui/frontend/src/themes/theme-mus4.css`、`web_ui/frontend/src/themes/theme-light.css`（DD ThemeSwitcher/LanguageSwitcher）：
    - 通用 `.bg-zinc-800` outline 规则不动——影响面太大（Button secondary 的 shadow-sm、Input 的 focus ring、多处 h-2 细轨道条都会被 inset 阴影波及）；新增专用选择器 `html.theme-mus4/theme-light div.rounded-full.bg-zinc-800.border{outline:none;box-shadow:inset 0 0 0 1px …}`，只命中两个切换胶囊容器（ModeTabs 容器是 bg-zinc-900，不误伤；DriveModeSelector 等其它控件族不在本次范围）。
  - 配套：Firmware 仓库同把 DC 的 RGB 开关（.langTabs）升级为同一粗框语言（v1.7.89），三处 D/DD/DC 切换键框体语言完全一致。
  - 测试同步：无已入库测试断言皮肤 CSS/模板样式，无需修改；全量验证：`tests/` + `web_ui/backend/tests/` pytest 151 项通过，前端 vitest 78 例（14 文件）通过，`npm run build`（tsc -b + vite）无错误。
  - 验证：D 页（worktree 临时 8091 实例）与 DD（vite preview 构建产物）Playwright 深/浅截图复核，两组胶囊均为 2px 粗框，与 DC 一致。
  - 部署注意：合并后需在上位机 `git pull` 并重启 `donkeydrifter-launcher.service`（D 页），DD 需重新 `npm run build`。
  - 涉及文件：`donkeycar/launcher/server.py`、`web_ui/frontend/src/themes/theme-mus4.css`、`web_ui/frontend/src/themes/theme-light.css`

## 2026-08-15 (9)

- feat(web_ui): DD 标题区入口按键文案去掉"打开 "/"Open "前缀——"打开 DrifterConsole"→"DrifterConsole"、"打开 Kimi Code Web"→"Kimi Code Web"（en 同步 "Open DrifterConsole"/"Open Kimi Code Web"→去前缀），中英文保持一致
  - `web_ui/frontend/src/i18n/messages/common.ts`：zh/en 两段各改 `common.enterButtons.drifterConsole`、`common.enterButtons.kimiCodeWeb` 两条；tooltip（`kimiCodeWebTitle`/`drifterConsoleTitle`）、失败提示（`kimiCodeWebFailed`）等其它含"打开/open"的词条一律不动。
  - `web_ui/frontend/src/components/EnterButtons.tsx` 确认无硬编码兜底文案、无渲染时前缀拼接（按钮直接渲染 i18n key），无需改动；桌面版头部与手机版汉堡菜单共用这两个 key，一处改两处同时生效。
  - 测试同步：`EnterButtons.test.tsx` 断言的是 i18n key 而非具体文案，无需修改；全量验证：后端 pytest 78 项通过，前端 vitest 78 例（14 文件）通过，`tsc -b --noEmit` 无错误，eslint 0 error（6 个 warning 均为既有、位于本次未触碰文件）。
  - 涉及文件：`web_ui/frontend/src/i18n/messages/common.ts`

## 2026-08-15 (8)

- fix(launcher): 修复 DC/DD/D 三处"打开 Kimi Code Web"全部失效（about:blank / 启动超时）——kimi 0.36.0 起 TUI 不再进 alternate-screen，旧的"PTY 注入 `kimi` → `/web`"自动化永远等不到就绪信号，每次必等满 60s 超时（避让：并行会话已合入 #118 占用 (7)，本条改号为 (8)）
  - `donkeycar/launcher/kimi_web.py` 重写启动链路（响应契约 `{"status","url"}` 不变，DC/DD/D 前端与 D 侧转发零改动）：
    - 快路径（复用）：扫描 `~/.kimi-code/server/instances/*.json` 登记（心跳新鲜 + pid 存活 + 带 `~/.kimi-code/server.token` 探测 `/api/v1/meta` 200），命中即返回 `http://<host>:<port>/#token=<token>` 入口 URL，毫秒级；kimi TUI 的内嵌 server 同样可复用。
    - 慢路径（冷启动）：无存活实例时直接拉起官方子命令 `kimi web --no-open`（0.36 起 `kimi server` 是其废弃别名），从 stdout ready banner 抓 `Local:`/`#token=` URL；二进制优先取 `~/.kimi-code/bin/kimi`（systemd 干净 PATH 下也能找到），实测冷启动 1.8s（原 TUI 链路常态 60s 超时）。失败路径杀净子进程并兜底再试一次复用（覆盖端口被登记滞后实例占用）。
    - 移除 PTY/TUI 自动化（`_BufferWriter`/`_wait_tui_ready`/`_wait_web_url`/`session_factory`），`extract_web_url`/`strip_ansi` 保留；`server.py` 仅 `launch_kimi_code_web(cwd=)` 一处调用，签名兼容。
  - `tests/test_launcher_kimi_web.py` 同步重写：保留 ANSI/URL 提取与端点 CORS 用例，新增实例复用过滤（心跳/pid/探测）、复用不起子进程、冷启动抓 URL、cwd 透传、二进制缺失、失败兜底复用、超时杀进程等用例（_FakeProc 真实管道模拟 stdout）。
  - 验证：`tests/` 全量 76 项通过；本机实测 POST 端点链路——复用路径 0.00s 返回、真实冷启动 1.8s 抓回 `#token=` URL。
  - 部署注意：合并后需在上位机 `git pull` 并重启 `donkeydrifter-launcher.service` 才生效。

## 2026-08-15 (7)

- feat(launcher): 终端页把输入行首词 postMessage 给 Drifter Console，用于 Serial 终端标签页改名
  - `donkeycar/launcher/terminal_static/terminal.html`：
    - 新增行捕获：`term.onData` 在转发 WebSocket 后追加 `trackLine(d)`——可打印字符入 `lineBuf`，退格 `\x7f`/`\b` 删尾字符，Ctrl+C/ESC 清空缓冲（方向键等转义序列不会拼出假名字），回车 `\r`/`\n` 触发 `commitLine()`。
    - `commitLine()`：取 trim 后第一个空白前的词（输入 `abc defg hijk` 上报 `abc`），截断 16 字符，非空才 `window.parent.postMessage({type:'donkeydrifter.term.name',name},'*')`（跨源 iframe，父页按 `e.source` 匹配自己的标签）。
    - TUI 防误改：`scanAltScreen()` 在 PTY 输出流扫描 `ESC[?1049h/l` 维护 `inAlt`，备用屏幕缓冲区期间（kimi/claude/codex 等全屏 TUI）清空并暂停行捕获。
  - 配套：固件侧（Firmware 仓库）新增 message 监听按 iframe 改名标签，重编号时自定义名优先。
  - 测试同步：新增 `tests/test_launcher_terminal.py` 静态断言 2 项通过；node --check 校验 script 块通过。

## 2026-08-15 (6)

- fix(launcher): D 页切换胶囊补浅色变体，深浅双色值全部改为 DD 主题重映射后的真实渲染值
  - 背景：(5) 误把 Tailwind 工具类的原始色值当作 DD 实际效果——DD 的 `src/themes/theme-mus4.css`/`theme-light.css` 会在两套主题下重映射这些工具类（如 `.bg-zinc-800` 深色实为 `#111820`、浅色实为 `#f4f6f9`），导致 (5) 的胶囊在深色下偏亮、浅色下完全保持深色（无浅色变体）。
  - 深色（theme-mus4 实际渲染值）：胶囊底色 `#27272a→#111820`、边框 `#3f3f46→#344154` 并补 1px `#2b3441` 内描边（outline -1px），未激活文字 `#a1a1aa→#8fa1b5`、hover `#e4e4e7→#e8edf2`，激活 `#0891b2→#5cc8ff` + 文字 `#fff→#061019` + 字重 400→800。
  - 浅色（theme-light 实际渲染值，新增）：胶囊 `#f4f6f9` + border `#ccd5df` + 内描边 `#d5dce4`，未激活文字 `#5b6b7d`、hover `#1a2330`；激活态深浅一致（`#5cc8ff`/`#061019`/800）。
  - hover/底色规则均以 `:not(.active)` 排除激活键，杜绝浅色下覆盖激活色（级联 (0,2,2)>(0,2,1) 曾把激活文字冲成 #5b6b7d/#1a2330）。
  - 测试同步：纯模板内 CSS 改动，无断言涉及；全量 pytest 98 项通过。Playwright 无头对拍：Donkey 胶囊与 DD（vite dev 实跑）在深色/浅色下的计算样式逐项一致（容器底色/边框/内描边/padding/gap/圆角、激活底色/文字色/字重、未激活文字色、字号），含浅色激活键悬停态。
  - 涉及文件：`donkeycar/launcher/server.py`

## 2026-08-15 (5)

- feat(launcher): D 页顶栏主题/语言切换胶囊复刻 DD 样式、整行垂直居中，11 号 Kimi Code Web 设为常用
  - `donkeycar/launcher/server.py` 菜单数据：11 号 "Kimi Code Web" `favorite: false → true`，菜单卡片显示「常用」标签。
  - 顶栏切换胶囊（`.langTabs`）逐值复刻 DD 的 `ThemeSwitcher.tsx`/`LanguageSwitcher.tsx` Tailwind 规格：容器 `bg-zinc-800(#27272a)` + 1px `border-zinc-700(#3f3f46)` + `p-1`/`gap-1`（原为 `#171c24` + 内阴影描边、固定高 24px）；按钮 `px-3 py-1`、`text-xs`（12px/16px）、字重 400（原 800），激活 `bg-cyan-600(#0891b2) text-white`（原 `#5cc8ff`），未激活 `text-zinc-400(#a1a1aa)` 且 hover 仅文字变 `zinc-200(#e4e4e7)` 不改背景，加 `transition-colors` 过渡。
  - 与 DD 行为一致：浅色模式下胶囊保持深色外观——删除 `html[data-theme="light"] .langTabs` 五条例外覆盖（DD 的胶囊为固定 Tailwind 色，无 light 变体）。
  - 顶栏整行垂直居中：`.headerRow` `align-items:flex-end → center`，删除 `.ghLink`/`.versionBadge` 的 `translateY(-1px)` 补偿与 `.headerLogo` 的 `align-self` 补丁；手机端两行布局不变。
  - 测试同步：纯模板内 CSS/数据改动，无断言涉及；全量 pytest 98 项通过。Playwright 无头实测：桌面深/浅下整行（图标/标题/GitHub/版本号/两个胶囊）垂直中心均为 29.0px 零偏差，手机端两行各自居中（28px/85px）；胶囊计算样式与 DD 逐项一致（含浅色保持深色）；11 号「常用」标签渲染确认。
  - 涉及文件：`donkeycar/launcher/server.py`

## 2026-08-15 (4)

- fix(web_ui): 顶栏胶囊与导航文本禁止换行——头部空间不足时"中文"/"跟随系统"竖排两行把切换键撑到 50px、导航 "Tub Manager" 折行
  - `web_ui/frontend/src/components/LanguageSwitcher.tsx`、`ThemeSwitcher.tsx`：分段按钮加 `whitespace-nowrap`；`Layout.tsx` 导航链接 `linkClass` 加 `whitespace-nowrap`。修后两个切换键恢复 34px，与"打开"按键同高；无头浏览器实测整行（图标/标题/导航/版本号/GitHub 图标/进入按键/切换键）垂直中心偏差全部 0.0px。
  - 测试同步：纯类名调整，无断言涉及；全量 vitest 78 例通过。
  - 涉及文件：`web_ui/frontend/src/components/LanguageSwitcher.tsx`、`web_ui/frontend/src/components/ThemeSwitcher.tsx`、`web_ui/frontend/src/components/Layout.tsx`

## 2026-08-15 (3)

- fix(web_ui): DD 标题区"打开 Drifter Console" / "打开 Kimi Code Web"按键高度由 24px（h-6）提至 34px，与右侧中英文切换键精确同高（LanguageSwitcher 总高 = 内部键 24px + 外壳 p-1×2 + border×2）
  - `web_ui/frontend/src/components/EnterButtons.tsx`：按钮类名 `h-6` 改为 `h-[34px]` 并附注释，其余样式不动；桌面端与手机端（consoleFirst）两处实例同时生效。
  - 配套：Firmware 仓库 v1.7.76 把 DC 头部三个"打开"按键同样提至 34px（`#enterDonkeyBtn,#enterDonkeyDrifterBtn,#openKimiCodeWebBtn{height:34px}` 专属规则，OTA 按钮保持 24px），已 OTA 上车确认。
  - 测试同步：纯样式类名调整，无断言涉及高度；`EnterButtons.test.tsx` 7 例及全量 vitest 回归通过。
  - 涉及文件：`web_ui/frontend/src/components/EnterButtons.tsx`

## 2026-08-15 (2)

- feat(launcher,web_ui): 实现"打开 Kimi Code Web"（issue #103/#104；配套 Firmware 侧 #59，固件 v1.7.74）
  - `donkeycar/launcher/kimi_web.py`（新增）：自动化核心——复用 `terminal.TerminalSession` 建独立 PTY bash 会话（writer 换成本模块的 `_BufferWriter` 缓冲输出，不动现有 WebSocket 桥），注入 `kimi` → TUI 就绪判定（alternate-screen 进入序列 `\x1b[?1049h` + 输出静默 2s，上限 60s）→ 注入 `/web` → 从注入点之后的输出剥 ANSI 捕获 URL（`Session:` 深链优先，`Local:`/`URL:`/`Network:` 次之，任意 http(s) 兜底）；`command not found`/`Trust this folder`/`No active session`/内嵌 server 失败均有专门报错；整体超时 120s；成功时会话保持存活（kimi web server 挂在该 PTY 前台），失败一律 close 不留孤儿。
  - `donkeycar/launcher/server.py`：新增 `POST /api/launch/kimi-code-web`——请求体可选 JSON `{"cwd": "/abs/path"}`（缺省上位机主目录；目录不存在直接报错，绝不回退）；成功 `200 {"status":"ok","url"}`、失败非 200 `{"status":"error","error"}`；**所有响应带 `Access-Control-Allow-Origin: *`**（DC 页面由 ESP32 提供服务，浏览器跨域 fetch :8090 依赖此头，仅此端点放行）；`_serve_json` 新增 `extra_headers` 参数承载。
  - D 页面（MENU_HTML）新增 **11 号菜单项"打开 Kimi Code Web"**（#104）：点击/数字键（先 1 再 1 二段输入）触发 `launchKimiCodeWeb()`，POST 固定带 `{"cwd":"/home/dkc/projects"}`（issue 要求先进入 projects 主文件夹），等待期间 overlay 显示"正在启动 Kimi Code Web（kimi 启动较慢，请耐心等待）..."，拿到 URL 后**当前标签页**跳转（区别于 #103 的新标签页）；help 文案数字键范围 0-10 改为 0-11。
  - `web_ui/backend/routers/launch.py`（新增）：`POST /api/launch/kimi-code-web` 转发路由——DD 前端与后端同源，相对路径到达本后端后原样转发到 launcher `http://localhost:8090`（125s 超时；连接失败回 502 中文错误；launcher 的业务错误 JSON 原样透传），`main.py` 挂载 `/api/launch` 前缀。
  - DD 前端（#103）：`services/api.ts` 新增 `launchKimiCodeWeb(signal)`（`validateStatus` 全放行，业务错误交给调用方按 status 判断）；`EnterButtons.tsx` 的 kimi 按钮接功能——防重复点击、点击同步上下文先 `window.open('about:blank','_blank')` 拿句柄规避弹窗拦截、`AbortController` 125s 超时、成功 `win.location.href=url`、失败关句柄并 alert；`i18n/messages/common.ts` 补 zh/en 词条（title/启动中…/失败/网络错误）。
  - 测试同步：`tests/test_launcher_kimi_web.py`（新增）19 项——strip_ansi/extract_web_url 纯函数、`_FakeSession` 脚本化 PTY（成功保活/cwd 透传/cwd 非法不建会话/command not found/Trust folder/No active session/超时回收/默认 session_factory）、内存 HTTP 服务器端点路由与 CORS 断言；`EnterButtons.test.tsx` 占位断言改为行为断言（成功填入预开标签页、失败关页+alert），共 7 例。全量回归：pytest 71 项、vitest 78 项通过。
  - 涉及文件：`donkeycar/launcher/kimi_web.py`、`donkeycar/launcher/server.py`、`web_ui/backend/routers/launch.py`、`web_ui/backend/main.py`、`web_ui/frontend/src/services/api.ts`、`web_ui/frontend/src/components/EnterButtons.tsx`、`web_ui/frontend/src/components/EnterButtons.test.tsx`、`web_ui/frontend/src/i18n/messages/common.ts`、`tests/test_launcher_kimi_web.py`

## 2026-08-15 (1)

- fix(launcher): 新开 Serial 上位机终端会话默认工作目录改为 `~/projects`（Closes #102）
  - 背景：/terminal 上位机终端新会话此前落在用户主目录 `~`（`terminal.py` `_spawn()` 的 `cwd or os.path.expanduser("~")`），每次用 kimi 等工具前都要手动 `cd`。
  - `donkeycar/launcher/terminal.py`：新增 `_default_cwd()`——优先返回 `os.path.expanduser("~/projects")`（不硬编码 `/home/dkc`），目录不存在时回退 `~`；`_spawn()` 默认 cwd 改走该函数，显式传 cwd 的调用方行为不变。
  - 测试同步：`donkeycar/tests/test_launcher_terminal.py` 新增「默认工作目录」一节 3 个用例（`~/projects` 存在时默认指向它、不存在回退 `~`、真实 bash PTY 会话 `pwd` 端到端验证），全部用 `monkeypatch.setenv("HOME", tmp_path)` 隔离机器状态；launcher 相关 27 项测试通过。
  - 涉及文件：`donkeycar/launcher/terminal.py`、`donkeycar/tests/test_launcher_terminal.py`

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

