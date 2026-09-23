# DonkeyDrift: Python 3.11 → 3.12 迁移说明

生成: 2026-09-22 20:24:13　|　状态: **已完成并验证**（由板端自动化流水线 `~/.hermes/aidlux/run/do_swap.sh` 执行替换，逐文件 A/B 比对通过后才切换）

## 1. 结论

| 项 | 值 |
|---|---|
| 新环境 `.venv` | **Python 3.12.3 + TensorFlow 2.19.0 + tf_keras 2.19.0**（numpy 1.26.4，pip 26.2.1，共 126 个包） |
| 旧环境 | 完整保留为 `.venv311-backup-20260922-2005`（Python 3.11.16 + TF 2.15.1） |
| 逐文件 A/B 比对 | 88 个测试文件中已比对 **86** 个：**passed 949 / failed 12 / skipped 12** |
| 相对 3.11 的**回归** | **0 个**（12 个失败在 3.11 上逐条同名，属历史遗留） |
| 业务代码改动 | **0 行**（仅 `setup.cfg` 约束与环境补件） |

## 2. 比对明细

### 2.1 两个环境完全相同的历史遗留失败（12 个，逐条同名 → 与升级无关）

```
donkeycar/tests/test_actuator.py::test_PCA9685
donkeycar/tests/test_actuator.py::test_PWMSteering
donkeycar/tests/test_project_metadata.py::test_agent_docs_describe_donkeydrifter_migration_contract
donkeycar/tests/test_scripts.py::test_bad_command_fails
donkeycar/tests/test_scripts.py::test_createcar
donkeycar/tests/test_scripts.py::test_drivesim
donkeycar/tests/test_scripts.py::test_tubplot
donkeycar/tests/test_template_simulator_preview.py::test_bridge_consumes_preview_image_array
donkeycar/tests/test_web_ui_branding.py::test_frontend_html_title_uses_donkeydrifter_brand
tests/test_build_drift_clip.py::MainMultiTubTest::test_backslash_tub_path_default_out_name
tests/test_web_production_mode.py::TestFrontendNeedsBuild::test_newer_config_needs_build
tests/test_web_production_mode.py::TestFrontendNeedsBuild::test_newer_source_needs_build
```

### 2.2 升级过程中发现的**唯一真回归**（已修复）

`donkeycar/tests/test_keras.py::test_keras_vs_tflite_and_tensorrt[KerasLSTM]` 与 `[Keras3D_CNN]`

- **症状**（TF 2.20）：tflite 模型推理报
  `RuntimeError: Select TensorFlow op(s) ... not supported by this interpreter. Make sure you apply/link the Flex delegate before inference. Node number 18 (FlexTensorListReserve) failed to prepare.`
- **根因**：TF 2.20 的 tflite 解释器换成 LiteRT 后端，**不再内置 Flex(SELECT_TF_OPS) 委托**；而本项目 `keras_to_tflite()` 明确设置 `converter.target_spec.supported_ops = [TFLITE_BUILTINS, SELECT_TF_OPS]`，LSTM / 3D-CNN 转换出的图含 `FlexTensorListReserve`、`tf.MaxPool3D` 等非内置算子 → 推理必然失败（**这不只是测试挂，真车以 tflite 跑 LSTM 模型同样会挂**）。
- **处置**：降到 **TF 2.19.0 + tf_keras 2.19.0**（不降 Python、不改代码）。结果：`test_keras.py` = **9 passed**（与 3.11 完全一致）；数值偏差 LSTM **1.1e-08** / 3D-CNN **2.7e-07**，与 3.11 同一量级。
- **约束落地**：`setup.cfg` 中 `tensorflow>=2.19,<2.20`（上限锁死并写明原因）。

### 2.3 未纳入自动比对的 2 个文件（单独说明）

| 文件 | 情况 | 判据价值 |
|---|---|---|
| `tests/test_web_command.py` | 3.12 = 8 passed, 1 warning in 60.56s (0:01:00)；3.11 = 8 passed, 1 warning in 60.85s (0:01:00) | 新环境通过 = 无回归 |
| `donkeycar/tests/test_train.py` | 未跑完：全量里最重的测试（真实训练模型，**单文件 >12 分钟**），本机供电在 10–60 分钟内必掉电，两个环境都跑不完 | 两个环境**同一限制**，对升级是否成功无判据价值；供电改造后可按第 6 节方法单独跑 |

## 3. 替换后实测验证清单

| 检查项 | 结果 |
|---|---|
| `python -V` / `sys.prefix` | Python 3.12.3 / /home/aidlux/projects/DonkeyDrift/.venv |
| 关键包 | TF 2.19.0 / tf_keras 2.19.0 / numpy 1.26.4 |
| pip 可用性 | pip 26.2.1 from /home/aidlux/projects/DonkeyDrift/.venv/lib/ |
| `donkey` CLI | 17 个子命令（createcar/train/ui/tui/web/drive/evaluate/tubplot…） |
| Web 后端（`web_ui/backend/main.py`, uvicorn） | `/` 200、`/docs` 200、`/openapi.json` 200，**openapi paths = 113**（与 3.11 时期一致） |
| 抽样测试 | `2 failed, 15 passed`（2 个即上文历史遗留） |
| 可执行脚本 shebang | `.venv/bin/pytest`、`.venv/bin/pip` 已指向 `/home/aidlux/projects/DonkeyDrift/.venv/bin/python` |
| 残留旧路径字符串 | 仅 `__pycache__/*.pyc` 内（无害）；`bin/`、`pyvenv.cfg`、`*.pth` **无活引用**（已逐项核对） |

## 4. 改动清单

1. `setup.cfg`（**仅此一处源码文件**，含备份）：
   - `python_requires = >=3.11.0,<3.13`
   - 新增 `Programming Language :: Python :: 3.12` 分类器
   - `tensorflow>=2.19,<2.20`（替换原 `>=2.16,<2.22`，附原因注释）
   - 备份：`setup.cfg.bak-py311`（3.11→3.12 支持）、`setup.cfg.bak-tf220pin`（TF 上限收紧前）
2. `.venv/lib/python3.12/site-packages` 内新增一个 `.pth`：让 `tensorflow.python.keras` 内部导入落到 `tf_keras`（项目有两处该导入，TF≥2.16 已从 TF 移除 Keras 2）
3. 系统侧：`apt install python3-tk`（Python 3.12 环境需要 tkinter）
4. **业务代码 0 改动**（`donkeycar/`、`web_ui/`、`tests/` 均未修改）

## 5. 回滚（30 秒）

```bash
cd /home/aidlux/projects/DonkeyDrift
rm -rf .venv && mv .venv311-backup-20260922-2005 .venv
```

## 6. 持久产物 / 复现方式

- 逐文件结果：`/home/aidlux/.hermes/aidlux/run/suite_312b.results`（新环境 86 文件）、`/home/aidlux/.hermes/aidlux/run/suite_311x.results`（旧环境对照）、`/home/aidlux/.hermes/aidlux/run/suite_post312.results`、`/home/aidlux/.hermes/aidlux/run/suite_post311b.results`
- 失败详情：`/home/aidlux/.hermes/aidlux/run/suite_312b.fail.log`；回归判定：`/home/aidlux/.hermes/aidlux/run/f_new.txt`、`/home/aidlux/.hermes/aidlux/run/f_old.txt`、`/home/aidlux/.hermes/aidlux/run/f_regress.txt`
- 替换全过程日志：`/home/aidlux/.hermes/aidlux/run/swap.out`；依赖快照：`/home/aidlux/.hermes/aidlux/run/req312_frozen.txt`（126 行，可直接 `pip install -r` 复现）
- 可断点续跑的逐文件 runner：`/home/aidlux/.hermes/aidlux/run/suite_runner.sh <venv_root> <tag> [filelist]`（每个文件 900s 超时，结果逐行 append + fsync，掉电后自动跳过已完成文件）
- 单独跑 `test_train.py`（供电改造后）：`cd /home/aidlux/projects/DonkeyDrift && .venv/bin/python -m pytest -q --tb=line donkeycar/tests/test_train.py`

## 7. 与本次迁移无关的已知限制（留档）

- 本机（AidLux/QCM6490）在负载下会**无痕掉电**：10–60 分钟一次，特征为重启时 PMIC RTC 计数清零（`rtc-pm8xxx: setting system clock to 1970-01-01T00:00:17`）。已确认与温度无关（所有 thermal trip 在 110–125 °C，全程未触发、cooling 全 0），根因指向输入供电链路（`fusb302` PD 只协商到 5 V）在电流跃变时跌落。
- 取证设施：`flightrec.service`（开机自启，每 2 秒 fsync 落盘），日志在 `/var/log/flightrec/state.log`，报告命令 `sudo flightrec-report [N]`。
- 因此长任务请使用**分片可续跑**方式（见第 6 节 runner），并在掉电后重新上电即可自动续跑。
