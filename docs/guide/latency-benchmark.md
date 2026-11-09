# 车端时延基准（推理 + 自动驾驶主循环）

> 用途：在真实车端平台上量化「单次模型推理」与「完整自动驾驶主循环」的时延，
> 提供可复跑的命令与可回归的测试，避免再凭猜测判断性能是否够用。
> 建立 2026-11-09（Intel N100 平台实测）。

## 0. 它测什么

| 模块 | 覆盖范围 | 不包含 |
| --- | --- | --- |
| `infer` | 单次 `pilot.run`（图像归一化 + 模型 invoke），走车端真实代码路径 | 取帧、缩放、下发 |
| `loop` | `Vehicle` 主循环：取帧 → `PilotHolder`（缩放+归一化+推理）→ 执行器下发 | WebRTC 视频编码、录制写盘、遥测等生产 Part |

- 实现：`donkeycar/benchmarks/latency_bench.py`
- 测试：`donkeycar/tests/test_latency_bench.py`（自建小模型，无需 mycar 工程/相机，默认纳入常规套件）

## 1. 快速开始

```bash
# 进入项目并激活虚拟环境（见 docs/guide/uv-venv-setup.md）
cd ~/projects/donkeycar
source .venv/bin/activate
```

### 1.1 单次推理时延

```bash
# 指定单个模型（类型按扩展名自动推导：.tflite→tflite_linear，.h5→linear，...）
python -m donkeycar.benchmarks.latency_bench infer \
    --model ~/projects/mycar/models/deployed.tflite

# 扫描目录（递归）下所有模型逐个测
python -m donkeycar.benchmarks.latency_bench infer \
    --scan ~/projects/mycar/models
```

输出示例：

```
deployed.tflite              type=tflite_linear   in=(120, 160, 3)  load=1ms
                             mean    3.12  p50    3.11  p90    3.20  p95    3.33  p99    3.42  max     3.52 ms  ( 320.5 fps, n=200)
```

### 1.2 完整自动驾驶主循环时延

```bash
# 目标 60Hz，跑 1200 次迭代；--image 用真实行车帧（缺省随机帧）
python -m donkeycar.benchmarks.latency_bench loop \
    --model ~/projects/mycar/models/deployed.tflite \
    --rate 60 --iterations 1200 \
    --image ~/projects/mycar/data/images/0_cam_image_array_.jpg
```

输出示例：

```
模型 deployed.tflite（tflite_linear）加载 2 ms
主循环：1200 次迭代 / 20.077 s = 实测 59.77 Hz（目标 60Hz，周期 16.73 ms）
各 Part 主循环内耗时（ms）：
  MockCamera                   mean    0.01  p50    0.01  p95    0.01  p99    0.01  max     0.09
  PilotHolder                  mean    4.06  p50    4.01  p95    4.23  p99    5.60  max     9.55
  _DummyActuator               mean    0.00  p50    0.00  p95    0.01  p99    0.01  max     0.03
```

## 2. 参数速查

`infer`：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--model` | — | 模型路径，可重复指定 |
| `--scan` | — | 递归扫描该目录下所有模型 |
| `--type` | 按扩展名推导 | 模型类型，如 `tflite_linear` / `linear` / `torch_linear` |
| `--iterations` / `--warmup` | 200 / 10 | 测量 / 预热迭代数 |
| `--width` `--height` `--depth` | 320 / 240 / 3 | 传入模型的配置图像尺寸 |

`loop`：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--model` | 必填 | 模型路径 |
| `--rate` | 60 | 主循环目标频率 Hz（应等于 `DRIVE_LOOP_HZ`） |
| `--iterations` | 1200 | 迭代数（`iterations/rate` ≈ 运行秒数） |
| `--image` | 随机帧 | 用作相机帧的图片 |
| `--width` `--height` `--depth` | 320 / 240 / 3 | 配置图像尺寸 |

## 3. 结果怎么读

- **推理够不够快**：把 `infer` 的 `p99` 与主循环预算 `1000/DRIVE_LOOP_HZ`（60Hz → 16.7ms）对比；接近或超过预算即会掉帧。
- **主循环是否稳定**：看 `实测 X Hz` 是否贴近目标；再看 `PilotHolder` 的 `p99/max` 是否出现长尾（长尾通常来自后台负载或内存抖动）。
- **模型输入与相机分辨率不一致会额外开销**：如相机 320×240、模型 120×160 时，`PilotHolder` 每帧都要缩放（约 +1ms）。原生匹配分辨率可省去这一步，但大分辨率推理本身更贵，需实测权衡。

## 4. 跑测试（回归）

```bash
cd ~/projects/donkeycar/donkeycar/tests
python -m pytest test_latency_bench.py -v
```

测试自建 120×160 的 `KerasLinear` → TFLite 模型并断言：统计量单调、输入形状正确、
主循环能跑满迭代数且达成频率在合理区间。**只做功能性/宽松区间断言，不做硬性时延墙**，
以免在高负载 CI 上误报。

## 5. 本机基线（Intel N100，4 核 / 7GB，2026-11-09）

测量时有后台负载（python ~31% CPU + node），结果偏保守。

| 模型 | 输入 | mean | p50 | p95 | p99 | max |
| --- | --- | --- | --- | --- | --- | --- |
| `mycar/models/deployed.tflite` | 120×160×3 | 3.12 | 3.11 | 3.33 | 3.42 | 3.52 ms |
| `donkeycar/models/DKG-1.tflite` | 120×160×3 | 3.10 | 3.09 | 3.25 | 3.32 | 3.41 ms |

完整主循环（`deployed.tflite`，相机 320×240，目标 60Hz）：
**实测 59.77 Hz（周期 16.73 ms）**，`PilotHolder` mean 4.06 / p99 5.60 / max 9.55 ms。
推理仅占 60Hz 预算（16.67ms）约 25%，余量充足。

## 6. 注意事项

1. **模型格式决定量级**：`.tflite` 是车端自动驾驶的推荐格式；Keras float（`.h5` 的 `linear`）
   单帧可达数十 ms，会远超预算。部分旧 `.h5` 在 TensorFlow 2.19 / Keras 3 下无法反序列化，
   基准会对该文件报「失败」并跳过，不影响其余模型。
2. `loop` 用 `MockCamera`（固定帧、无真实采集）与占位执行器，因此测的是计算链路本身；
   真机上 WebRTC 视频编码、录制写盘等并发 Part 会叠加额外负载。要评估端到端上限，
   请结合真机 `curl /api/drive/webrtc/stats` 的 `source_fps` 一起看。
3. 结果受机器后台负载影响显著，比较不同模型/改动时应在相近负载下测量。
