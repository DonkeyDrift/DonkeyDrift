# 「数据体检」互动功能开发任务单（Maker Faire 现场）

- 制定日期：2026-09-11（v2：按 2 人现场裁剪范围）
- 归属计划：`docs/plan/maker-faire-demo-plan.md` P2「体验闭环 MVP」
- 目标周期：约 4-5 周（v1 范围），排入 Maker Faire 三个月计划的第 1-2 个月（与 `demo.sh` 稳定化并行，录制链路稳定后启动）

> **v1 范围（2 人现场只做这个）**：后端分析 API + 驾驶体验自动录制 + 报告卡片 + 示例数据兜底。
> **降级到 v2（现场不做）**：大屏专页 `/#/health-screen`、当日排行榜、SSE 推送——大屏 = 笔记本投电视，报告直接显示在体验台笔记本上。

---

## 0. 目标与验收标准

### 现场流程（观众视角，总时长 < 90 秒）

```
观众走到体验台
  → 点「开始驾驶体验」→ 60 秒倒计时，Web UI 摇杆驾驶（自动录制）
  → 倒计时结束自动停录 → 点「生成体检报告」
  → 大屏 + 体验台同时展示健康度报告（评分/图表/告警文案）
  → 下载/拍照分享（报告上印留资二维码）
```

### 验收标准

| 指标 | 目标 |
|---|---|
| 全流程体验时长 | < 90 秒（含倒计时 60s） |
| 报告生成耗时 | < 5 秒（只读元数据，不读图像） |
| 无模型依赖 | 默认模式不加载任何模型即可出报告 |
| 故障兜底 | 录制/分析失败时 10 秒内切到"示例数据"演示 |
| 测试覆盖 | 分析逻辑单测 + API 测试 + 前端组件测试 + 现场 checklist |

---

## 1. 现状盘点（可复用资产）

| 资产 | 位置 | 现状 |
|---|---|---|
| 统计与健康告警逻辑 | `donkeycar/management/base.py` `Evaluate.run()`（L705-788）+ `_angle_health_warnings`（L668-703） | 功能完整（三档占比/左右均衡/直行占比/告警），但**内嵌在 CLI 类里，API 无法直接调用** |
| 无模型分析性能 | `TubDataset(seq_size=0)` + 只读 `r.underlying['user/angle'/'throttle']` | 已不读图像，性能达标（60s≈1200 帧可秒级出结果） |
| 录制链路 | 前端 WS `{recording:true}` → `routers/drive.py` `drive_ws`（L546-549/654-655）→ `DriveApiBridge.recording_latch`（L432-433/794-798）→ TubWriter（`run_condition='recording'`） | 已通，体验模式只需封装"自动开始/倒计时/自动停止" |
| 录制状态回传 | `car_state.num_records / recording`（`drive_api_bridge.py` L676-681） | 可用于倒计时页显示"已录 N 帧" |
| Tub 路由模式 | `web_ui/backend/routers/tub.py`（/load /records /sessions /delete…） | 新增端点参照此模式 |
| 项目发现与配置加载 | `/api/config/discover_projects`、`/api/tub/load` | 体检 API 复用同一套"定位车项目 + 加载 config"逻辑 |
| 前端图表 | chart.js + react-chartjs-2（TelemetryChart 已有） | 报告图表直接复用 |
| 前端 Hooks/状态 | `useDriveWebsocket`、zustand stores、i18n（12 命名空间） | 体验模式按既有 hook 模式扩展 |
| 测试设施 | jest + testing-library、`donkeycar/tests/test_evaluate_command.py` | 一致性测试扩展点 |

### 关键风险点

1. **逻辑复用**：若在 `web_ui/backend` 里另写一份统计，会出现"CLI 与 Web 两套结果不一致"——必须抽公共模块；
2. **性能**：API 层必须强制"只读元数据"，一旦有人加了读图路径，报告会从秒级退化到分钟级；
3. **数据隔离**：体验录制不能污染正式数据——用专用 session 目录。

---

## 2. 任务分解

### 阶段 A：后端可复用分析模块（约 1 周）

- **A1 抽取公共模块**：新建 `donkeycar/management/health_report.py`
  - 从 `Evaluate` 提取纯函数：`build_angle_stats(records)`、`build_throttle_stats(records)`、`check_health(angle_stats)`（返回告警列表）、`build_report(tub_path, cfg, model=None)`（组合入口，返回完整报告 dict）；
  - 输入只接受 `TubDataset.get_records()` 迭代器，不碰图像；
- **A2 健康评分模型**：新建 `compute_score(stats, warnings)` → 0-100 分 + 等级（优秀 80+ / 良好 60-79 / 待改进 40-59 / 危险 <40）
  - 初稿规则（可解释、可测试）：基础 60 分；记录数 <200 扣分；左右失衡（<10%）扣 15；中间幅度缺失（<5%）扣 15；直行占比 >70% 扣 10；字段缺失（angle/throttle 记录不足）扣 10；上限 100、下限 0；
  - 每条扣分对应一条可读文案，文案引用项目实测案例（如"中间幅度仅 3.2% 时模型 corr≈0，重采后 corr≈0.99"）；
- **A3 CLI 重构**：`Evaluate.run()` 改为调用 `health_report`，输出格式保持不变；扩展 `test_evaluate_command.py` 增加 **CLI/API 输出一致性测试**（同一 tub，两路径结果逐字段相等）；
- **A4 API 端点**：`web_ui/backend/routers/tub.py` 新增 `POST /api/tub/health`
  - 请求：`{tubPath, modelPath?}`；响应：`{records, score, level, angle_stats, throttle_stats, warnings[], messages[], duration_ms}`；
  - 实现：`asyncio.to_thread` 跑分析（避免阻塞事件循环）；内部复用 tub 路由已有的项目/配置解析；
  - 可选扩展：`modelPath` 传入时追加 corr/MAE/RMSE（复用 `_metrics`），**现场默认不启用**。

### 阶段 B：前端体验模式与报告卡片（约 1.5 周）

- **B1 `useDemoSession` hook**（或扩展 `useDriveStore`）：状态机 `idle → driving → analyzing → report`
  - driving：60 秒倒计时（后端时间对齐用 WS 消息时间戳，避免 setTimeout 漂移）、自动发 `{recording:true}`、显示 `num_records` 实时帧数、结束自动 `{recording:false}`；
  - analyzing：调 `/api/tub/health`，带超时（8s）与失败转"示例数据"兜底；
- **B2 DrivePage「体验驾驶」卡片**：一键开始/倒计时 UI/停止后引导"生成体检报告"；录制 session 写入专用目录（见 D2）；
- **B3 `HealthReportCard` 组件**：
  - 评分仪表盘（大字）+ 等级徽章；
  - 三档转向占比条形图（直行/中间/大幅）+ 左右均衡图 + throttle 分布（chart.js）；
  - 告警列表（每条含"影响"与"怎么改"文案）+ 教育向结论句（"你的驾驶数据健康吗？"）；
- **B4 报告下载/分享**：canvas 绘制报告 PNG（含二维码：留资表单链接 + 仓库链接）
  - 二维码依赖决策：新增 `qrcode` npm 包（约 20KB）在前端生成，**不用后端生成**（保持后端零新依赖）；
- **B5 i18n**：新增 `health` 命名空间（zh/en），含告警文案与结论句。

### 阶段 C：大屏模式（**v2 可选，2 人现场不做**，约 1 周）

- **C1 新路由 `/#/health-screen`**（全屏大字版，从 FlowPage 布局独立出来）：轮播最近 N 份报告 + 当日排行榜 Top 5（昵称 + 分数 + 等级徽章）；
- **C2 排行榜存储**：后端内存 + JSON 文件持久化（`~/.donkeycar/health_leaderboard.json`）；防刷：前端 localStorage 设备指纹 + 每设备每日限 3 次提交（现场场景够用，不做强校验）；
- **C3 联动**：体验台新报告生成后推送大屏——方案选 **SSE**（复用 trainer/simcollect 的 SSE 模式）或 5s 轮询 GET；推荐先轮询（1 天工作量 vs SSE 2 天），人流大再升级；
- **C4 大屏配套**：深色大字号样式、自动隐藏鼠标、断线显示"等待下一份报告"。

> v1 替代方案：报告直接在体验台笔记本全屏展示（浏览器自带全屏），投屏到电视即可，**零开发**。

### 阶段 D：现场运维集成（约 0.5 周，可与 A-C 并行）

- **D1 录制目录隔离**：体验模式录制写入专用目录 `<car>/data/health_sessions/<sessionId>/`，与正式数据分离；晚间复盘按 session 汇总（复用 `/api/tub/sessions`）；
- **D2 `demo.sh` 集成**：pre-flight 增加"录制链路自检"（开录 3 秒 → 停录 → 确认 num_records 增长）；启动后默认打开体验页 + 大屏页两个窗口；
- **D3 报告导出**：`data/health_reports/<timestamp>.json/png` 自动留存，供晚间复盘与展后数据报告（KPI："体验人次"、"平均分"）；
- **D4 示例数据包**：预录 3 条 tub 示例（一条健康 / 一条左右失衡 / 一条直行过多），打包进演示环境，故障与冷场时一键展示——**保证任何时候都能演示体检功能**。

### 阶段 E：测试与验收（贯穿，收尾 0.5 周）

- **E1 单测**：`health_report` 纯函数全覆盖——告警边界（mid_ratio=4.9%/5.0%、left=9.9%/10.0%、直行 69%/71%）、评分边界、空 tub、缺字段 tub；
- **E2 API 测试**：`/api/tub/health` 正常 / 空 tub / 路径不存在 / 超时；
- **E3 前端测试**：倒计时状态机（含 WS 断线重连）、报告渲染（分数/图表/告警）、下载按钮（mock canvas）；
- **E4 端到端验收清单**（现场 checklist 纳入 `demo.sh` pre-flight）：
  - 60s 录制 → 报告 <5s → 大屏自动更新 → PNG 下载含二维码 → 排行榜出现新纪录；
- **E5 故障演练**：录制失败 / 分析超时 / 大屏断连 / WS 断线——每条都有兜底路径且演练过。

---

## 3. 需要拍板的设计决策

| # | 决策点 | 建议 | 理由 |
|---|---|---|---|
| D1 | 分析逻辑放哪 | `donkeycar/management/health_report.py` 公共模块，backend 薄封装 | CLI 与 API 一套逻辑，一致性可测试 |
| D2 | 报告数据源 | 只读 tub 元数据（标签字段），**禁止读图** | 60s≈1200 帧，读图会拖到分钟级 |
| D3 | 评分规则 | 60 分基础 + 四项扣分（见 A2），等级四档 | 可解释、可测试、现场能讲给观众听 |
| D4 | 录制目录 | 专用 `data/health_sessions/` | 不污染正式数据；复盘可汇总 |
| D5 | 排行榜防刷 | localStorage 指纹 + 每日 3 次 | 现场场景够用，不做强校验 |
| D6 | 二维码 | 前端 `qrcode` npm 包 | 后端零新依赖 |
| D7 | 大屏联动 | 先 5s 轮询，人流大再升级 SSE | 1 天 vs 2 天工作量，MVP 优先 |

---

## 4. 排期与人力（2-3 人团队）

| 周次 | 任务 | 负责人建议 |
|---|---|---|
| 第 1 周 | A1 + A2 + A3（含一致性测试） | 后端主力 |
| 第 2 周 | A4 + E1/E2 + B1 | 后端主力 |
| 第 3 周 | B2 + B3 | 前端主力 |
| 第 4 周 | B4 + B5 + E3 | 前端主力 |
| 第 5 周 | D1-D4 + E4/E5 + 内测 1 轮 | 全员 |

**v1 排期 = 5 周（不含阶段 C）**；阶段 C（大屏/排行榜/SSE）排期另计，作为 v2 在展后或有人手时再做。
**依赖关系**：A（后端）→ B（前端）→ D/E（集成验收）；**录制链路稳定性是前置条件**——若 `demo.sh` 稳定化发现车端录制 bug，优先修录制再继续 B。

---

## 5. 上线前检查清单

```
□ /api/tub/health 在空 tub / 坏路径下返回可读错误
□ 报告生成对 1200 帧 tub < 5s（性能冒烟）
□ CLI evaluate 与 API 输出逐字段一致（自动化测试）
□ 体验模式断网/断 WS 时自动停录并提示
□ 示例数据包一键可展示（不依赖车与相机）
□ 报告全屏展示 + 投屏电视正常（替代大屏专页）
□ 报告 PNG 二维码扫出来是留资表单
□ 夜间复盘脚本能输出：体验人次/平均分（v1 不含 TOP5）
```

---

## 6. 现场话术衔接（互动点 3 专用）

- 开场："来，开 60 秒车，我们看看**你的驾驶数据健不健康**——很多 AI 模型学不会开车，问题不在模型，在数据。"
- 报告展示时指着告警项："你看，你直行占了 80%，这种数据训练出来的模型只会走直线。"
- 收尾："报告可以下载带走，上面有二维码——扫码可以拿到完整版报告和开源代码。"
- 对教育机构："这个'数据体检'本身就是我们的课程模块，学生录完数据自己看报告，数据素养是这么练出来的。"
