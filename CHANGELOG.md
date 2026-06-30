# 变更日志

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
