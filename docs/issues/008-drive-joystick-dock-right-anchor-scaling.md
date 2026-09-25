# Issue 008: Drive 页虚拟摇杆抽屉窄屏整体折叠到视频下方，应右缘常驻并连续缩放

- 状态: fixed（2026-09-22）
- 记录日期: 2026-09-22
- 页面: Drive（统一流程页 → Drive section 右侧摇杆抽屉）
- 类型: enhancement

## 现象

屏宽低于 1024px 时，「视频 + 遥测 | 右侧抽屉」容器从 `lg:flex-row` 落回 `flex-col`，
虚拟摇杆窗口和它的展开把手整体掉到视频下方：位置断点跳变、页面被抽屉自然高度撑长、
驾驶时摇杆脱离视线。用户要求摇杆窗口与把手**始终保持在屏幕右侧**，窄屏下以缩放代替折叠。

## 调研结论

- `DrivePage.tsx` 视频行容器：`flex flex-col lg:flex-row lg:items-start lg:gap-3`——
  1024px 断点以下是折叠的直接原因。
- 抽屉面板宽度 `w-[min(24rem,calc(100vw-3.5rem))]` 同样是断点式硬切，无过渡。
- `VirtualJoystick` 的指针换算基于 `getBoundingClientRect` 的**屏幕像素**位移，
  父级一旦被 `transform: scale()` 缩小，行程映射会随缩放变化（拖 1px 不再是 1px 输入），
  需要按 1/scale 补偿。
- 页面骨架 `Layout.tsx` 的 `<main>` 用 Tailwind `container`，宽度按
  640/768/1024/1280 断点量化——行宽不是随视口连续变化的，缩放比必须响应**实测容器宽**
  （ResizeObserver）而非 `window.innerWidth`。
- 把手宽度随语言变化（中文竖排 ≈30px，英文横排堆叠 ≈60px），簇自然宽不能写死常量。

## 实现要点（已落地，2026-09-22）

交互原型经独立 demo 页（`web_ui/joystick-scaling-demo.html`，可 A/B 对比新旧行为）
评估确认：右缘常驻 + 连续缩放 + 悬浮模式透明度 40%。

1. **右缘常驻**：`DrivePage.tsx` 视频行容器去掉 `flex-col` 断点（任何屏宽左右并排，
   容器加 `relative`）；抽屉 aside 任意宽度下不进文档流折叠。
2. **连续缩放**：aside 以 `transform: scale(s)`、`transform-origin: top right` 缩放，
   `s = clamp(0.62, (行宽 − 360) / 422, 1)`（422 = 面板 384 + 簇内 gap 8 + 把手的设计基准；
   缩放分支内视频列恒剩 348px ≥ 320px 底线）。贴地时以**负 margin-left** 把缩放省出的
   占位还给视频列（负右边距不会使抽屉左移，是首个实现踩过的坑）；桌面 `lg:sticky lg:top-16`
   行为保持不变。
3. **悬浮模式**：视频列保不住 320px 底线时（行宽 < 332 + 0.62 × 实测簇宽），aside 改
   `absolute right-2.5` 吸附右缘浮于视频之上，面板整体降为 `DOCK_OVERLAY_OPACITY = 0.4`
   半透明 + `backdrop-blur-[2px]`（透明度经 demo 滑块评估确认为 40%），面板顶对齐视频顶
   （实测工具栏高度 + mb-16px 让过，避免盖住录制按钮）。收起/展开用「展开态等效宽」
   （收起时 = 把手 + 面板 + gap，恰与展开自然宽相等）判定阈值，模式不随收起跳变。
4. **实测替代常量**：新增 `hooks/useElementWidth.ts`（`useElementWidth` / `useElementHeight`，
   ResizeObserver 封装）——行宽、抽屉自然宽（随语言/展开态变化）、工具栏高度全部实测；
   缩放分母用设计常量保证手感不随语言抖动。
5. **缩放补偿**：`VirtualJoystick` 新增可选 `scale` prop，指针位移按 1/scale 换算回元素
   坐标，任意缩放下行程映射一致；scale 变化时重算中心（origin 在右上角，中心会移动）。

## 验证

- `npm run check`（tsc）通过；`vitest run` 316/316 通过（两轮确认）。
- Playwright 多宽度实测（1400/1024/900/800/768/700/640/600/500/375/320）：
  - ≥1024：scale 1、抽屉右缘齐平、面板 384px——与改造前桌面完全一致；
  - 768–1023（行宽 736）：贴地缩放 0.891，视频列 321px ≥ 320；
  - ≤767（行宽 608）：自动切悬浮，视频全宽、面板 40% 透明、右缘 inset 10px；
  - 收起态保持悬浮模式不跳变；面板顶不遮工具栏（`coversToolbar: false`）。
- 摇杆拖拽补偿：s=0.62 时物理拖 40px → 摇杆头元素位移 64.5px（= 40/0.62），s=1 时 40→40。
- 截图：`/tmp/real-1024.png`、`/tmp/real-700-zoom2.png`、`/tmp/real-375-zoom.png`。
