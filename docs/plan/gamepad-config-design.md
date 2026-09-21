# 手柄转向轴可配置化 · 需求分析与方案设计

- 状态：设计待评审（界面方案 A / B / C 待筛选）
- 范围：仅浏览器 Gamepad 输入源（DonkeyDrift Web 驾驶控制台）
- 关联代码：web_ui/frontend/src/hooks/useGamepadDrive.ts 等
- 交互设计参考：docs/design/gamepad-config-mockup.html

## 1. 问题

### 1.1 现象
切到「手柄」输入源后：前后油门方向正确，左右转向不生效或方向相反。

### 1.2 根因
useGamepadDrive.ts 把转向和油门写死在固定轴序号上：

~~~ts
const x = applyDeadzone(pad.axes[0]);        // 转向固定用左摇杆 X
const y = applyDeadzone(pad.axes[1]);        // 油门固定用左摇杆 Y
const angle = clamp(x);
const throttle = clamp(-y * maxThrottle);
~~~

而该手柄的左右是 Z 轴（通常落在 axes[2]），因此 axes[0] 在左右方向基本不动，表现为「左右无效」。
油门使用 axes[1] 且取负，恰好与你的设备一致，所以前后正常。

### 1.3 待实测确认
需求描述中「Z 轴中位=车头朝前」与「正前方 Z 值最小；左转最大；Z 值最大时右转最大」存在表述冲突。
实际极性不必先猜：调试台会实时显示各轴数值与映射结果，勾选「反向」即可修正。

## 2. 目标

1. 转向/油门所用轴可配置，覆盖 Z 轴等非标准布局。
2. 每个轴支持反向、死区、上限（可选中位偏移）。
3. 提供常见手柄预设，降低理解门槛。
4. 提供自动识别（找出变化最大的轴）与自动死区采样，兼容更多手柄。
5. 配置可持久化（前端 + 服务端），并按手柄 id 记忆。
6. 不破坏现有键盘 / 虚拟摇杆 / 陀螺仪 / ESP32 手柄输入链路。

## 3. 方案总览

把「轴序号」从代码常量提升为配置项，映射公式统一为：去死区 → 中位校准 → 反向 → 限幅。

~~~text
raw       = pad.axes[config.axis] - config.center
normalized = deadzone(raw, config.deadzone)
output     = clamp(normalized * (config.invert ? -1 : 1) * config.max)
~~~

## 4. 数据模型

~~~ts
interface AxisMapping {
  axis: number;      // 轴索引，-1 表示未指定
  invert: boolean;   // 反向
  deadzone: number;  // 0 ~ 0.3
  max: number;       // 0.2 ~ 1
  center: number;    // 中位偏移，默认 0
}

interface GamepadConfig {
  version: 1;
  preset: "xbox" | "z-axis" | "wheel" | "custom";
  steering: AxisMapping;
  throttle: AxisMapping;
  padId?: string;    // 按手柄记忆
}
~~~

默认值（等价于现状，保证向后兼容）：steering.axis = 0，throttle.axis = 1 且 invert = true。
你的手柄预设（z-axis）：steering.axis = 2，throttle.axis = 1 且 invert = true，死区 0.08。

## 5. 界面方案对比

### 方案 A · 抽屉内嵌「手柄设置」折叠卡（推荐基础）
- 位置：虚拟摇杆下方、控制参数上方，选中手柄输入源时自动展开。
- 内容：预设下拉、转向轴/油门轴下拉、反向勾选、死区与上限滑块、迷你轴监视、一键校准入口。
- 优点：与现有控制参数面板同构，改动小、常驻可达、不遮挡视频。
- 缺点：抽屉变长；仍暴露「轴序号」概念（由预设与向导缓解）。

### 方案 B · 首次使用弹出校准向导（推荐与 A 合并）
- 触发：选中手柄且该设备未校准时自动弹出；或点击 A 中的「一键校准」。
- 步骤：识别转向轴 → 确认方向 → 识别油门轴与死区 → 保存。
- 优点：全引导，普通用户无需理解轴序号；可按手柄 id 记忆。
- 缺点：弹窗遮挡画面，驾驶中不宜弹出；实现量较大。

### 方案 C · 选中手柄时切换为「手柄映射」面板
- 选中手柄后，抽屉用轴监视器 + 映射输出替换虚拟摇杆区域。
- 优点：信息密度高，调参直观。
- 缺点：入口随输入源消失、隐藏虚拟摇杆、与输入源切换语义重叠。

### 推荐结论
以 A 为基础形态，把 B 作为首次校准与「一键校准」入口合并；C 作为可选进阶视图，暂不作为主入口。

## 6. 落地改动清单

| 文件 | 类型 | 改动 |
| --- | --- | --- |
| web_ui/frontend/src/hooks/useGamepadDrive.ts | 改 | 接收 GamepadConfig，按配置映射；支持指定 gamepad index 与热插拔 |
| web_ui/frontend/src/store/useDriveStore.ts | 改 | DriveParams 增加 gamepad 段与 setGamepadConfig，沿用防抖保存 |
| web_ui/backend/routers/drive.py | 改 | DriveParams 增加可选 gamepad 字段，旧配置兼容 |
| web_ui/frontend/src/components/drive/GamepadConfigPanel.tsx | 新 | 方案 A 折叠卡 |
| web_ui/frontend/src/components/drive/GamepadCalibrationWizard.tsx | 新 | 方案 B 向导 |
| web_ui/frontend/src/components/drive/InputSourceSelector.tsx | 改 | 手柄项旁新增设置入口 |
| web_ui/frontend/src/i18n/messages/drive.ts | 改 | 新增中英文案 |
| web_ui/frontend/src/hooks/useGamepadDrive.test.tsx | 改 | 新增轴选择/反向/死区/预设测试 |

## 7. 持久化与迁移

- 前端：zustand persist + 现有 /drive/params 防抖保存链路。
- 服务端：drive_params.json 内的 params 增加 gamepad 段；后端模型新增 Optional[dict] = None，旧文件可正常读取。
- 迁移：读取时与 DEFAULT 深合并；缺失 gamepad 段补默认（steering.axis=0、throttle.axis=1、invert=true），行为与当前一致。

## 8. 测试计划

1. 单元测试：给定伪造 gamepad 对象，验证 Z 轴映射、反向、死区、上限、center 偏移。
2. 预设测试：xbox / z-axis / wheel 三套预设的输出符合预期。
3. 组件测试：GamepadConfigPanel 与向导的交互与回调。
4. 后端测试：带 gamepad 字段的读写，以及缺失字段时的默认值与回退。
5. 回归：键盘、虚拟摇杆、陀螺仪、ESP32 手柄输入路径不受影响。

## 9. 风险与兼容

- 轴序因设备、浏览器、DInput/XInput 模式而异：配置化 + 预设 + 自动识别。
- 部分设备 Z 轴不自居中或有漂移：center 偏移 + 死区；极端情况可扩展 min/max 归一化。
- 多手柄与热插拔：记录 index 与 id，断线时输出归零，保留现有连接检测常驻逻辑。
- 浏览器 Gamepad 与车端 ESP32 rc 通道是两条独立输入源，配置只作用于前者。

## 10. 待确认问题

1. 转向实际所在轴索引（拨动后在调试台查看哪个轴在动）。
2. 左转对应 Z 最小值还是最大值（决定是否勾反向）。
3. 是否需要把 W1–W5 / 录制 / 模式切换映射到手柄按键。
## 11. 实现状态（已完成）

已按「方案 A + B 合并」落地，默认配置按确认结果：转向 = 轴 2（Z / 右摇杆 X）不反向；油门 = 轴 1 反向；不映射手柄按键。

新增文件：

- web_ui/frontend/src/lib/gamepadMapping.ts（映射公式、默认值、预设、轴提示）
- web_ui/frontend/src/lib/gamepadMapping.test.ts
- web_ui/frontend/src/store/useGamepadStore.ts（localStorage 持久化）
- web_ui/frontend/src/store/useGamepadStore.test.ts
- web_ui/frontend/src/components/drive/GamepadConfigPanel.tsx（方案 A）
- web_ui/frontend/src/components/drive/GamepadConfigPanel.test.tsx
- web_ui/frontend/src/components/drive/GamepadCalibrationWizard.tsx（方案 B）

修改文件：

- web_ui/frontend/src/hooks/useGamepadDrive.ts（配置化映射 + 轴快照；新增 monitor 选项）
- web_ui/frontend/src/hooks/useGamepadDrive.test.tsx
- web_ui/frontend/src/pages/DrivePage.tsx（挂载面板、传轴快照）
- web_ui/frontend/src/i18n/messages/drive.ts（新增 56 条中英文案）

### 持久化决策（与原计划不同）

原计划「前端 + 服务端」持久化，实际只做前端 localStorage（键名 donkey-gamepad-config）。原因：轴映射是客户端硬件相关配置，同一后端会服务桌面/手机等不同浏览器，服务端共享配置会把某台设备的手柄映射串到另一台。若以后确实需要跨浏览器同步，再给 /drive/params 增加可选 gamepad 字段即可，旧数据仍可兼容。

### 验证

- 新增/更新 23 个用例全部通过；前端全量 334 个用例通过。
- tsc -b --noEmit 与 eslint 均通过。
- 已重新构建 web_ui/frontend/dist，运行中的控制台（8001）已提供新包。

