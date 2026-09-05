# Issue 002: Tub 编辑器无法直接在图表上框选一段数据

- 状态: fixed（2026-09-04）
- 记录日期: 2026-09-04
- 页面: Tub 编辑器（转向/油门曲线图）
- 类型: enhancement（恢复被移除的能力）

## 现象

Tub 编辑器图表上无法拖拽框选一段数据，目前只能通过右上角两个数字输入框（如 6440 至 6980）手动输入范围再点删除/恢复，或两次点击设定锚点，操作不便。

## 根因分析

核心文件：`web_ui/frontend/src/components/TubEditor.tsx`（Chart.js + react-chartjs-2）。

1. 当前是**两次点击选择**模式（`TubEditor.tsx:836-849`）：第一次点击记录锚点，第二次点击把「锚点→当前点」设为选区。
2. 拖拽框选是**被人为移除的**，不是 bug：提交 `b5428fd1`（2026-08-22，「拖动选择改为两次点击选择」）删除了 mousedown→mousemove→mouseup 的拖拽链路，`handleMouseUp`（`:858-864`）留有注释「拖动选择已移除」。更早的 `d63fe8e2` 修过窄拖选被误判为单击的问题（Issue #130）后被 `1dabaf9e` revert——拖拽与单击（移动播放头）的判定冲突是历史痛点。
3. 但渲染基础设施仍在：`selectionDraft`/`selectionDraftRef`（`:95-101`）、草稿虚线框的 canvas 绘制（`:1252-1275`）、草稿态光标、草稿→选区提交 effect（`:1352-1366`）全部保留，只是事件层不再产生 draft。像素坐标→帧下标换算 `getIndexFromPointerX`（`:650-676`）可直接复用。

## 修复建议

以 `git show b5428fd1^:web_ui/frontend/src/components/TubEditor.tsx` 中被删除的原拖拽逻辑为蓝本恢复，并加冲突消解：

1. **拖动阈值分流**：`handleMouseDown`（`:813`）只记录按下点；`handleMouseMove` 中水平位移超过阈值（约 5px 或 2 帧）才进入拖拽态并更新 `selectionDraftRef`；未超阈值按现有「移动播放头 + 两次点击锚点」处理。
2. `handleMouseUp` 分流：拖拽态提交选区（复用 `queueSelectionRangeUpdate`）并清除锚点；非拖拽走现有逻辑。
3. 窄选区可见性：吸取 #130 教训，绘制端 `max(maxX - minX, 2px)` 兜底（底部滑块 `:1449` 已有先例）。
4. `handleMouseLeave` 中处于拖拽态时提交到离开点；Escape 清理逻辑（`:885-891`）已覆盖 draft。
5. 触屏分流工作量大，首版建议只恢复鼠标拖拽。

## 修复记录（2026-09-04）

按上述方案实现，全部改动在 `web_ui/frontend/src/components/TubEditor.tsx`：

1. **拖动阈值分流**：新增 `DRAG_SELECTION_THRESHOLD_PX = 5`。`handleMouseDown` 只把按下点记入 `dragStartRef`（锚点逻辑保持不变）；`handleMouseMove` 中水平位移超阈值才进入拖拽态（`isDragSelectingRef`），进入时撤销 mousedown 的锚点/选区提交（清锚点 + `clearSelectionRange`），随后持续更新 `selectionDraftRef` 草稿框。
2. `handleMouseUp` 分流：拖拽态用 `queueSelectionRangeUpdate` 提交选区；非拖拽不做事，两次点击语义不变。
3. 窄选区可见性：草稿框绘制按 `max(宽度, MIN_SELECTION_DRAFT_WIDTH_PX=2px)` 兜底。
4. `handleMouseLeave` 拖拽态提交到离开点（坐标按图表区收敛）；Escape 清理逻辑补充了拖拽态标记与 `dragStartRef`。
5. 触屏未做分流，维持现状。

测试：新增 `web_ui/frontend/src/components/TubEditor.test.tsx` 4 例（拖拽提交、阈值下视为点击、mouseleave 提交、Escape 取消），前端 vitest 30 文件 172 例全过，`tsc -b --noEmit` 与 eslint 干净。
