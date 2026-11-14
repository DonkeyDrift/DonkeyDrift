# DonkeyDrift uv venv 安装说明（macOS 开发机）

生成: 2026-10-12　|　状态: **实测通过**（Python 3.11.16 + TF 2.15.1 + tensorflow-metal，131 个包，Metal GPU 可见）

本文是 Mac 开发机上用 uv 搭建 DonkeyDrift / GymDonkeyCar 开发环境的完整 runbook，沉淀了 2026-10-12 一次真实安装中踩过的全部坑。
**给 AI 的执行提示：** 逐步照做、每步以实测输出对照"验证清单"；遇到已存在的 `.venv` 先看第 6 节（可能是目录搬家残留，直接重建会丢环境）；本文所有期望值（命令数、环境数、包数）以输出为准，不符先排查不要硬走下一步。

## 1. 结论速览

| 项 | 值 | 说明 |
|---|---|---|
| Python | **3.11**（实测 3.11.16） | 唯一同时满足全部约束的版本，见第 2 节 |
| venv 位置 | `DonkeyDrift/.venv` | **两个仓库共享一个 venv**（GymDonkeyCar 没有独立 venv） |
| TensorFlow | 2.15.1 + tensorflow-metal 1.2.0 | 来自 `[macos]` extra |
| numpy | **必须锁 1.26.4** | numpy 2.x 会破坏老代码，见坑 #2 |
| GymDonkeyCar | editable 安装自同级目录 | 缺失则 dgym 相关测试被 importorskip 跳过 |
| 装法 | `uv venv` + `uv pip install` | **不要用 `uv sync`**，见坑 #1 |

## 2. 为什么是 Python 3.11

| 约束来源 | 内容 | 对版本的影响 |
|---|---|---|
| `setup.cfg` `python_requires` | `>=3.10.0,<3.13` | 只允许 3.10 / 3.11 / 3.12 |
| `[macos]` extra | `tensorflow==2.15.*` | TF 2.15 只发布到 **3.11** 的 wheel（3.12 支持自 TF 2.16 起）→ **Mac 上限 3.11** |
| `[pc]` extra | `tensorflow>=2.19,<2.20` | TF 2.19 支持 3.9–3.12；上限 `<2.20` 是因为 TF 2.20 的 LiteRT 后端不再内置 Flex(SELECT_TF_OPS) 委托，LSTM / 3D-CNN 转 tflite 后推理必挂（`FlexTensorListReserve` 报错），详见 `MIGRATION-py312.md` §2.2 |
| numpy 锁 1.26.4 | 1.26 系止步于 3.12 | 3.13 无解 |
| README | 官方支持 3.11 | 3.10 仅为车端 AidLux 系统 Python 放宽；3.12 用于车端 NPU 运行时，训练栈"实验性" |

3.11 是所有 extras 的交集且经完整 A/B 验证（`MIGRATION-py312.md` 的对照基线即 3.11.16 + TF 2.15.1）。

## 3. 安装步骤

```bash
cd ~/Dev/DKC/DonkeyDrift    # 你的仓库位置

# 国内网络必设（每次新 shell 都要带；AI 工具的每次命令执行都是新 shell，变量须与命令同行）
export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
# 仅当本机没有 uv 管理的 3.11、需要下载 Python 时才需要（南大镜像；中科大亦可）：
# export UV_PYTHON_INSTALL_MIRROR=https://mirror.nju.edu.cn/github-release/astral-sh/python-build-standalone

# 1) 建 venv（本机已有 uv 管理的 3.11 时不会触发下载）
uv venv --python 3.11 --prompt DonkeyDrift .venv

# 2) 装主程序（editable，带 macos+dev extras）+ GymDonkeyCar（editable，自同级目录）
#    numpy 必须锁；scipy/opencv/gymnasium 是与迁移基线对齐的实测版本
uv pip install --python .venv/bin/python \
  -e ".[macos,dev]" \
  -e "../GymDonkeyCar" \
  "numpy==1.26.4" "scipy==1.17.1" "opencv-python-headless==4.11.0.86" "gymnasium==1.3.0"

# 3) （可选）zsh 自动激活钩子，见第 5 节
```

注意：**只装 `donkeydrifter`，绝不装 `donkeycar`**（后者是上游项目，会覆盖 `donkey` 命令，详见 README 的 Important 警告）。

## 4. 验证清单（照抄执行，逐项对照）

| 检查项 | 命令 | 期望 |
|---|---|---|
| Python | `.venv/bin/python -V` | Python 3.11.x |
| 依赖一致性 | `uv pip check --python .venv/bin/python` | All installed packages are compatible（约 131 包） |
| 源码解析 | `.venv/bin/python -c "import donkeycar, gym_donkeycar; print(donkeycar.__file__); print(gym_donkeycar.__file__)"` | 分别指向两个仓库的当前目录 |
| TF + Metal GPU | `.venv/bin/python -c "import tensorflow as tf; print(tf.__version__); print(tf.config.list_physical_devices())"` | 2.15.1，列表含 `/physical_device:GPU:0` |
| numpy | 同上环境 `import numpy; numpy.__version__` | **1.26.4**（若出现 2.x 立即回装 1.26.4） |
| CLI | `.venv/bin/donkey --help` | 17 个子命令（createcar/train/web/drive…） |
| gym 环境 | `.venv/bin/python -c "import gymnasium, gym_donkeycar; print([i for i in gymnasium.envs.registry if 'donkey' in i])"` | 11 个 donkey 环境 |

## 5. zsh 自动激活钩子（可选）

进两个目录树自动激活共享 venv、离开自动退出。写入 `~/.zshrc`（**路径按实际仓库位置改**；目录再搬家时记得同步改这里，见坑 #5）：

```zsh
# >>> auto-activate venv >>>
autoload -Uz add-zsh-hook
_auto_venv() {
  local venv_dir=""
  case "$PWD" in
    /Users/hwp/Dev/DKC/DonkeyDrift|/Users/hwp/Dev/DKC/DonkeyDrift/*|/Users/hwp/Dev/DKC/GymDonkeyCar|/Users/hwp/Dev/DKC/GymDonkeyCar/*) venv_dir=/Users/hwp/Dev/DKC/DonkeyDrift/.venv ;;
  esac
  if [[ -n "$venv_dir" ]]; then
    [[ "$VIRTUAL_ENV" != "$venv_dir" ]] && source "$venv_dir/bin/activate"
  elif [[ -n "$VIRTUAL_ENV" && "$VIRTUAL_ENV" == /Users/hwp/Dev/DKC/DonkeyDrift/.venv ]]; then
    deactivate
  fi
}
add-zsh-hook chpwd _auto_venv
_auto_venv
# <<< auto-activate venv <<<
```

验证：`zsh -ic 'cd ~/Dev/DKC/GymDonkeyCar && echo $VIRTUAL_ENV && which python && cd ~ && echo ${VIRTUAL_ENV:-未激活}'`，
期望依次为 venv 路径、`.venv/bin/python`、`未激活`。

## 6. 坑清单（按踩中概率排序）

### 坑 #1：`uv sync` 不可用
`uv.lock` 是**空壳**（只有 3 行元数据、0 个锁定的包）——`pyproject.toml` 只有 build-system，项目元数据在 `setup.cfg`，`uv lock/sync` 解析不到依赖。用 `uv venv` + `uv pip install`，别指望 `uv.lock`。（依赖审计/CI 另有 `requirements-lock.txt`——`uv pip compile` 从 `requirements.in` 生成的精确固定 + 哈希锁，重生成 `scripts/regenerate_lock.sh`；它服务于 pip-audit 门禁，不是 venv 装包入口。）

### 坑 #2：numpy 2.x 会被解析器选中并静默破坏老代码
TF 2.15 对 numpy 的上界约束不足以挡住解析器选 2.x。必须在安装命令里显式 `"numpy==1.26.4"`，并在验证清单里复查。同时基线对齐 `scipy==1.17.1 / opencv-python-headless==4.11.0.86 / gymnasium==1.3.0`。

### 坑 #3：目录搬家/改名后 venv 全套静默损坏（最隐蔽）
仓库或 `.venv` 被 mv 到新路径后，`bin/activate` 里的 `VIRTUAL_ENV`、`bin/*` 脚本 shebang、editable 安装记录**全部还是旧绝对路径**。症状：激活"成功"但 `VIRTUAL_ENV` 显示旧路径、`which python` 找不到命令（PATH 里塞的是不存在的旧 bin）、钩子反复重新 source。此时**改钩子没用**，需原地重建：

```bash
cd ~/Dev/DKC/DonkeyDrift
uv pip freeze --python .venv/bin/python > /tmp/dd-venv-frozen.txt   # 冻结留底
# 检查冻结文件里 -e 行的路径，旧了就改成新路径
rm -rf .venv
export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
uv venv --python 3.11 --prompt DonkeyDrift .venv
uv pip install --python .venv/bin/python -r /tmp/dd-venv-frozen.txt
# 冻结恢复不带 extras 元数据，再补一次正式安装（幂等）：
uv pip install --python .venv/bin/python -e ".[macos,dev]" -e "../GymDonkeyCar" "numpy==1.26.4"
# 同步修 ~/.zshrc 钩子里的路径（坑 #5），然后按第 4 节全量复验
```

### 坑 #4：镜像变量在新 shell 里丢失
uv 的两个镜像变量都是环境变量，`export` 只对当前 shell 生效。AI 工具每次命令执行都是新 shell，**变量必须与 uv 命令写在同一行命令里**。症状：解析卡住、下载 GitHub 超时。

### 坑 #5：`~/.zshrc` 钩子路径过期
钩子匹配的是绝对路径前缀，仓库搬家后不报错、只是静默不触发（或触发到旧 venv）。搬家后必须同步更新 `~/.zshrc` 里的 case 分支和 deactivate 条件。

### 坑 #6：macOS 没有裸 `python` 命令
系统只有 `python3`。验证"venv 是否激活"要看 `which python`（venv 内一定有）而不是假设系统有。

### 坑 #7：误装上游 `donkeycar` 包
会覆盖 `donkey` 命令导致 `tui/web/drive/installweb` 消失。恢复：`pip uninstall -y donkeycar && uv pip install -e ".[macos,dev]"`。

## 7. 车端（AidLux 板）不在本文范围

板端 Python 版本（系统 3.10 / uv 装的 3.12）、NPU 环境、`TF_USE_LEGACY_KERAS` 补件等见 `MIGRATION-py312.md`（其 §8 就是板端复现记录）。Mac 上 3.11 + TF 2.15 自带 Keras 2，**不需要** `TF_USE_LEGACY_KERAS`。
