# Issue 001: 模型 loss 曲线浮窗遮挡操作按钮

- 状态: open
- 记录日期: 2026-09-04
- 页面: Trainer（训练器）→ 已训练模型列表
- 类型: bug / UI

## 现象

在 Trainer 页面「已训练模型」列表中，悬停或点击某个模型行后弹出的 model loss 曲线浮窗会覆盖相邻行的操作按钮（下载 / 推送 / 复制 / 删除），被遮住的按钮完全无法点击，且浮窗没有明显的关闭入口（无关闭按钮、无遮罩、Esc 无效）。

## 根因分析

实现全部在 `web_ui/frontend/src/components/trainer/ModelsList.tsx`：

1. 浮窗是固定定位的 popover 而非 modal：`getPopoverStyle()` 返回 `position: 'fixed'`、`zIndex: 9999`、固定尺寸 320×260（`ModelsList.tsx:117-144`），坐标基于整行的 `getBoundingClientRect()` 水平居中。260px 高的浮窗必然覆盖上方或下方 3~4 行。
2. 定位翻转：当行上方空间不足（`top < 8`）时浮窗翻转到行下方（`ModelsList.tsx:133-135`），恰好压在下方行的按钮列上；且没有视口底部钳制。
3. 触发区域是整个模型行而非独立的曲线图标（`ModelsList.tsx:172-174`，onMouseEnter / onClick toggle），误触率高；浮窗一旦锁定显示就没有关闭按钮。
4. 列表容器可内部滚动（`max-h-64 overflow-y-auto`，`ModelsList.tsx:167`）而浮窗是 fixed 坐标，滚动列表时浮窗停留在原位遮住其它行。

被遮挡的按钮列位于 `ModelsList.tsx:189-232`。同文件删除确认弹窗（`ModelsList.tsx:283`）已是正确的 modal 写法，可作参照。

## 修复建议（按推荐度排序）

1. **改为真正的 modal（推荐）**：复用删除确认弹窗的模式（`fixed inset-0` 遮罩 + 居中内容 + 点击遮罩/X 关闭），click 打开。天然不遮挡列表，也解决无关闭入口问题。
2. 保留 popover 但：触发面收敛到 loss 徽章/图标区域（`ModelsList.tsx:183-188`）；定位改放到行左侧（模型名空白区）并补视口底部钳制；监听列表滚动时关闭浮窗。
3. 最低成本缓解：给浮窗加关闭按钮 + Esc 关闭。

## 备注

用户描述为「点击 loss 曲线图标」，实际当前没有独立图标按钮，触发区是整行。若按建议 1 改造，可顺势把触发收敛到 loss 徽章上，交互语义更贴合预期。
