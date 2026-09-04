# Issues 索引

本目录记录在代码库中跟踪的问题（未使用 GitHub Issues 时以此为准）。每条 issue 一个文件，含现象、根因调研与修复建议。

| # | 标题 | 类型 | 主要涉及位置 |
|---|------|------|--------------|
| [001](001-loss-popover-overlaps-actions.md) | 模型 loss 曲线浮窗遮挡操作按钮 | bug / UI | `web_ui/frontend/src/components/trainer/ModelsList.tsx` |
| [002](002-tub-editor-drag-select.md) | Tub 编辑器无法直接在图表上框选一段数据 | enhancement | `web_ui/frontend/src/components/TubEditor.tsx` |
| [003](003-load-model-not-activating-autopilot.md) | 先切换全自动/半自动再选模型时自动驾驶不激活 | bug | `drive_api_bridge.py` / `drive.py` / `complete.py` |
| [004](004-simulator-reconnect-fails.md) | 模拟器断连后自动重连不成功 | bug | `dgym.py` / `simulator.py` / `gym_donkeycar` |
| [005](005-tub-plot-frame-range-slicing.md) | Tub 曲线图支持首尾帧切片分析 | enhancement | `PilotArenaPage.tsx` / `arena.py` |
| [006](006-trainer-naming-local-vs-car-computer.md) | Trainer「本机」与「车载电脑」命名颠倒 | bug / 文案 | `i18n/messages/trainer.ts` |
