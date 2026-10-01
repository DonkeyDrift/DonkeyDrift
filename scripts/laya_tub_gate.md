# laya_tub_gate —— Donkeycar tub 离线数据质量阀门

用 **Laya 决策模型**（或纯规则基线）给采集到的 tub 数据打分、归因缺陷、按机动类型做类别平衡。
**离线工具，不是车上模块**——核心价值就是对 20Hz 行车链路零风险。

```
图像 + 遥测 → 滑动窗口 → 十几个统计量 → 结构化文本 → Laya 三原语（noul/score/choice）
```

一句话本质：**用文本决策模型，在"遥测统计量"这一层做数据筛选，而不是在像素层做。**
它替代的是人工 tubclean 和手写 if-else 清洗规则，不是替代 CNN。

---

## 一、方案合理性评估（开发前的结论）

### 成立的部分

| 设计点 | 评价 |
|---|---|
| 完全离线，不碰实时链路 | ✅ 正确。数据清洗天然该在训练前做，放车上毫无收益还引入风险 |
| 数值桥（十几个统计量 → 文本） | ✅ 方向正确。Laya 是文本编码器看不了图，这是唯一可行路径 |
| report 默认 + delete 走官方 `Tub.delete_records()` | ✅ 软删除可恢复，不手改 catalog 是官方红线，遵守了 |
| export 出新 tub 而非原地改 | ✅ 推荐 path，训练管线无侵入 |
| 强制内置规则基线做 A/B | ✅ **全案最专业的一条**。零训练对照让"Laya 是否值得"变成可测命题 |
| `maneuver` 分类做类别平衡 | ✅ ROI 最高。驴车数据 80%+ 直行导致"永远直行"病，比数据脏更致命 |
| 不训练/不微调、不用视觉模型、不用闭源 API | ✅ 定位清晰，约束合理 |

### 需要泼冷水的部分（诚实结论）

1. **"校准概率无需重新标定"这个核心卖点不成立（出厂状态下）。**
   `laya` 包自身的文档承认：shipped checkpoints 是 **过度自信** 的，
   `laya-multilingual` 甚至没有附带拟合好的温度。
   "输出的 noul 概率可直接当阈值用"只有在**用标注数据拟合过温度之后**才成立
   （`laya.fit_temperatures()`，比训练轻得多但仍是"要有标注"）。
   因此本工具的 eval 模式把 **ECE 对比做成了硬性验收**，而不是宣传语。

2. **零样本决策能力存疑。** 社区评测显示 Laya 的 typed-decisions 零样本分数
   接近随机（0.362）。在我们这种"15 个数字渲染成文本"的强领域偏移输入上，
   不能预设它比 20 行规则强。**先跑 `--engine heuristic`，把 Laya 当候选挑战者。**

3. **信息瓶颈客观存在。** 15 个统计量喂给任何分类器（包括逻辑回归）信息量都一样；
   Laya 的优势只剩"零训练 + 校准概率"。这正是必须 A/B 的原因。

### 草稿（附件 laya_tub_gate.py）中发现并已修复的缺陷

| # | 缺陷 | 后果 | 修复 |
|---|---|---|---|
| 1 | **索引坐标系混用**：`bad_idx` 用 `_index` 值的 `range(start, end+1)`，`keep_idx` 用位置 `range(len(records))` | tub 里若有软删除记录（索引有空洞），export/delete 会**删错行**——坏数据留在导出结果里 | 窗口携带真实 `_index` 列表，全程单坐标系（有回归测试） |
| 2 | **读不到 tub_v2 的软删除状态**：v2 的 `delete_records()` 只写 manifest 的 `deleted_indexes`，catalog 行内无 `_deleted` 标记 | 已删记录被当活记录读回来 | 解析 manifest.json 的 `deleted_indexes` 并过滤 |
| 3 | v1 回退排序用字典序 | `record_10.json` 排在 `record_2.json` 前面，帧序错乱 | 数字排序 |
| 4 | export 模式图像读两次，且复用 64×48 灰度缓存做合法性检查 | 浪费 IO；语义混乱 | 分离 `load_gray`（特征）与 `load_rgb`（导出保真） |
| 5 | 空记录时 `records[0]` 直接 IndexError | 崩溃而非报错 | 明确的 `sys.exit` 提示 |
| 6 | 报告 action 查找 O(n²) | 万帧级变慢 | 预建 dict |
| 7 | `predict` 逐条调用 | 未用包自带的 `predict_batch`（GPU 上快数倍） | 批量分块 + 进度 |
| 8 | 注释说"只对窗口首尾采样"但代码全量加载 | IO 浪费 | 只加载落入窗口的帧 |

---

## 二、安装

```bash
# 最小依赖（report 模式 + 规则引擎 + 合成 eval）
pip install numpy pillow

# Laya 引擎（可选，拖带 torch/transformers，约 2GB；首次运行另需从 HF 下载权重）
pip install laya

# delete / export 模式需要本仓库的 donkeycar（开发安装：pip install -e .）
```

## 三、快速上手（推荐顺序）

```bash
# 第 1 步：规则基线出报告，肉眼核对缺陷归因是否靠谱
python scripts/laya_tub_gate.py --tub ~/mycar/data/tub_001 --engine heuristic

# 第 2 步：合成基准 A/B（不需要 tub；装了 laya 会两个引擎一起跑）
python scripts/laya_tub_gate.py --mode eval

# 第 3 步（可选）：Laya 引擎出报告对比
python scripts/laya_tub_gate.py --tub ~/mycar/data/tub_001 --engine laya

# 第 4 步：确认无误后，export 一个清洗+平衡的新 tub（原数据不动）
python scripts/laya_tub_gate.py --tub ~/mycar/data/tub_001 --engine heuristic \
    --mode export --out ~/mycar/data/tub_clean --balance --straight-keep 0.5

# 用新 tub 训练
donkey train --tub ~/mycar/data/tub_clean --model ~/mycar/models/pilot.h5
```

## 四、四种模式与参数

| 模式 | 行为 |
|---|---|
| `report`（默认） | 只输出诊断报告 jsonl，**绝不改动数据** |
| `delete` | 坏窗口覆盖的记录交给 `Tub.delete_records()` 软标记（UI 可恢复） |
| `export` | 导出清洗 + 平衡后的**新 tub**，原数据不动（推荐） |
| `eval` | 合成标注基准 A/B（准确率 / ECE / 缺陷归因）；`--labels` 可指向人工标注文件做真实校准评估 |

```
--tub             tub 目录（report/delete/export 必填）
--mode            report | delete | export | eval   默认 report
--engine          laya | heuristic                  默认 laya
--model           convaiinnovations/laya | laya-multilingual | laya-typed-decisions
--window          窗口帧数，默认 10（20Hz 下 ≈ 0.5s）
--stride          步长，默认 5（窗口重叠一半）
--threshold       is_clean 阈值，默认 0.35
--balance         对 straight 窗口随机降采样做类别平衡
--straight-keep   直行保留比例，默认 0.5
--seed            降采样随机种子（默认 0，可复现）
--no-vision       跳过视觉特征只读遥测（快很多，抓不出撞墙静止）
--out             export 目标路径
--report          报告/评估输出路径（默认 <tub>/laya_gate_report.jsonl）
--labels          eval 模式：人工标注过的 report jsonl（每行加 "label_clean": 0/1）
--eval-windows    eval 合成基准窗口数，默认 300
```

### 决策语义（重要）

- **保守并集**：stride < window 时窗口重叠，一条记录只要被任何一个坏窗口覆盖就会被剔除。
  缺陷（如撞墙静止）通常持续存在，宁可多删边界帧也不放过坏段。
- **窗口尾部不覆盖**：`len % stride` 的尾部残帧不属于任何完整窗口，不会被剔除。
- **erratic_steering 不是删了完事**：它往往说明转向增益没调好或采集手抖，删掉等于掩盖问题，
  应去补采或调参。report 里的缺陷直方图就是补采清单。
- **quality 低分段 ≠ 删**：分低的段是"该去补采的地方"。

### 人工标注做真实 ECE 验证（验收红线）

1. 跑 report 得到 `laya_gate_report.jsonl`；
2. 随机抽 ~100 行，人工加 `"label_clean": 1`（可保留）或 `0`（有缺陷）；
3. `python scripts/laya_tub_gate.py --mode eval --engine laya --labels annotated.jsonl`；
4. **红线**：若 Laya 的 ECE 明显高于 heuristic，说明 Laya 方案在当前checkpoint下不成立，
   就用规则引擎交付——本工具两种引擎都支持，切换零成本。

## 五、验证结果

### 冒烟测试（需求 5.1）

合成 tub：前 40 帧巡线（`angle=0.3·sin(i/8)`、`throttle=0.5`、噪声图像），
后 20 帧撞墙静止（恒定亮画面、`throttle=0`）。规则引擎结果：

- 纯静止窗口（start≥40）全部命中 `stationary_stall`，`is_clean=0.05 < 0.35` ✅
- 纯巡线窗口全部 `none / clean=1.0` ✅
- 巡线→静止的过渡窗口因亮度突变被判 `off_track`（合理行为）✅
- 见 `donkeycar/tests/test_laya_tub_gate.py::TestHeuristicSmoke`（CI 可重复）

### 合成基准 A/B（需求 5.2 的自动化部分，300 窗口，实测）

| 引擎 | 准确率 | ECE | 缺陷归因准确率 | is_clean 均值 |
|---|---|---|---|---|
| heuristic | **99.0%** | 0.084 | **99.0%** | 0.684 |
| laya（零样本） | 60.0% | 0.067 | 8.0% | 0.635 |

环境：laya 0.3.22 / transformers 5.18 / torch 2.14，Apple Silicon CPU，
`convaiinnovations/laya`（ModernBERT-large 421M），吞吐 ≈ 7 窗口/秒
（1 万帧 ≈ 2000 窗口 ≈ 5 分钟，与需求文档的估算一致）。

**如何解读（重要，不要只看 ECE）：**

1. Laya 的 60% 准确率**恰好等于干净样本占比（60%）**——等价于"全猜干净"的
   多数类基线；缺陷归因 8% 甚至低于 6 选 1 均匀随机（~17%）。
   与社区"零样本 typed-decisions 接近随机"的独立评测一致。
2. Laya 的 ECE（0.067）看起来比规则（0.084）还低，但这是**常数预测器的假象**：
   把概率永远贴在先验（~0.6）附近当然"校准"，却没有判别力。
   校准好 ≠ 判断对——ECE 只在前者（准确率）及格后才有意义。
3. 加载时 laya 自己发出警告：checkpoint 附带的温度值非法（越界钳到 0.5），
   "受影响条目的置信度应视为未校准"。

**按需求文档 5.2 的验收红线，如实结论：零样本状态下 Laya 引擎不成立，
规则引擎胜出。** 因此 `--engine` 默认值从需求文档原定的 `laya` 改为
`heuristic`（这是一处有依据的偏离；Laya 保留为可选引擎，等
`laya.fit_temperatures()` 用标注数据拟合温度后可用 `--labels` 复评翻身）。

> 注意：合成基准按规则阈值反向构造，**天然偏向 heuristic**，只能证伪不能证成。
> 但 Laya 连多数类基线都没超过，这个结论对分布偏移是稳健的。

### 真实 Laya 推理实测记录（工程细节）

- 包：`laya==0.3.22`（PyPI，Apache 2.0，依赖 torch≥2.0 / transformers≥4.48），
  权重从 HuggingFace 拉 `convaiinnovations/laya`（421M，首次下载约 1.6GB）。
- API 与需求文档草稿的写法兼容：`laya.load(model)` → `agent.predict(state, QUESTIONS)`
  → `res["answers"][qid]["noul"/"choice"/"score"]`；另有 `predict_batch` 批量接口
  （本工具已改用，逐条 → 分块批量）。
- `score` 原语返回**期望等级浮点值** + `legend` 映射（如 `2.23 → marginal`），
  报告里数值与标签都落盘（`quality_level` / `quality`）。
- 加载警告（原文）：*"this checkpoint ships invalid temperatures or values outside
  [0.5, 5]; ... Treat confidence from the affected entries as uncalibrated."*
  ——checkpoint 自带温度非法，置信度未校准。
- **一个真实的坑（已修复）**：`python scripts/laya_tub_gate.py --engine laya` 会把
  `scripts/` 放进 `sys.path` 首位，仓库历史脚本 `scripts/profile.py` 遮蔽标准库
  `profile`，transformers 懒加载链因此 import 到仓库脚本（其首行 `from donkeycar...`
  在无 donkeycar 的 venv 里炸），报出 `No module named 'donkeycar'` 这种完全不相干的错。
  修复：`laya_score_all` 导入 laya 前把 `scripts/` 从 `sys.path` 摘除。

## 六、已知限制（必须读）

1. **Laya 是 2026-09 才发布的新模型**，社区验证薄；出厂 checkpoint 过度自信
   （包文档自认），校准概率需先 `laya.fit_temperatures()` 拟合温度才可信。
2. **特征阈值环境相关**：`frame_motion < 0.004` 等阈值针对 20Hz、常规赛道/光照；
   换相机帧率/赛道光照要重新标定（改 `heuristic_score_all` 顶部常数）。
3. **`is_clean` 软降权未接入训练**：donkeycar 训练管线不开放 sample_weight，
   侵入式改 `training.py` 不划算；所以落地推荐 export 模式。
4. 视觉特征只是 64×48 灰度的统计量，**不是**语义理解；`off_track` 归因依赖亮度突变，
   阴影/逆光会误报。
5. `--engine` 默认值为 `heuristic`（**有意偏离需求文档原定的 laya 默认**），
   依据是上面合成基准的实测：零样本 Laya 未超过多数类基线。标注数据拟合温度后
   可用 `--engine laya` 复评。

## 七、关键设计决策（为什么这么做）

- **为什么单坐标系**：tub 删除记录后 `_index` 有空洞，"位置"和"索引"从此不同；
  草稿在这个地方把坏数据漏进导出结果（见评估表 #1）。窗口显式携带 `indices` 列表。
- **为什么视觉特征填 -1 而不是 0**：`frame_motion=0` 是"车真的没动"（撞墙证据），
  `-1` 是"拿不到图"（--no-vision 或图损坏）。规则里 `0 <= frame_motion < 0.004`
  显式排除 -1，避免把无图数据全判成撞墙。
- **为什么 export 用 `load_rgb` 重读原图**：视觉缓存是 64×48 归一化灰度，
  拿它导出等于把用户数据降级；导出必须保真。
- **为什么 manifest 里读 `deleted_indexes`**：tub_v2 的软删除只记在 manifest，
  catalog 行内无标记（源码 `datastore_v2.py:310` 可证）。
