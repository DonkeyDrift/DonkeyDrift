# AidLux / Qualcomm QCS6490 自研模型 → NPU 部署 跑通记录

- **日期**：2026-09-21
- **设备**：AidLux 开发板（Qualcomm QCM6490 / sm7325，Ubuntu 24.04，NPU 已激活）
- **目标**：把自研模型转成能在板载 Hexagon NPU（HTP）上推理的模型，并确保环境具备该能力
- **状态**：✅ **全链路已跑通并实测验证**（演练模型：YOLOv5s → QCS6490/QNN2.40/INT8 → 设备 NPU 推理 12~14ms/图）

---

## 0. 结论速览

| 项 | 结论 |
|---|---|
| 转换工具在哪 | **设备上没有 QNN 转换器**（全盘无 `qnn-onnx-converter`/`qairt`/`snpe-*`）。官方路线是 **AIMO 模型优化平台**（SaaS 云端）或 x86 PC 侧 QNN SDK |
| 推荐链路 | 模型 → **AIMO Python SDK**（`TargetDevice=Qualcomm_QCS6490` + `ModelRuntime=QNN_2_40`）→ 下载 `*.ctx.bin` → 设备 AidLite `qnn240` 后端 + `TYPE_DSP` |
| 实测转换耗时 | YOLOv5s 640 INT8，**263.87 秒（4 分 24 秒）**（CLE 量化很快，文档里"可能几天"指的是 ADA 方法） |
| 实测 NPU 性能 | 完整 YOLOv5s 后处理流程 **12.62 ms/图**；零输入冒烟测试 **11.75~13.75 ms** |
| 设备侧运行前提 | AidLite SDK **2.5.0.284** + 匹配后端 **aidlite-qnn240 2.5.0.284**（`TYPE_QNN240` + `TYPE_DSP`） |
| NPU 使用前提 | 设备必须已激活（本机 license ID `<device-license-id>`）；`.bin`/ctx 模型**只能跑 DSP**（CPU/GPU 会被拒，`StatusCode[120010]`） |
| **★ NPU vs CPU 加速比** | YOLOv5s 640 实测：纯推理 **70.2×**（6.2 ms vs 435.2 ms）；端到端 **35.2×**（12.4 ms vs 435.4 ms）。CPU 基准 = 同源 ONNX 走 AidLite `TYPE_CPU`（8 核），onnxruntime 425 ms 交叉印证 |
| 一键全流程 | `scripts/aidlux_npu_pipeline.py`：给模型 → 转换/复用 → NPU 测速 → CPU 基准 → 张量级+检测级精度 → 加速比报告（控制台 / JSON / Markdown） |

---

## 1. 环境基线

### 1.1 设备

```
主机        AidLux QCM6490 (qcm6490-addons IDP platform), Ubuntu 24.04.3 LTS, kernel 6.6.65-qli
内存/存储   7.2 GiB RAM（约 6 GiB 可用）/ 111 GB 磁盘（16% 占用）
编译链      gcc/g++ 13.3.0, cmake 3.28.3, make, python3-dev, pkg-config
```

### 1.2 AI 栈版本矩阵（⚠️ SDK 与后端必须同主版本）

| 包 | 版本 | 说明 |
|---|---|---|
| `aidlite-sdk` | **2.5.0.284** | 推理核心（C++ 库 `libaidlite.so` + Python 模块 `aidlite`） |
| `aidlite-qnn240` | **2.5.0.284** | **NPU/HTP 后端（本项目使用）** |
| `aidlite-onnx` | **2.5.0.284** | CPU 后端（跑 ONNX 原模型做对照） |
| `aidlite-tflite` | **2.5.0.284** | CPU 后端 |
| `aidlux-aistack-base` | 1.3.1.169 | 依赖 |
| `pyaidlite` | 2.5.0.284 | Python 绑定（import 名是 `aidlite`，不是 `pyaidlite`） |
| `aidlite-qnn236` | 2.3.2.248 | ⚠️ **死版本**：appcenter 上 qnn236 最高只到 2.4.1.278，满足不了 2.5.0 核心要求的"后端 ≥2.5.0.X"，对应的 qnn236 示例已不可用 |

**官方版本约束（`aid-pkg show aidlite-sdk`）**：
> If the version number of Aidlite-SDK is greater than or equal to 2.2.6.\*, then the backend inference framework program must also be greater than or equal to version 2.2.6.\*

**可匹配 2.5.0.284 核心的后端**：`aidlite-qnn240` / `aidlite-qnn248` / `aidlite-onnx` / `aidlite-tflite` / `aidlite-remote` / `aidlite-rknn`（均 2.5.0.284）

### 1.3 网络接入（主备双路径）

| 路径 | 地址 | 说明 |
|---|---|---|
| `wlan0`（WiFi） | `<board-ip>/24`，gw `<board-ip>` | **主路由** `metric 100`，SSID HUAWEI-DKC 5GHz ch161 |
| `eth0`（USB 千兆网卡→PC ICS） | `<board-ip>/24`，gw `<board-ip>` | 备用 `metric 200` |
| `eth1`（USB-RNDIS 旧路径） | — | ❌ 已废弃，曾闪断（`linkdown`）导致 SSH 随机超时、HTTPS 全 `HTTP 000` |

配置由 **netplan 托管**（`/etc/netplan/90-NM-*.yaml`，非 `/etc/NetworkManager/system-connections`），已持久化：`route-metric` / `wifi.powersave: "2"`（关省电，降抖动）。

### 1.4 Python 工具（为自研模型准备）

| 模块 | 版本 | 用途 |
|---|---|---|
| `numpy` | **1.26.4** | ⚠️ 必须 `<2`（onnx 会试图升到 2.5.3，会破坏 AidLite；安装时务必钉住 `"numpy<2"`） |
| `onnx` | 1.22.0 | 模型结构检查、改 input shape（AIMO FAQ 要求把 `?`/动态维固定） |
| `onnxruntime` | 1.30.0 | CPU 参考推理（精度对照） |
| `opencv-aidcv-python` | 4.13.0（`cv2` 报 4.6.0） | 前后处理 |
| `aplux_aimo` | **1.3.0** | AIMO 云转换 SDK |
| `mms`（aid-mms 1.2.61） | CLI | Model Farm 模型下载（`list` 免登录，`get` 需登录） |

---

## 2. 转换链路（已跑通）

### 2.1 参数表（演练实际使用）

```
源模型               cutoff_yolov5s_640_sigmoid.onnx（28,930,494 B，opset 12，输入 images [1,3,640,640]，199 节点）
SourceModelType      ONNX
TargetDevice         Qualcomm_QCS6490
ModelRuntime         QNN_2_40                       ← 与设备 aidlite-qnn240 精确匹配
quantize_precision   INT8        (= 'A8_W8')
quantize_mode        ['cle']     (= Enhanced_CLE)
per_channel_quantize True
calibration_data_mode  'cv'      (= Image)
calibration_dataset_type 'imagenet'  （AIMO 内置校准集，无需上传图片）
```

### 2.2 时间线（AIMO 产物包内 `shell_info.txt` 原文）

```
17:23:22  Optimization started.
17:23:22  [ONNX-SIM] Clean ONNX Model input node.
17:23:23  [ONNX2QNN] Start converting to QNN.
17:27:26  [CONVERT-QNN] Convert model is done. Begin to compile model.      ← 转换 4分03秒
17:27:40  [COMPILE-QNN] Compile model is done. Begin to create serialization file.  ← 编译 14.5s
17:27:45  [CREATE-CONTEXT-BINARY] Create context binary is done.          ← ctx 4.8s
17:27:45  Model optimization done.
```
任务记录：`task_status = SUCCESS`，`usage_time = 263.87`，task_id `04cbf2a061034ea4b2c01547a7c9f26d`

### 2.3 AIMO 产物包说明（`*_save_path.zip`，演练 12,951,108 B）

| 文件 | 大小 | 作用 |
|---|---|---|
| `cutoff_yolov5s_640_sigmoid_qcs6490_w8a8.qnn240.ctx.bin.aidem` | 7,673,904 B | ✅ **设备用的 QNN 上下文二进制（ARM/HTP）** |
| `libcutoff_..._w8a8.qnn240.x86.so.aidem` | 7,916,496 B | ⚠️ x86 共享库，给 **PC 仿真**用，**设备上不能用**（用了会报 `StatusCode[120000] Initializing QNN Function Points failed`） |
| `qnn_model_info.json` | 325 B | **输入输出形状/类型/目标 SoC**（设备侧脚本靠它自动取形状） |
| `htp_config.json` | 242 B | HTP 图配置（vtcm 2MB、dsp_arch v68、soc_id 35、perf_profile burst…） |
| `htp_backend_extensions.json` | 284 B | ⚠️ 指向 **AIMO 服务器 x86 路径**，设备上无用有害，**不要加载**（见 4.6） |
| `cutoff_..._qcs6490_net.json` | — | QNN 图结构（张量名/维度） |
| `shell_info.txt` | 679 B | 转换日志（时间线，很适合排错） |

`qnn_model_info.json` 内容：
```json
{"model_name": "cutoff_yolov5s_640_sigmoid_qcs6490_w8a8.qnn240.ctx.bin", "data_type": "int8",
 "inputDimensions":  {"images": [1, 640, 640, 3]},
 "outputDimensions": {"_326": [1, 80, 80, 255], "_364": [1, 40, 40, 255], "_402": [1, 20, 20, 255]},
 "htp_socs_name": "QCS6490", "htp_socs_type": "sm7325", "qnn_sdk": "2.40.0.251030"}
```
> 注意：**AIMO 把 ONNX 的 NCHW 输入自动转成了 NHWC `[1,640,640,3]`** —— 正好与 AidLite 示例里 `input_shapes = [[1, 640, 640, 3]]` 的约定一致，设备侧形状写法不用改。

---

## 3. 设备侧部署与验证

### 3.1 方式一：完整 YOLOv5 流程（含前后处理）

改造官方示例（只改模型路径，前后处理照用）：
```bash
W=/home/aidlux/models/npu_test2
cp -r /usr/local/share/aidlite/examples/aidlite_qnn240/. $W/
cp <AIMO产物>/cutoff_..._w8a8.qnn240.ctx.bin.aidem $W/data/qnn_yolov5_multi/aimo_model.ctx.bin
cd $W/python
sed -i 's|cutoff_yolov5s_640_sigmoid_qcs6490_w8a8.qnn240.ctx.bin|aimo_model.ctx.bin|' qnn_yolov5_multi.py
python3 qnn_yolov5_multi.py 3        # 3 = TYPE_DSP(NPU)
```
实测输出：
```
repeat [10] times , input[29.75]ms --- invoke[65.59]ms --- output[30.86]ms --- sum[126.20]ms   → 12.62 ms/图
检测到4个区域: 3 person + 1 bus
```

### 3.2 方式二：通用冒烟测试（任意模型，无需任务专用后处理）

```bash
python3 /home/aidlux/tools/npu_smoke_test.py <model.ctx.bin> \
        --info <AIMO包>/qnn_model_info.json --acc 3 --iters 10
```
自动从 `qnn_model_info.json` 取输入输出形状，全零输入跑 10 次，报告耗时与每个输出的形状/数值范围。

实测：
```
自转模型 : 平均 11.75~13.75 ms   输出 _326(1632000,) / _364(408000,) / _402(102000,)
官方模型 : 平均 11.19 ms
CPU/GPU 档: 正确被拒 → StatusCode[120010] "QNN's .bin model can only use DSP"
```

### 3.3 精度对比（同一张图）

| | 自转模型（ImageNet 校准） | 官方模型 |
|---|---|---|
| 检测数 | 4 | 4 |
| 类别 | 3 person + 1 bus | 3 person + 1 bus |
| bus 置信度 | 0.645 | 0.751 |
| person 置信度 | 0.847 / 0.787 / 0.575 | 0.813 / 0.811 / 0.799 |
| 框位置偏差 | ~10 px 量级 | — |

**结论**：链路正确、类别无误；置信度偏低源于**校准集**（演练用 AIMO 内置 ImageNet 通用校准）。换正式模型时用任务同分布图片校准可显著改善。

---

### 3.4 全流程一键脚本 `aidlux_npu_pipeline.py`

一条命令跑完「转换 → NPU 测试 → CPU 基准 → 精度评估 → 加速比」：

```bash
# 已有产物：只测速 + 精度 + 加速比（不消耗 AIMO 配额）
python3 aidlux_npu_pipeline.py --model yolov5s.onnx --ctx xxx.qnn240.ctx.bin.aidem \
        --images ./samples --cpu-backend both

# 从源模型开始：自动送 AIMO 云端转换（YOLOv5s 约 4~5 分钟）
python3 aidlux_npu_pipeline.py --model yolov5s.onnx --images ./samples \
        --calib-type custom --calib-dir ./calib
```

八个阶段：环境自检 → 模型分析 → AIMO 转换（带缓存复用）→ 产物定位 → NPU 测速 →
CPU 基准 → 精度评估 → 加速比报告。

**实测输出（YOLOv5s 640 / QCS6490 / AidLite 2.5.0.284 / 评估 3 张图）**

| 项 | 结果 |
|---|---|
| NPU `set_input` / `invoke` / `get_output` | 3.1 / **6.2** / 3.0 ms |
| NPU 端到端 | **12.4 ms（81 FPS）** |
| CPU AidLite ONNX（8 核） | 435.2 ms（2.3 FPS） |
| CPU onnxruntime 1.30（交叉印证） | 425.0 ms（2.4 FPS） |
| **★ 加速比（纯推理 / 端到端）** | **70.2× / 35.2×** |
| 张量级一致性（三输出最小余弦） | 0.9947 |
| 检测级 | 4/4 匹配，平均 IoU 0.915，类别一致率 100% |

产物：`report.json`、`report.md`、`vis_N_npu.jpg` / `vis_N_cpu.jpg`（可肉眼核对）、`aidlite.log`。

**为什么 CPU 基准要另走源模型**：`.ctx.bin` 只能跑 DSP（`StatusCode[120010]`），
同一个二进制没法两边跑。CPU 侧用**同一源 ONNX** 走 AidLite `TYPE_ONNX` + `TYPE_CPU`
（同 API、同预处理，最公平），再用 onnxruntime 交叉印证。两边输入张量完全相同。
**注意输出布局不同**：QNN 输出 NHWC、ONNX 输出 NCHW，脚本按各自声明形状 reshape 后把
通道轴统一到 `axis=1` 再做逐元素比较——直接相减两个 flat buffer 是无意义的。

---

### 3.5 原始模型是 TFLite 时的适配（实测）

AIMO 支持 `SourceModelType.TensorFlow_Lite`（值 `'tflite'`）。脚本 `--source-type auto` 会按扩展名
自动映射，无需手工指定。除此之外有 6 个 TFLite 特有的坑，脚本都已处理：

| # | 坑 | 处理方式 |
|---|---|---|
| 1 | 形状不能靠猜 | 非 ONNX 源用 AidLite 在 **`init()`+`load_model()` 之后** 调 `get_input_tensor_info()`/`get_output_tensor_info()` 拿真实 I/O（之前调会抛 `RuntimeError`） |
| 2 | 输出顺序不是 stride8 在前 | 实测三个头是 `StatefulPartitionedCall:1/2/0` = 40/20/80 尺度 → 按**元素数排序**对齐 |
| 3 | 输入数据类型 | `element_type`：4=float32 / 1=uint8 / 2=int8。量化模型必须按 uint8 原图喂，否则**静默出 NaN** |
| 4 | 输出尺度非标准 | 官方 `Detect` 网格写死 stride 8/16/32；实测 int8 版头是 40/20/10 → 拒解并打印原因 |
| 5 | 该用哪个 tflite 当源 | 用 **fp32** 版当 AIMO 源；文件名含 `int8` 会告警 |
| 6 | 输出对不齐时 | 明确告警 + 指标标"无法计算"，不假装通过 |

**实测（CPU 与 NPU 用完全相同的输入张量，CPU 跑满 8 核）**

| 运行方式 | NPU `invoke` | CPU `invoke` | 纯推理加速比 | 端到端加速比 | 精度 |
|---|---|---|---|---|---|
| **全链路**：tflite 源 → AIMO 转出 ctx（task_id `761f826abc3940d3b7fc0016ed5ed486`，转换 232s）；CPU 基准用同一个 tflite | 5.56 ms | 723.4 ms | **130.0×** | 65.3× | cos≥0.9947；检测 4/4，IoU 0.917，类别一致率 100% |
| 快速验证：NPU 用 ONNX 转出的 ctx，CPU 基准用该 tflite | 6.27 ms | 723.0 ms | 115.4× | 56.5× | cos≥0.9947 |
| CPU 基准用 int8 版 tflite | 6.15 ms | 205.7 ms | 33.5× | 17.6× | 输出尺度非标准 → 拒解 |

**交叉印证**：同一张图、同一个 NPU 产物，用 ONNX 版 CPU 基准与 TFLite 版 CPU 基准分别比，
余弦相似度 0.996422 / 0.996428 / 0.996453、IoU 都是 0.914~0.917 —— 两个框架实现同一网络，
结果几乎逐位重合，说明「布局归一化 + 逐元素比较」这套流程本身是可靠的。

**另一个实测细节**：tflite 转出的 ctx，其 `qnn_model_info.json` 里输出顺序是
`[[1,20,20,255],[1,40,40,255],[1,80,80,255]]`（**非** stride8 在前），与 ONNX 转出的 ctx 顺序不同。
脚本按元素数对齐，所以两种顺序都能正确处理 —— 这也印证了「不要按索引假设输出顺序」。

---

### 3.6 案例：DonkeyCar 行为克隆回归模型（Sim01.tflite）

来源：`d:\Projects\MushroomCloud\Sim01.tflite`，参考项目 `github.com/DonkeyDrift/DonkeyDrift`（DonkeyCar 分支）。

| 项 | 实测 |
|---|---|
| 输入 | `serving_default_img_in:0` **[1, 120, 160, 3]** float32 —— DonkeyCar 标准 120×160×3 RGB |
| 输出 | 两个标量 `[1,1]` = (steering, throttle)，**回归**模型 |
| 预处理 | ×1/255 → [0,1]（脚本 `--norm 01`，与参考项目 `donkeycar/utils.py::normalize_image()` 完全一致） |
| 转换 | INT8 / CLE，**33.8 s**（服务端 24.65 s），产物 1.0 MB，task_id `bfbaa356a06945f99f9c131b00bbbac3` |
| NPU | `set_input` 0.47 / `invoke` **0.69** / `get_output` 0.36 / 端到端 **1.51 ms**（661 FPS） |
| CPU（同一 tflite，8 核） | `invoke` 3.78 / 端到端 3.90 ms（256 FPS） |
| **加速比** | **纯推理 5.51× / 端到端 2.58×** |
| 精度 | steering Δ0.0234、throttle Δ0.0038（跨域图片上的量化误差，非训练域） |

**三个与该模型类型有关的要点**

1. **回归模型的评估口径必须换** —— 两个标量输出的余弦相似度没有意义（符号翻转会给出 −1，
   第一版就误报成"精度差"）。脚本对小维度输出（≤16 元素）额外给出**逐值对照**
   （NPU 值 / CPU 值 / 绝对偏差 / 相对误差），结论按「绝对偏差 + 相对误差」双阈值判定，
   并自动把小维度输出排除出余弦统计。
2. **小模型的固定开销占比高** —— 端到端 1.51 ms 里 `set_input`+`get_output` 占 0.83 ms（55%），
   真正的计算只有 0.69 ms。所以这个尺度上加速比被固定开销摊薄：纯推理 5.5×，端到端只剩 2.6×。
3. **`qnn_shared_buffer = 1` 实测无收益** —— 1.480 ms vs 1.483 ms，输出逐位相同
   （属性在 AidLite 2.5.0.284 上可设置且不报错，但本模型无效；输入只有 57.6 KB，拷贝本就微不足道）。
   → 官方示例里注释掉它是有道理的，别折腾。

**结论**：Sim01 可以在 QCS6490 NPU 上跑，INT8 量化对控制输出的影响在千分之几量级
（steering 0.023 / throttle 0.004，相对全量程 ≈2.3% / 0.4%），端到端 1.5 ms 远超车载 20~30 FPS 的
实时要求 —— 瓶颈完全不在推理。**注意**：这里的精度是在 COCO 街景图（跨域）上量的，
换用你 tub 里的真实训练域帧重跑（`--images <tub目录>`）才是有意义的绝对精度。

---

## 4. 坑与对策（都是实测踩出来的）

| # | 现象 | 原因 | 对策 |
|---|---|---|---|
| 4.1 | `aid-pkg install` 命令长期无输出直到超时 | **系统自动更新进程 `unattended-upgrade` 空转 1.5 小时**，死握 `/var/lib/dpkg/lock-frontend`，aid-pkg 调 dpkg 时无限等待 | 先 `kill -KILL` 该进程再停服务（直接 `systemctl stop` 会等满 `TimeoutStopSec` 挂住），并 `systemctl disable apt-daily.timer apt-daily-upgrade.timer` |
| 4.2 | 只升 `aidlite-sdk` 后 NPU 直接失效 | 后端版本没跟上：`StatusCode[100062] AidLite-SDK need backend lowest version [2.5.0.X]` | SDK 与后端**必须同主版本**一起装（`aidlite-qnn240` 等） |
| 4.3 | `aid-pkg install a b c`（多包名）无反应 | aid-pkg **只支持单包名** | 逐个安装；无 TTY 时加 `--without-progress`；被硬杀后留下 `/var/lib/aid-pkg/lock` 需手删（否则后续全报 `being locked`） |
| 4.4 | `aimo.task(task_id)` 跨进程报 `TaskNotExistError` | 未提交的任务在服务端不存在 | **"创建 → 配置 → 提交"必须同一进程完成**；提交后即可跨进程轮询 |
| 4.5 | 轮询拿不到状态 | 状态字段是 `ResultTaskInfo.task_status`，不是 `status` | 用 `task_status`；`usage_time` 是耗时秒数 |
| 4.6 | 加载 AIMO 的 `htp_backend_extensions.json` 报 `Unknown Key: backend_extensions/...` | 该文件里写的是 **AIMO 服务器自己的 x86 路径**（`/home/opt/qcom/aistack/qairt/2.40.0/lib/x86_64-linux-clang/...`） | **默认不要加载**。实测：不加载 11.75ms / 加载 13.32ms，且输出数值逐位相同。仅当模型含自定义 UDO 算子且有设备版扩展库时才需要 |
| 4.7 | 拿错产物文件 → `StatusCode[120000] Initializing QNN Function Points failed` | 误用了 x86 的 `lib*.x86.so.aidem` | 设备上必须用 `*.ctx.bin.aidem` |
| 4.8 | 自定义模型在 AidLite 上加载失败 `StatusCode[110003] Parameter in_tensor_name invalid` | 示例脚本里**硬编码了输入张量名**（如 `input_tensor_name_to_index("images")`），与自研模型的 I/O 名不一致 | 用 `onnx` 包列出实际输入/输出名，同步改脚本（或改模型） |
| 4.9 | `pip install onnx` 把 numpy 升到 2.x 后 AidLite 失效 | pip 会顺带升级 numpy，但 Debian 的 numpy 卸不掉导致事务回滚 | 安装时显式钉住：`pip install --break-system-packages "numpy<2" onnx`；国内源用 `-i https://mirrors.aliyun.com/pypi/simple/` |

---

## 5. 换你的模型：操作清单

**第 0 步 · 先确认模型本身规整**（AIMO FAQ 的硬要求）
```bash
python3 -c "
import onnx; m=onnx.load('your_model.onnx')
print('opset:', [(o.domain or 'ai.onnx', o.version) for o in m.opset_import])   # 建议 12
print('输入:', [(i.name,[d.dim_value if d.HasField('dim_value') else d.dim_param for d in i.type.tensor_type.shape.dim]) for i in m.graph.input])
print('输出:', [(o.name,[d.dim_value if d.HasField('dim_value') else d.dim_param for d in o.type.tensor_type.shape.dim]) for o in m.graph.output])
"
```
- 输入 shape 里**不能有 `?` 或动态维** → 用 onnx 包固定成具体值（如 `[1,3,640,640]`）另存
- 记录输入/输出**张量名**（后面在设备侧要对上）

**第 1 步 · 准备校准集**（影响量化精度，强烈建议）
- 20~50 张**与部署场景同分布**的图片，放一个目录
- 无校准集时可用内置 `imagenet/coco/normal`（能跑通，精度打折）

**第 2 步 · 转换（脚本已备好）**
```bash
python3 /home/aidlux/tools/aimo_convert.py \
  --model /path/your_model.onnx --source-type onnx \
  --device qcs6490 --runtime qnn_2_40 \
  --precision int8 --quant-mode cle --per-channel 1 \
  --calib-mode cv --calib-type custom --calib-dir /path/calib_images \
  --desc "your-model" --out /home/aidlux/models/your_out
# 先 --dry-run 校验参数不消耗配额
```

**第 3 步 · 设备侧冒烟测试**
```bash
python3 /home/aidlux/tools/npu_smoke_test.py /home/aidlux/models/your_out/*.ctx.bin.aidem \
        --info /home/aidlux/models/your_out/qnn_model_info.json --acc 3
```

**第 4 步 · 业务精度验证**
- 用你自己的前/后处理，对比 ONNX-CPU 与 QNN-NPU 输出
- 有偏差时优先：① 改用量身校准集 ② 试 `W8A16`（`--precision int16`）③ 检查是否有算子被回退到 CPU

**其他源格式**：PyTorch / TensorFlow_Lite / TensorFlow_PB / TensorFlow_Save_Model / Caffe / PaddlePaddle / MXNet 均支持（`--source-type`）

---

## 6. 复用脚本清单

**设备侧 `/home/aidlux/tools/`**
| 脚本 | 用途 |
|---|---|
| `aidlux_npu_pipeline.py` | **全流程一键**：转换(可复用/可跳过) → NPU 测速 → CPU 基准 → 张量级+检测级精度 → 加速比报告。支持 `--ctx/--skip-convert/--dry-run/--cpu-backend/--postprocess/--images` |
| `aimo_convert.py` | AIMO 转换（参数化，含 `--dry-run`；密钥从文件读，不出现在命令行） |
| `npu_smoke_test.py` | 通用 NPU 冒烟测试（自动读 `qnn_model_info.json` 取形状，默认不加载 ext） |

**本机 `~/.hermes/aidlux/`（操作设备用，均带多路径自动回退）**
| 脚本 | 用途 |
|---|---|
| `aiderun.sh <脚本>` | 把本地脚本 base64 传到设备落盘执行（避免 stdin 交互把脚本吃掉） |
| `aidev.sh "<命令>"` | 单条命令/片段（走 `bash -s`，不二次解析） |
| `aiput.sh <本地> <远端> [权限]` | 小文件推送（md5 校验） |
| `aiget.sh <远端> <本地>` | 文件取回 |
| `put_secret.sh <本地> <远端文件名>` | 密钥类文件：只经 stdin、落盘 600、不回显 |
| `cputemp.sh` | 设备温度监控脚本（`/usr/local/bin/cputemp`，含 `-a/-c/-q/-j/-n/-w`） |

**凭证**：AIMO API Key 存于设备 `/home/aidlux/.aidlux_cred/aimo_api_key`（600，172 字节）；脚本只从该文件读取。

---

## 7. 未做 / 可选

- [ ] 用**任务相关校准集**重跑一次，量化精度对比（验证 3.3 的推断）
- [ ] `mms login`（需账号密码）→ 从 Model Farm 下参考模型包（含完整前后处理代码）做交叉验证
- [ ] 自研模型的**自定义前后处理**（脱离 YOLOv5 示例，用 AidLite Python API 直接集成）
- [ ] C++ 侧集成（`/usr/local/include/aidlux/aidlite/aidlite.hpp` + `/usr/local/lib/libaidlite.so`，g++ 13.3/cmake 已就绪）
- [ ] 清理死版本 `aidlite-qnn236` 与对应示例（避免误用）
- [ ] 多线程/多核 HTP 配置调优（`htp_config.json` 里的 `perf_profile`、`cores_num`）
