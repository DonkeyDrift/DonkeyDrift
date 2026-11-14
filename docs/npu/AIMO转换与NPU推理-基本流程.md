# AIMO 转模型 + 设备侧 NPU 推理 —— 基本流程

> 岗位速查版。完整实测记录见 `AidLux-QCS6490-AIMO-NPU-跑通记录.md`
> 设备：AidLux / Qualcomm QCS6490（sm7325）· SDK：AidLite 2.5.0.284 + aidlite-qnn240
>
> **要跑完整流程（转换 → 测试 → 精度 → 加速比）直接用 `../scripts/aidlux_npu_pipeline.py`**，
> 一条命令出报告；本文是它的原理拆解与手工步骤，便于排障时逐步定位。

---

## 总览

```
                    你的模型 (ONNX / PyTorch / TFLite / TF / Caffe / Paddle / MXNet)
                                     │
        ┌────────────────────────────▼─────────────────────────────────┐
        │ ① AIMO 云转换 (设备上没有 QNN 转换器, 转换在云端做)             │
        │   login → new_task → submit → poll → download                 │
        │   目标平台: Qualcomm_QCS6490 + QNN_2_40                       │
        │   量化: INT8 / cle / per-channel + 校准集                      │
        └────────────────────────────┬─────────────────────────────────┘
                                     │  产物 zip
                                     │   ├─ *.ctx.bin.aidem      ← 设备用这个 (ARM)
                                     │   ├─ qnn_model_info.json  ← 输入输出形状
                                     │   └─ lib*.x86.so.aidem    ← PC 仿真用, 设备别用
                                     ▼
        ┌──────────────────────────────────────────────────────────────┐
        │ ② 设备侧 AidLite 推理                                         │
        │   Model.create_instance → set_model_properties                │
        │   → Config(TYPE_QNN240 + TYPE_DSP) → InterpreterBuilder       │
        │   → init → load_model → set_input_tensor → invoke             │
        │   → get_output_tensor → destroy                              │
        └────────────────────────────┬─────────────────────────────────┘
                                     ▼
                                  业务结果
```

---

## 一、API 转模型（AIMO Python SDK）

### 1. 环境准备（一次性）

```bash
pip install aplux_aimo -i https://mirrors.aidlux.com/simple/
```
API Key 获取：登录 https://aimo.aidlux.com/ → 右上角用户图标 → 「用户密钥」。
**建议存文件（600 权限），不要写进代码/命令行**：`~/.aidlux_cred/aimo_api_key`

### 2. 七个步骤

| 步骤 | 调用 | 说明 |
|---|---|---|
| ① 登录 | `aimo = AimoApi(); aimo.login(api_key=k)` | 默认服务 `https://aimo.aidlux.com/` |
| ② 建任务 | `aimo.new_task(source_model_type, source_model_file, target_device, target_runtime, description, quantize_options=...)` | **会顺带上传模型文件** |
| ③ 配量化 | `QuantizeOptions(...)` | 作为 kwarg 传给 `new_task` |
| ④ 传校准集 | `task.upload_calibration_data_files(files=[...])` | 仅自定义图片校准时需要，**必须与②在同一进程** |
| ⑤ 提交 | `task.submit()` | 提交后服务端才真正存在该任务 |
| ⑥ 轮询 | `task.get_result().task_status` | 直到 `SUCCESS` / 失败；失败看 `task.get_info_log()` |
| ⑦ 下载 | `task.download(file_mode=DownloadFileMode.OutputModel, output_file_path=DIR)` | 得到 `*_save_path.zip` |

### 3. 关键参数

| 参数 | 取值 | 备注 |
|---|---|---|
| `source_model_type` | `ONNX` / `PyTorch` / `TensorFlow_Lite` / `TensorFlow_PB` / `TensorFlow_Save_Model` / `Caffe` / `PaddlePaddle` / `MXNet` | |
| `target_device` | **`Qualcomm_QCS6490`** | 也可 QCS8250/8550/8625、Snapdragon 系列 |
| `target_runtime` | **`QNN_2_40`**（或 `Qairt_QNN_2_40`） | **必须与设备后端 `aidlite-qnn240` 匹配**；QNN_2_36 及更早对不上 |
| `quantize_precision` | `INT8`（=`A8_W8`）/ `INT16`（=`A16_W8`）/ `FP16` | INT8 最快最稳 |
| `quantize_mode` | `['cle']`（=`Enhanced_CLE`）/ `['ada']` | **用 cle**：YOLOv5s 640 实测 4 分 24 秒；ada 可能极慢（文档称数天） |
| `enable_per_channel_quantize` | `True` | |
| `calibration_data_mode` | `'cv'`(=Image) / `'random'` / `'nlp'` / `'nlp_npy'` | 图像任务用 `'cv'` |
| `calibration_dataset_type` | `'custom'`（+目录）/ `'imagenet'` / `'coco'` / `'normal'` / `'face'` | **用任务同分布图片（custom）精度最好**；内置 ImageNet 可跑通但精度打折 |

### 4. 最小可运行代码

```python
from aplux_aimo import AimoApi
from aplux_aimo.enums import (SourceModelType, TargetDevice, ModelRuntime,
                             ModelDataPrecision, DownloadFileMode)
from aplux_aimo.base_data import QuantizeOptions

key = open('/home/aidlux/.aidlux_cred/aimo_api_key').read().strip()
aimo = AimoApi(); aimo.login(api_key=key)

q = QuantizeOptions(
    quantize_precision=ModelDataPrecision.INT8,
    quantize_mode=['cle'],
    enable_per_channel_quantize=True,
    calibration_data_mode='cv',
    calibration_dataset_type='imagenet',      # 或 'custom' + upload_calibration_data_files
)

task = aimo.new_task(                          # ← 同一个进程里必须一路做完到 submit
    source_model_type=SourceModelType.ONNX,
    source_model_file='/path/your_model.onnx',
    target_device=TargetDevice.Qualcomm_QCS6490,
    target_runtime=ModelRuntime.QNN_2_40,
    description='my-model',
    quantize_options=q,
)
task.submit()

import time
while True:
    st = str(task.get_result().task_status)
    print(st)
    if 'SUCCESS' in st.upper() or 'FAIL' in st.upper(): break
    time.sleep(15)

if 'SUCCESS' in st.upper():
    print(task.download(file_mode=DownloadFileMode.OutputModel,
                        output_file_path='/home/aidlux/models/out'))
```

> 现成脚本：`aimo_convert.py`（含 `--dry-run` 免配额校验）

### 5. 四条铁律

1. **「建任务 → 配量化 → 上传校准 → 提交」必须在同一个进程完成** —— 未提交的任务在服务端不存在，跨进程 `aimo.task(id)` 会抛 `TaskNotExistError`
2. **状态字段是 `task_status`**（不是 `status`）；`usage_time` 是耗时秒数
3. 设备上必须用 **`*.ctx.bin.aidem`**；`lib*.x86.so.aidem` 是 x86 仿真库，用了报 `StatusCode[120000]`
4. **不要加载**产物包里的 `htp_backend_extensions.json`（里面是 AIMO 服务器的 x86 路径，设备上报 `Unknown Key`，实测反而慢 1.5ms 且输出逐位相同）

---

## 二、设备侧运行推理（AidLite）

### 1. 六个步骤

| 步骤 | 调用 | 说明 |
|---|---|---|
| ① 建模型对象 | `model = aidlite.Model.create_instance(ctx_path)` | 返回 `None` 即路径/文件问题 |
| ② 声明形状 | `model.set_model_properties(input_shapes, aidlite.DataType.TYPE_FLOAT32, output_shapes, aidlite.DataType.TYPE_FLOAT32)` | 形状取自产物包 `qnn_model_info.json` |
| ③ 建配置 | `cfg = aidlite.Config.create_instance()` → `cfg.framework_type = aidlite.FrameworkType.TYPE_QNN240` → `cfg.accelerate_type = aidlite.AccelerateType.TYPE_DSP` | `TYPE_DSP` 才是 NPU |
| ④ 建解释器 | `it = aidlite.InterpreterBuilder.build_interpreter_from_model_and_config(model, cfg)` | |
| ⑤ 初始化 | `it.init()` → `it.load_model()` | 非 0 即失败，看上方 `StatusCode` |
| ⑥ 推理循环 | `it.set_input_tensor(0, x)` → `it.invoke()` → `it.get_output_tensor(i)` | 输出**按索引**取（按名字已弃用）；结束 `it.destroy()` |

### 2. 关键点

- **输入形状用 NHWC**：`[[1, H, W, 3]]`。AIMO 会把 ONNX 的 NCHW 自动转成 NHWC，所以设备侧不用自己转置
- **形状别硬编码**：从 `qnn_model_info.json` 的 `inputDimensions` / `outputDimensions` 读
- **`.bin`/ctx 模型只能 `TYPE_DSP`**：试 CPU/GPU 会被拒（`StatusCode[120010] QNN's .bin model can only use DSP`）
- **设备必须已激活**，否则 NPU 不可用（日志会打 license ID）
- **前后处理要自己写**：AidLite 只做推理；官方示例的 YOLOv5 前后处理在
  `/usr/local/share/aidlite/examples/aidlite_qnn240/python/qnn_yolov5_multi.py`
- 输入张量名要与模型一致（示例里常有硬编码，自研模型需同步改，否则 `StatusCode[110003]`）

### 3. 最小可运行代码

```python
import json, numpy as np, aidlite

ctx = '/path/xxx.qnn240.ctx.bin.aidem'
info = json.load(open('/path/qnn_model_info.json'))
in_shapes  = list(info['inputDimensions'].values())     # [[1,640,640,3]]
out_shapes = list(info['outputDimensions'].values())    # [[1,80,80,255],[1,40,40,255],[1,20,20,255]]

model = aidlite.Model.create_instance(ctx)
model.set_model_properties(in_shapes, aidlite.DataType.TYPE_FLOAT32,
                          out_shapes, aidlite.DataType.TYPE_FLOAT32)

cfg = aidlite.Config.create_instance()
cfg.framework_type  = aidlite.FrameworkType.TYPE_QNN240
cfg.accelerate_type = aidlite.AccelerateType.TYPE_DSP      # NPU

it = aidlite.InterpreterBuilder.build_interpreter_from_model_and_config(model, cfg)
assert it.init() == 0 and it.load_model() == 0, "初始化失败, 看上方 StatusCode"

x = np.zeros(in_shapes[0], dtype=np.float32)               # TODO: 换成你的前处理结果
it.set_input_tensor(0, x)
it.invoke()
outs = [it.get_output_tensor(i) for i in range(len(out_shapes))]
it.destroy()
# TODO: 你的后处理
```

> 现成脚本：`npu_smoke_test.py`（零输入冒烟测试；自动读形状；任意模型通用）

---

## 三、实测基准（供对标）

| 指标 | 值 |
|---|---|
| AIMO 转换（YOLOv5s 640 → INT8，CLE） | **263.87 s** |
| 设备 NPU 推理（完整 YOLOv5s 流程） | **12.62 ms/图** |
| 设备 NPU 推理（零输入冒烟） | 11.75 ~ 13.75 ms |
| CPU 对照（ONNX / TFLite） | 438.6 ms / 206.5 ms /图 |

---

## 附：与项目 venv（TF 2.19）的兼容性坑（2026-10-07 实测）

本机项目环境 `.venv` 是 **Python 3.12 + TF 2.19**，而 TF 2.19 自己声明：

```
protobuf !=4.21.0..4.21.5,<6.0.0dev,>=3.20.3
numpy    <2.2.0,>=1.26.0
ml-dtypes<1.0.0,>=0.5.1
```

因此 **不要把 onnx / tf2onnx 装进项目 venv**：

- `onnx 1.23.x` 由 protobuf **≥6.31** 的 gencode 生成 → 会强制把 protobuf 顶到 6/7，
  而 TF 2.19 要 `<6`；表现为 `AttributeError: 'MessageFactory' object has no attribute 'GetPrototype'`
  以及 `VersionError: gencode 6.31.1 runtime 5.29.6`；
- 反过来把 protobuf 钉回 5.29.6，则 `import onnx` 直接失败 —— **两者不可共存于同一解释器**；
- 顺带：`onnx` 的依赖链还会把 numpy 顶到 2.x（本项目要求 numpy 1.26.4）。

**正确做法**：转换源不需要 onnx。AIMO 的 `SourceModelType` 原生支持
`TensorFlow_Lite` / `TensorFlow_PB` / `TensorFlow_Save_Model` / `PyTorch` / `Caffe` / `MXNet` / `PaddlePaddle`，
`donkeycar/tools/aimo_npu_convert.py` 已按扩展名**自动识别**源类型，`.tflite` 可直接作为源：

```bash
python -m donkeycar.tools.aimo_npu_convert --onnx models/DKG-1.tflite --out out/ --calib-tubs ~/mycar/data
# [0/5] 源模型类型: SourceModelType.TensorFlow_Lite  (DKG-1.tflite)
```

若确需 onnx（例如要先用 tf2onnx 做结构改造），请**另建独立 venv**（如 `~/.venvs/onnx-tools`）做转换，
产物文件再交给本脚本；不要让 onnx 与 TF 2.19 共享解释器。
