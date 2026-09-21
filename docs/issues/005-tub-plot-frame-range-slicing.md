# Issue 005: Tub 曲线图只能定量生成，希望支持首尾帧切片分析

- 状态: fixed（2026-09-04）
- 记录日期: 2026-09-04
- 页面: Pilot Arena → Tub 曲线图
- 类型: enhancement

## 现象

Tub 曲线图（对比 user angle / pilot angle / user throttle / pilot throttle）目前只能输入一个帧数（如 200）生成曲线，无法指定首尾帧做特定区间的切片分析。

## 调研结论

这是 **UI 缺口而非能力缺失**：后端 API 已支持 `start + limit` 区间语义，前端把 `start` 硬编码为 0，只暴露了 `limit`。

- 前端：`web_ui/frontend/src/pages/PilotArenaPage.tsx:760-781` `loadPlot()` 固定发 `{ config_path, start: 0, limit: plotLimit }`；UI 只有一个帧数输入框（`:1138-1145`）+「生成曲线」按钮（`:1146`）。
- 后端：`web_ui/backend/routers/arena.py:70-81` `PredictionsRequest` 已有 `start: int = 0`、`limit: int = 1000`；`:473-507` 取帧逻辑是连续区间 `records[start : start+limit]` 逐帧推理（非采样）。
- `web_ui/frontend/src/services/api.ts:689-703` `getArenaPredictions` 的 payload 类型已含 `start?: number`，无需改动。

注意点：

- 后端请求体没有 `end` 字段，区间需换算为 `limit = end - start + 1`（也可选在后端加 `end` 参数，非必须）。
- 图表 X 轴用记录的 `_index`（catalog 索引），而 `start` 是 `records` 数组位置。若 tub 删除过记录、`_index` 非连续，两种语义的体感不同——建议 UI 明确标注按「记录位置（0..N-1）」。
- 区间大时后端逐帧推理耗时长，现有无进度反馈，仅 `plotLoading` 转圈。

## 实现建议

**交互形式已确认（2026-09-04）：用双滑块进度条（range slider）设置首尾帧。** 项目内无现成 range-slider 组件，需自绘（chart 区域叠加双滑块，或基于原生双 `input[type=range]` 组合）或引入轻量依赖；自绘时注意与页面现有深色主题样式一致。

1. `PilotArenaPage.tsx:177-182` 附近新增 `plotStart` / `plotEnd` state（默认 `0` / `records.length - 1`）。
2. `:1127-1149` 把单个帧数输入框替换为双滑块控件（保留数值显示，便于精确读数；可辅以两个只读/可编辑的小数字框），做 `plotStart <= plotEnd` 约束。
3. `:769-773` 调用改为 `{ config_path, start: plotStart, limit: plotEnd - plotStart + 1 }`。
4. i18n：`web_ui/frontend/src/i18n/messages/arena.ts`（zh 约 49-63 行 / en 约 121-135 行）新增起止帧文案。
5. 测试同步：`PilotArenaPage.test.tsx`、`web_ui/frontend/e2e/pilot-arena.spec.ts` 的 `/predictions` mock 契约断言、`web_ui/backend/tests/test_arena.py`（E2E mock 契约忠实度是近期提交专门修过的点，需保持真实形状）。
