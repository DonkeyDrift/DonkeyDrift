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
         FPV_CAPTURE_W/H/FPS = 1280/720/120 # M0 探测后定稿（720p120 优先）
         FPV_CAPTURE_PIXFMT  = nv12
         FPV_MODEL_W/H       = 320/240      # 推理输入（与 TRAINING_IMAGE_SIZE 对齐）
    """
    def latest_model_frame(self) -> tuple[np.ndarray, float]: ...   # (320x240x3 RGB, 到达单调时间)
    def latest_full_frame(self)  -> tuple[np.ndarray, float]: ...   # 720p RGB，供录制
    def stats(self) -> dict: ...                                    # 采集fps/帧龄/丢帧，供诊断
```

- 后台线程 `container.decode` 循环 → 同帧派发两个消费者槽（模型帧/全帧）+ `set_source_arrival()`
  打点（frame_freshness.py 侧信道，为延迟分解测量留桩）。
- 可选像素印章：预览帧烧 `video_timestamp.draw_timestamp`，复用现有 E2E 测量方法论。
- 录制帧 JPEG q85（720p ≈60KB/帧）。

### 3.3 权限与环境（macOS）

- **TCC 摄像头授权**：采集进程宿主（终端 App / 最终的常驻服务）须在
  系统设置→隐私与安全性→摄像头 白名单；首次运行弹窗授权一次。
  本机实测：沙箱 shell 内 AVFoundation 打开采集卡会**挂起等待授权**（ffmpeg CLI 同样），
  探测一律用带超时的子进程隔离（见 `scripts/fpv_card_probe.py`）。
- 依赖已就绪：`av` 17.1（仓库核心依赖）、ffmpeg（homebrew）。

### 3.4 技术栈选型（已定 PyAV 主选 + 两级回退）

| 栈 | 定位 | 回退触发条件 |
|---|---|---|
| **PyAV + avfoundation** | 主选：进程内、帧时间戳精确、格式可控、三平台同 API（`format=` 切换） | 该卡 NV12 档协商失败 |
| OpenCV `CAP_AVFOUNDATION`（cv2 4.11 就绪） | 备选：最简单但帧率/格式设置常不生效、内部缓冲加延迟 | PyAV MJPEG 档亦不可用 |
| ffmpeg 子进程 → rawvideo 管道 | 兜底：鲁棒但多一次拷贝、无帧时间戳 | 仅诊断工具沿用 |

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
| 取帧等待（120fps 节拍化） | ≤8.3ms | §3.1 原则的收益 |
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
| **M0 探测**（脚本已备：`scripts/fpv_card_probe.py`） | TCC 授权 + UVC 格式矩阵（720p120 原生档有无）+ 真实内容 fps + 采集延迟 | 定稿采集档位（§2.1）；实测延迟表回填 §5 |
| **M1 采集层** | `fpv_capture.py` 部件 + 预览 + 统计 | 稳定 120fps 采集、帧龄 p95 <10ms |
| **M2 桥+注入**（WheelLink 侧） | WS 服务 + `AiInputSource` + `MixedInputSource` + 三态仲裁 | 假推理（恒 0 转向/限幅油门）注入真车空转，安全链全程生效 |
| **M3 闭环** | 人工录制 FPV 数据 → 训练 → AI 首航（先直线/大半径，AI-shadow 起步） | 人工随时接管无冲突；E2E 延迟实测达标 |
| **M4 迁移** | 采集层切 `dshow`、推理与 WheelLink 同机（Windows） | 同机上 M0 指标复现；WS 走 localhost |

## 7. 风险与开放问题

- **采集卡 1080p120 是否为 720p upscale**：M0 格式矩阵定（OBS 属性"输入格式"下拉即完整矩阵，
  720p120 原生档存在则直接协商）。
- **120fps 解码负载**：M0 实测帧间隔分布；超预算降 60fps 采集（帧新鲜度损失 8ms，可接受）。
- **图传 OSD 叠加**（电池/RSSI 入画）对模型是噪声：查图传菜单可否关 OSD，或训练前裁剪下缘条带。
- 开放：AI 油门限幅是否独立于人工限幅配置（WheelLink 侧 `LimitPercent` 语义沿用还是单列）；
  `tele/attitude` 的具体列格式（M3 录制器实现时定）。

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
