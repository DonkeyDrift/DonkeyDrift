# Issues 索引

本目录存放问题的调研文档（现象、代码级根因分析、修复建议），并已全部同步为 GitHub Issues（2026-09-04）。正文以 GitHub Issue 为准，本目录保留调研细节备查。

| # | GitHub | 标题 | 类型 | 主要涉及位置 |
|---|--------|------|------|--------------|
| [001](001-loss-popover-overlaps-actions.md) | [#360](https://github.com/DonkeyDrift/DonkeyDrift/issues/360) | 模型 loss 曲线浮窗遮挡操作按钮 | bug / UI | `web_ui/frontend/src/components/trainer/ModelsList.tsx` |
| [002](002-tub-editor-drag-select.md) | [#361](https://github.com/DonkeyDrift/DonkeyDrift/issues/361) | Tub 编辑器无法直接在图表上框选一段数据 | enhancement | `web_ui/frontend/src/components/TubEditor.tsx` |
| [003](003-load-model-not-activating-autopilot.md) | [#362](https://github.com/DonkeyDrift/DonkeyDrift/issues/362) | 先切换全自动/半自动再选模型时自动驾驶不激活 | bug | `drive_api_bridge.py` / `drive.py` / `complete.py` |
| [004](004-simulator-reconnect-fails.md) | [#363](https://github.com/DonkeyDrift/DonkeyDrift/issues/363) | 模拟器断连后自动重连不成功 | bug | `dgym.py` / `simulator.py` / `gym_donkeycar` |
| [005](005-tub-plot-frame-range-slicing.md) | [#364](https://github.com/DonkeyDrift/DonkeyDrift/issues/364) | Tub 曲线图支持首尾帧切片分析 | enhancement | `PilotArenaPage.tsx` / `arena.py` |
| [006](006-trainer-naming-local-vs-car-computer.md) | [#365](https://github.com/DonkeyDrift/DonkeyDrift/issues/365) | Trainer「本机」与「车载电脑」命名颠倒 | bug / 文案 | `i18n/messages/trainer.ts` |
