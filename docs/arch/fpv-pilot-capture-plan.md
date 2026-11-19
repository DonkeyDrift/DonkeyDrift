# FPV 采集卡画面采集方案（PC 端 AI 驾驶链路）

> 定案日期：2026-11-19（分支 `feat-fpv-pilot`）。
> 依据：OBS 实测采集卡（UVC "USB3 Video"，1080p/NV12(420v)/Rec.709，最高 240FPS 档）+
> WheelLink 仓库摸底（CRSF/ELRS 150Hz 控制环、`IInputSource` 抽象、ARM/看门狗/急停三级安全链）+
> 本仓库相机/录制管线摸底（`DriveVideoFrameBuffer` latest-only、`frame_freshness`、tub schema）。
> 定位：**AI 算力在 PC、FPV 画面为唯一视觉输入**的自动驾驶链路——本仓库负责采集/推理/录制/训练，
> 控制下发与安全由 WheelLink（独立仓库）承担，接口规格见其 `docs/plan/ai-bridge-plan.md`。

---

## 1. 需求与全链路架构

```
车端: FPV相机 ──5.8G图传(CADDX, 720p120)──> 接收机 ──HDMI──> USB采集卡(UVC)
                                                                  │
PC(先Mac验证):   采集层(PyAV, latest-only) → 推理层(60Hz取最新帧) → WS桥
                     │ (同帧派发)                                       │
                     └── 训练录制(tub, 兼容 train.py)                    ▼
PC(Windows, WheelLink): AiInputSource → MixedInputSource → ChannelMixer
   → CRSF@150Hz → ELRS 2.4G → 车（ARM/看门狗/急停安全链全程生效）
   回传: 人工打杆值(Steer/Throttle/Brake) + 遥测(电压/GPS地速/姿态/LQ) → WS → PC
```

职责边界（两仓库分工）：

| 层 | 仓库 | 内容 |
|---|---|---|
| 采集 | DonkeyDrift | `fpv_capture.py` 部件（PyAV，avfoundation→dshow/v4l2 可移植） |
| 推理 | DonkeyDrift | 现有 pilot 管线（KerasLinear/TorchLinear，`TRAINING_IMAGE_SIZE` 解耦输入分辨率） |
| 录制/训练 | DonkeyDrift | tub schema 兼容 `train.py`；FPV 帧 + 打杆回显 + 遥测单时钟录制 |
| 注入/仲裁/安全/射频 | WheelLink | `AiInputSource : IInputSource` + `MixedInputSource` + WS 桥（另行立项） |

## 2. 已定案决策（2026-11-19 用户确认）

1. **图传实际规格 = 720p120**（CADDX 数字图传）。AI 有效输入帧率上限 120fps；采集优先协商原生
   1280×720@120 档（若卡仅 1080p 输出则采 1080p120 缩放，M0 探测定）。
2. **油门标签语义**（训练录制映射）：D 挡油门为正、刹车为负（合成单一 `user/throttle`）、
   R 挡整体取反、N 挡不录。
3. **AI 模式切换**：方向盘按钮切换 Human / AI-shadow / AI 三态（对齐 donkey `user/local_pilot`
   语义）；**首跑默认 AI-shadow**（AI 只记录不介入）。具体按钮点位 WheelLink 侧实现时定。
4. **迁移终点 = Windows 与 WheelLink 同机**：最终形态采集(dshow)+推理+WheelLink 单机，
   WS 桥退化 localhost；Mac 验证期经 LAN WS（协议同一套）。

## 3. 采集层设计（`donkeycar/parts/fpv_capture.py`，M1 实现）

### 3.1 核心原则

- **120fps 采集的意义是帧新鲜度，不是推理帧率**：推理按 30-60Hz 消费"最新帧"，120fps 采集把
  最大取帧等待从 16.7ms 压到 8.3ms，直接吃进端到端延迟。
- **latest-only，绝不排队**：沿用 `DriveVideoFrameBuffer`（drive_api_bridge.py:171）模式——
  采集线程只覆盖最新帧 + 单调到达时间戳，消费者永远取最新，旧帧丢弃。
- **解码 pass 一步完成缩放**：NV12→`reformat(width=model_w, height=model_h, format='rgb24')`
  单次完成色彩转换+下采样（1080p→320×240 约 1-2ms/帧，M 系芯片无压力）。

### 3.2 部件接口

```python
class FpvCaptureCardCamera:
    """PyAV 采集卡相机：latest-only，平台可移植。

    cfg: FPV_CAPTURE_BACKEND = avfoundation | dshow | v4l2   # M0=avfoundation, M4=dshow
         FPV_CAPTURE_DEVICE_NAME = "USB3 Video"  # 按名字解析(推荐;macOS 枚举索引不稳定,
                                                  # 实测两轮 0/1 互换——索引只是兜底键)
         FPV_CAPTURE_W/H/FPS = 1280/720/120 # M0 终审：120 会话档，实得稳态 120fps（fpv_rate_audit 实测 p50=8.33ms）
         FPV_CAPTURE_PIXFMT  = nv12
         FPV_MODEL_W/H       = 320/240      # 推理输入（与 TRAINING_IMAGE_SIZE 对齐）
    """
    def latest_model_frame(self) -> tuple[np.ndarray, float]: ...   # (320x240x3 RGB, 到达单调时间)
    def latest_full_frame(self)  -> tuple[np.ndarray, float]: ...   # 720p RGB，供录制
    def stats(self) -> dict: ...                                    # 采集fps/帧龄/丢帧，供诊断
```

- 后台线程读帧循环（**PyAV 每帧新建 decode generator + EAGAIN 重试**，机制见 §3.4）→
  同帧派发两个消费者槽（模型帧/全帧）+ `set_source_arrival()`
  打点（frame_freshness.py 侧信道，为延迟分解测量留桩）。
- 可选像素印章：预览帧烧 `video_timestamp.draw_timestamp`，复用现有 E2E 测量方法论。
- 录制帧 JPEG q85（720p ≈60KB/帧）。

### 3.3 权限与环境（macOS）

- **TCC 摄像头授权**：采集进程宿主（终端 App / 最终的常驻服务）须在
  系统设置→隐私与安全性→摄像头 白名单；首次运行弹窗授权一次。
  本机实测：沙箱 shell 内 AVFoundation 打开采集卡会**挂起等待授权**（ffmpeg CLI 同样），
  探测一律用带超时的子进程隔离（见 `scripts/fpv_card_probe.py`）。
- 依赖已就绪：`av` 17.1（仓库核心依赖）、ffmpeg（homebrew）。

### 3.4 技术栈选型（终审翻案 2026-11-20：PyAV 重试循环为采集后端，实测满帧 120fps）

> ⚠️ 误诊史（防再犯）：初版"85fps = 卡硬件上限、PyAV macOS 死刑、ffmpeg 管道胜出"**已全部推翻**。
> 85 的真凶是 **CLI ffmpeg 读取路径的 EAGAIN 重试节拍**（~10ms 轮询+单帧读取，队列溢出丢帧）——
> 所有测出 85 的工具（CLI ffmpeg）共用这一条路径；PyAV 的"EOF 早退"是探针自己的 bug
> （**generator 在首个 EAGAIN 后死亡**，Python generator 抛异常即终止，后续 next() 全部假 StopIteration）。
> 判决实验 `scripts/fpv_rate_audit.py`（忙重试 vs 5ms 重试两段对照）：
> **605 帧/5s = 120.3fps，p50=8.33ms 精确 1/120，逐秒 120/120/120/120**——卡是真 120，格式表没虚标。

| 栈 | 定位 | 终审结论（2026-11-20，fpv_rate_audit） |
|---|---|---|
| **PyAV 重试循环（每帧新建 decode generator）** | **采集后端（M1）** | **实测 120.3fps 满帧**（忙重试与 5ms 睡眠重试均 ~120，队列吸收抖动）；进程内、逐帧时间戳、`format=avfoundation→dshow` 一参数迁移 |
| ffmpeg 子进程 → rawvideo 管道 | 对照/诊断工具 | **陷阱**：CLI 读取节拍封顶 ~85fps（丢帧），不能当 >85 的采集后端；fftest 子命令保留作诊断 |
| OpenCV `CAP_AVFOUNDATION` | 预览/低帧率模式 | 锁 60fps（格式选择选中 max60 条目，非卡限制），不用于 >60 采集 |

**EAGAIN 重试范式（M1 必须照此实现）**：avfoundation 读路径在帧间隙常态返回 EAGAIN
（`avf_read_frame` 不阻塞等帧），`container.decode()` generator 抛出该异常即**终止**——
正确读法是**每次读取新建 generator**、EAGAIN 后重试（忙重试或 ≤5ms 睡眠均可，帧队列会吸收抖动），
连续 >1.5s 无帧才判真死。30fps 内置相机同见"突发数帧后 EAGAIN"，此为该路径通性，不是卡/流故障。

## 4. 训练数据录制（M3，Mac 单进程）

- **单时钟免对齐**：人工驾驶（方向盘经 WheelLink）时打杆值与遥测经 WS 回传 Mac，与 FPV 帧
  在**同一进程同一时钟**落 tub——规避双机时间同步问题（LAN 抖动 <5ms 对 30Hz 标签无影响）。
- **tub schema 兼容现有训练链**（`donkeycar/templates/train.py` 直接消费）：

| 列 | 来源 | 类型 |
|---|---|---|
| `cam/image_array` | 采集层全帧（720p JPEG q85） | image_array |
| `user/angle` | WS 回显 `Axes["Steer"]` | float |
| `user/throttle` | 油门/刹车/挡位合成（§2.2 语义） | float |
| `user/mode` | `human` / `ai_shadow` / `ai` | str |
| `tele/speed`、`tele/vbat`、`tele/attitude`、`tele/lq` | WS 遥测（GPS 地速/电压/姿态/链路质量） | float/str |

- 默认 30Hz 录制（120fps 全录可选 ≈7MB/s）；录制开关 = ARM 状态 + 手动启停。
- 断流标记：WS 断连期间的记录打 `gap` 标记列，训练时可选过滤。

## 5. 端到端延迟预算（M0 实测校准）

| 环节 | 预算 | 备注 |
|---|---|---|
| 图传链路（720p120 低延迟档） | 15~30ms | 数字图传固有 |
| 接收机 HDMI → 采集卡 UVC 缓冲 | 8~17ms | 1-2 帧 @120fps，M0 实测 |
| 解码+缩放（PyAV reformat） | 2~4ms | NV12→RGB24+缩放一步 |
| 取帧等待（120fps 满帧达成） | ≤8.3ms | 终审：p50=8.33ms 精确 1/120（fpv_rate_audit） |
| 推理（320×240 小 CNN，MPS） | 3~8ms | 60Hz 无压力 |
| WS 传输（LAN / 最终 localhost） | 1~3ms / ~0 | |
| WheelLink→ELRS→车（官方实测） | 6~15ms | 150Hz 控制环 |
| 车端飞控执行 | ~5-10ms | |
| **合计** | **≈45~90ms** | 3m/s → 14~27cm 行程 |

M0 测量法：FPV 相机对准手机毫秒计时器 App 拍照，读"计时器读数差" = 相机→PC 段实测；
软件段用到达时间戳分解；像素印章做回归验证。

## 6. 里程碑

| 阶段 | 内容 | 验收 |
|---|---|---|
| **M0 探测** ✅（2026-11-20 终审，`fpv_card_probe.py` + **`fpv_rate_audit.py` 判决实验**） | TCC 授权排查 + 格式矩阵 + 双参照 + Swift 格式表 + **读取节拍归因审计** | **终审（翻案后定案）**：① 采集后端=**PyAV 重试循环**（每帧新建 generator+EAGAIN 重试，实测 120.3fps 满帧、p50=8.33ms）；② 采集档=1280×720 @120 会话，**实得满帧 120fps**；③ 卡**非虚标**（格式表 120 档真实；"85 上限/120 虚标"系 CLI ffmpeg 读取节拍误诊，240 档未测）；④ 无 MJPEG 档；⑤ 原生 720p 档确认。误诊史详见 §3.4 顶部警告框 |
| **M1 采集层** | `fpv_capture.py` 部件 + 预览 + 统计 | 稳定 120fps 采集、帧龄 p95 <10ms |
| **M2 桥+注入**（WheelLink 侧） | WS 服务 + `AiInputSource` + `MixedInputSource` + 三态仲裁 | 假推理（恒 0 转向/限幅油门）注入真车空转，安全链全程生效 |
| **M3 闭环** | 人工录制 FPV 数据 → 训练 → AI 首航（先直线/大半径，AI-shadow 起步） | 人工随时接管无冲突；E2E 延迟实测达标 |
| **M4 迁移** | 采集层切 `dshow`、推理与 WheelLink 同机（Windows） | 同机上 M0 指标复现；WS 走 localhost |

## 7. 风险与开放问题

- ~~1080p upscale 疑问~~ **已解决**：卡有原生 720p 420v 档（Swift 格式表 + OpenCV shape 实证）。
- ~~85fps 硬件上限 / 120 虚标~~ **已翻案（终审 2026-11-20）**：`fpv_rate_audit.py` 忙重试实测
  **120.3fps、p50=8.33ms 精确 1/120、逐秒 120/120/120**——卡真 120、格式表没虚标；此前的
  "85 上限"全部来自 CLI ffmpeg 的读取节拍（~10ms 轮询+单帧读取丢帧），"PyAV EOF"是探针
  generator 死亡的假象。教训：**读取器自身节拍会伪装成设备上限——凡"上限"结论必须有独立
  读取器对照**（第三方参照分支原则）。240 档未测（若需更高帧率再补测）。
- **图传 OSD 叠加**（电池/RSSI 入画）对模型是噪声：查图传菜单可否关 OSD，或训练前裁剪下缘条带。
- 开放：AI 油门限幅是否独立于人工限幅（WheelLink 侧）；`tele/attitude` 列格式（M3 定）。

## 8. 附：M0 运行指引

```bash
# 0) 授权：系统设置 → 隐私与安全性 → 摄像头 → 勾选你的终端 App（首次运行弹窗）
#    另：跑探测前先关掉 OBS——EAGAIN(Errno 35) 两大来源就是"授权未决"和"设备被独占"
# 1) 列设备核对（枚举索引不稳定，脚本已默认按名解析 "USB3 Video"，无需手工带 --name）
.venv/bin/python scripts/fpv_card_probe.py list
# 2) 格式矩阵探测（子进程隔离，单档超时不拖垮全局；末尾自带 default 档判别
#    "授权/占用问题"还是"格式协商问题"；产出 docs/arch/fpv-card-probe.json）
.venv/bin/python scripts/fpv_card_probe.py matrix
# 3) 抓一帧确认画面内容
.venv/bin/python scripts/fpv_card_probe.py frame
# 4) 帧率归因审计（判决实验：忙重试 vs 5ms 重试两段对照，验证满帧/唯一帧/间隔分布）
.venv/bin/python scripts/fpv_rate_audit.py
```

M0 首跑实录（2026-11-20，已修复）三条教训：
1. 裸跑 `matrix` 曾打到索引 0=**内置摄像头**（mjpeg EINVAL/640x480 I/O error 全是内置头
   格式签名）——**按名解析必须是默认行为**；
2. 采集卡 NV12 各档 "0 帧 EAGAIN" 曾误诊为授权问题——真因是 **ffmpeg avfoundation 读帧
   间隙常返 EAGAIN，CLI ffmpeg 内部重试而 PyAV 直接抛**（内置相机实测：首帧 1145ms 后
   突发 4 帧，随后 EAGAIN）——读帧循环必须睡 5ms 重试，连续 1.5s 无帧才判死；帧率口径
   用窗口吞吐（突发到达时帧间隔口径虚高到万级）；
3. ZCode 沙箱后台进程的摄像头授权弹窗不显示（tccutil reset 后仍不弹）——探测/采集一律
   从用户终端跑；ZCode 侧权限不作为依赖。
