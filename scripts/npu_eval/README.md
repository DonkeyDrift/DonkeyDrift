# scripts/npu_eval —— NPU 模型 vs float32 参考的固定流程对照

四个脚本一条流水线：**固定输入集 → 两引擎各跑一遍 → 逐头统计**。

```bash
SET=~/eval_sets/dkg1
python3 scripts/npu_eval/make_eval_set.py --tub ~/projects/mycar/data --out-dir $SET --frames 21 --syn 5
.venv/bin/python scripts/npu_eval/ref_eval.py models/DKG-1.tflite $SET/ref.json \
        --set-dir $SET --input-scale raw --car-dir ~/projects/mycar
python3 scripts/npu_eval/npu_eval.py ~/models/DKG-1_xxx.aidem $SET/npu.json --set-dir $SET --input-scale div255
python3 scripts/npu_eval/cmp_eval.py $SET/ref.json $SET/npu.json
```

## 为什么要「固定输入集」

- 车载 tub **重复帧极多**（实测 787 帧里仅 272 帧唯一）：直接取前 N 张会让"连续帧输出相同"伪装成
  模型退化，也会让"测试集不合格"成为假象 → 先 `md5` 去重，再（有 `catalog_manifest.json` 时）按真值分层抽样。
- 只喂真实帧时，若参考输出恰好**单侧**，量化会出现"输出头半死"（反号值被压成 0）→
  合成图（黑/白/灰/左右分块/上下分块）能强制把输出推到两个符号，是发现该坑最快的手段。
  完整机制与判据见 `docs/npu/AIMO量化校准-单侧校准陷阱.md`。

## 输入尺度（最容易搞错的一环）

| 引擎 | 尺度 | 依据 |
|---|---|---|
| **NPU（AIMO 产物）** | `/255` | AIMO 的图像约定（官方示例 `img_input = img_input / 255`） |
| **float32 源模型** | **跟模型自身走**（本例 `raw` = 0~255） | 判据：把 0~255 与 /255 两种尺度都喂一遍，哪个对黑/白极端图**敏感**（输出变化 >0.1）就是它训练时的等效尺度 |

## 实测样例（DKG-1，21 帧去重真实图）

| 模型 | steering 平均\|Δ\| / 最大\|Δ\|（非零） | throttle 平均\|Δ\| / 最大\|Δ\|（非零） |
|---|---|---|---|
| INT8（仅 tub 校准） | 0.2307 / 0.3384（**0/21** ✗） | 0.0235 / 0.0559 |
| INT16（仅 tub 校准） | 0.2307 / 0.3384（**0/21** ✗） | 0.0017 / 0.0043 |
| **INT16（混入合成图校准）** | **0.0031 / 0.0058（21/21 ✓）** | **0.0020 / 0.0036（21/21 ✓）** |

合成输入那一栏能一眼看出"哪个头只在单侧有响应"：

```
输入            参考 steer/throt      INT16(仅 tub)        INT16(+合成图)
全黑            +0.0841/+0.4629      +0.0847/+0.0000      +0.0871/+0.4599
上黑下白        -0.0993/-0.9292      +0.0000/-0.9296      -0.1053/-0.9293
```

## 使用注意事项

- **回归/标量输出模型不要用余弦相似度**：单元素向量的余弦会因符号翻转误报 `-1`（曾把 0.023 的偏差
  误报成"精度损失偏大"）→ 本工具一律**逐值对照**，并以**绝对偏差**为主、相对误差仅作参考。
- `npu_eval.py` 从模型同目录的 `qnn_model_info.json` 读形状 → **模型目录必须带它**。
- **同一个 `Model` 对象不要换 `accelerate_type` 复用**（DSP 成功后再试 CPU/GPU 会段错误）→
  每个模型/后端各起一个进程。
- aidlite 的 C 层会把噪声打到 stdout；本工具只打印自己那几行（`✓ ...` / 统计表）。
