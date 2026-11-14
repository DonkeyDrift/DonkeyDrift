# A1 板定位结论：只做推理，不做训练（2026-10 实测依据）

> 结论沉淀自 2026-10-08/09 两次整机死机复盘与 2026-10-09/10 的训练内存专项研究
> （修复见 CHANGELOG `2026-10-09 (265)`，原始数据与脚本在 `~/projects/bench_tubs/`）。
> 用户决策（2026-10-10）：**A1 板定位为推理设备；训练一律走远端 GPU
> （train_online 打包上传流）。板上训练仅保留应急配方。**

## 一、定位结论与依据

| 维度 | 推理（板上） | 训练（板上） |
|---|---|---|
| 内存 | TFLite 推理 + drive 全链路 ~几百 MB，余量充足 | 唯一安全档 BS=32 峰值 1491.5MB，**贴 1.5GB 红线** |
| 速度 | TFLite p50 13.7ms@320x240（60Hz 预算 16.7ms 内）；drive 主循环 58.7Hz | 20k 帧 2 epochs = 27 分钟（BS=32，822s/epoch），无收益 |
| 风险 | 无 | BS=128 必死（3.4GB，即两次死机的直接形态）；memguard 随时可能击杀 |

结论：训练在板上**内存不可行 + 速度无收益**，双输；远端 GPU 训练流分辨率随 cfg
打包带走，不受影响。`mycar/myconfig.py` 的 `BATCH_SIZE=128` 保留（服务远端 GPU）。

## 二、内存实测矩阵（本机 A1，合成 20k 帧 320x240 tub，linear，2 epochs）

| 配置 | 峰值 RSS | 结局 |
|---|---|---|
| 改动前缓存行为（ARRAY 无界，3000 帧 tub 外推） | +608MB/2400 训练帧，线性增长（2 万帧 ≈ 4.4GB） | 死机根因之一 |
| BS=128 + 默认分配器（= 事故实况） | **3431MB** | Epoch 2 被 memguard 击杀（journal 留痕 avail 834→579MB） |
| BS=128 + prefetch(1) | ~3200MB | 预取缓冲不是主因 |
| BS=64 + 默认 | 3307MB（E 实验，2 epochs 完整） | 存活但深入警戒区 |
| BS=64 + mallopt(ARENA=2) | 1.9~2.2GB（分解实验） | 仍偏险 |
| **BS=32 + CACHE_MAX_BYTES=128MiB + mallopt** | **1491.5MB** | **2 epochs 跑通，loss 0.065→0.021 正常收敛，memguard 静默** |

分相数据（BS=64，`run_decompose.py`）：import TF 2.19 = 490MB → 建模型 + 2 万
records = 575MB → 纯 tf.data 取 50 批（无训练）= +~1GB → fit 工作区再 +~1.2GB。
图像缓存钉在预算值（256MiB→268416000B/1165 条；128MiB→582 条），多 epoch 不涨。

## 三、根因是两层的（教训核心）

1. **无界图像缓存**（`TubRecord._image` 永驻，ARRAY 默认）——已修：全局字节预算
   LRU（`donkeycar/pipeline/image_cache.py`，新配置 `CACHE_MAX_BYTES` 默认 256MiB）。
2. **tf.data float64 批量流转的分配器驻留 + 模型激活地板**——与预取无关
   （prefetch(1) 无改善）、与 BFC 分配器无关（`TF_CPU_ALLOCATOR_USE_BFC` /
   `TF_CPU_BFC_MEM_LIMIT_IN_MB` / `TF_ENABLE_ONEDNN` 实测仅 0~70MB）。代码侧唯一
   有效手段是 TF import 前 `mallopt(M_ARENA_MAX=2)`（-600MB~1GB，已内建于
   `pipeline/training.py`）；再往下**只能降 BATCH_SIZE**——BS=128 时激活+工作区
   ~2GB 起步，物理不可行。float64 批体积速算：`BATCH×H×W×3×8B`
   （BS=128@320x240 = 235.9MB/批）。

事故观测 3.4GB < 缓存估算 4.4GB 的差异本身就是第二层根因存在的线索——当时被
"数量级吻合"带过了。**修完第一层后验收 run 又死了一次，才挖出第二层：每次修复
后必须重新实测，不能宣布胜利。**

## 四、应急板上训练配方（仅在必须时）

```python
# myconfig.py 追加（其余默认；mallopt 已内建，无需配）
BATCH_SIZE = 32                # 64=1.9~2.2GB 贴警戒；128=3.4GB 必死
CACHE_MAX_BYTES = 134217728    # 128MiB；大 tub 下 LRU 命中率→0，预算纯属封顶
```

- 跑前 `sudo /usr/local/bin/memguard --dry` 看余量与卫士目标；
- 预期：稳态 ~1.0GB / 峰值 ~1.5GB / 20k 帧每 epoch ~14 分钟（8 核 CPU）；
- 小 tub（≲1200 帧）可全量进缓存（命中 0.001ms/帧 vs 未命中 0.55ms/帧），
  256MiB 默认即可；NOCACHE 解码成本 0.55ms/帧，一个 2 万帧 epoch 仅 +11s。

## 五、可复用手法（本次验证过的）

- **分阶段 RSS 定位法**：import TF → 建模型 → get_records → 纯管线取批 → fit，
  每阶段记 `VmRSS`+采样线程峰值（`/proc/self/status` + `ru_maxrss`），
  `~/projects/bench_tubs/run_decompose.py` 可直接复用。
- **`MALLOC_ARENA_MAX` 运行中设环境变量无效**：glibc 在进程首次 malloc（解释器
  启动）时就读掉了；必须 `ctypes.CDLL(None).mallopt(-8, 2)`（M_ARENA_MAX=-8）。
- **基准工具**：`donkeycar/benchmarks/image_cache_bench.py`（gen/epoch/decode
  三子命令，改动前后通用，cache-stats 行自标注 build 状态）。
- **取证**：`sudo journalctl --since ... | grep memguard`（tag=memguard，WARN 即
  接近 400MB 阈值，含 top5 进程内存）；memguard 击杀训练进程是预期保护，别绕。
- nohup+重定向下 stdout 块缓冲：keras 进度条要 `tr '\r' '\n'` 展开看，logging
  走 stderr 实时；`pgrep -f` 会匹配轮询 shell 自身 cmdline（自匹配坑）。
- LRU 在"固定顺序循环访问 + 容量 < 工作集"下命中率为 0——缓存是
  "装得下就热、装不下就流"的器件，给大 tub 设大预算不会提速。

## 六、不要顺手"修"的东西（语义耦合）

- `CACHE_POLICY` getattr 回退默认必须保持 `'ARRAY'`：`test_train.py::
  test_training_pipeline` 依赖默认缓存命中 + "processor 结果驻留后、下次带不同
  processor 的调用作用在缓存值上"的槽位语义（该文件 227 行注释）。
- `CACHE_IMAGES` 是历史死键（存了不用）——"修活"它（让 False 真的关缓存）会
  让上述测试翻车，别动。
- 模板 `cfg_basic.py` 是 CRLF 行尾：只允许二进制方式定点插入，禁文本模式改写。

## 资产清单

- 代码：`donkeycar/pipeline/image_cache.py`（有界 LRU）、`types.py`（属性槽位）、
  `training.py`（mallopt + 缓存日志）、模板 ×2（`CACHE_MAX_BYTES`）。
- 测试：`donkeycar/tests/test_image_cache.py`（14 项，含预算不变量与语义锁定）。
- 数据：`~/projects/bench_tubs/`（tub3k/tub20k、run_experiment.py、
  run_decompose.py、exp_*.log / acceptance.log / e2e_train.log 原始记录）。
