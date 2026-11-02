# TONY007 Linux 功能验证运维说明

本文规定 Mac 与 Linux 验证机 TONY007 的使用边界，以及 `feat` 提交在 commit、push 和 PR 合并前的验证流程。

> 本文说明操作约定与当前 GitHub-hosted PR 检查的工作方式；GitHub required check 与分支保护尚未配置，本文也不包含需要仓库 Admin 权限的配置步骤。

## 1. Mac 与 Linux 的边界

- **Mac 是正本和日常开发机**：日常代码修改、调试、普通单元测试及常规验证均在 Mac 完成。
- **Linux 只承担规定的验证任务**：主机为 TONY007，默认 SSH 地址为 `dkc@192.168.3.62`。不要把 Linux 当作日常开发机，不要在 Linux 上独立演进代码。
- **新功能必须在 Linux 验证**：Conventional Commit 首行采用 `feat: ...`、`feat(scope): ...` 及对应 `feat!:`、`feat(scope)!:` 形式的提交，在 **commit 前和 PR 前**都必须通过 TONY007 验证。
- 是否触发该要求看提交消息的 Conventional Commit 类型，不看分支名、PR 标题或修改了哪些文件。`fix:`、`docs:`、`refactor:` 等不因此免除其各自应有的测试，但只有上述 `feat` 形式触发本文的强制 Linux 门禁。
- Linux 不在线时，不要伪造通过记录，也不要用 Mac 测试替代强制验证；保留待验证状态，待 TONY007 恢复后补验。

验证覆盖根目录 pytest 和 `web_ui/backend/tests`。日常小范围测试仍在 Mac 进行，不要为了每次普通调试都触发 Linux 全量测试。

## 2. 在 Mac 安装本仓库 hooks

在仓库根目录执行一次：

```bash
git config core.hooksPath .githooks
```

该命令写入当前仓库的本地 Git 配置，不修改全局 Git 配置。安装后，`.githooks` 会立即影响**本仓库后续执行的 Git 命令**，不需要重启终端或等待下一次对话。

正在进行的 AI/agent 对话不会因为规则文件或 hooks 改变就自动更新已有上下文：需要在对话中重申文字规则，或重启/新开会话后重新加载规则。hooks 的即时生效与对话规则需要重申/重启是两件不同的事。

## 3. 验证命令与准确代码树

统一使用 `python3 scripts/linux_validation.py`。它有两种操作：

- `run`：让 TONY007 对指定代码树实际执行验证，成功后写入本地通过凭证。
- `check`：只核验指定代码树是否已有对应的通过凭证，**不会重新运行测试**。

### 3.1 commit 前验证暂存区

```bash
python3 scripts/linux_validation.py run --staged
python3 scripts/linux_validation.py check --staged
```

`--staged` 指 Git index 中准确的内容树，不是“当前工作目录看起来差不多”的内容。未暂存修改、未跟踪文件以及暂存后又发生的暂存区变化，都不能混用同一份通过结论。

推荐顺序：

1. 在 Mac 完成开发和普通测试。
2. 只暂存本次准备提交的内容。
3. 执行 `run --staged`，等待根目录 pytest 和 `web_ui/backend/tests` 在 TONY007 通过。
4. 保持暂存区不变，创建 `feat: ...` 或 `feat(scope): ...` 提交。
5. 如果暂存区发生变化，重新执行 `run --staged`。

### 3.2 验证已有提交

```bash
python3 scripts/linux_validation.py run --commit COMMIT
python3 scripts/linux_validation.py check --commit COMMIT
```

将 `COMMIT` 替换为实际提交 SHA 或可解析到该提交的引用。该形式验证的是此提交的准确 Git tree，适用于 PR 前补验已有 `feat` 提交。

本地凭证保存于：

```text
.git/linux-validation/<tree>.json
```

其中 `<tree>` 是被验证代码树的 Git tree 标识。凭证绑定的是**准确 tree**，不是分支名、工作目录、PR 编号或“最新 HEAD”这一易变概念：

- tree 改变后，旧凭证不能证明新 tree 已通过，必须重新 `run`。
- 只改提交说明、提交者或父提交会产生新 commit，但如果 tree 完全没变，凭证仍对应同一个 tree。
- rebase、amend、cherry-pick 或继续修改后，应按实际 tree 重新核验，不能仅凭旧 commit 曾经通过来判断。
- `.git/linux-validation/` 是本机 Git 元数据，不是可分发的测试结果；不要把它当作跨机器、跨工作树或 CI 的永久通行证。

本地 hooks 和凭证也不替代 CI：它们可能被绕过或本地环境可能配置不一致，最终合并门禁仍应依赖 GitHub 上独立运行的 `linux-validation` check。

## 4. commit-msg 与 pre-push 的工作方式

### `commit-msg`

`commit-msg` 在提交创建过程中读取提交消息：

- 对 `feat: ...` 或 `feat(scope): ...`，核验当前待提交暂存树是否已经存在 `run --staged` 产生的通过凭证。
- 没有凭证、凭证不对应准确 tree 或核验失败时，拒绝该提交。
- 它负责执行门禁，不应把 `check` 当成实际测试；测试必须在之前的 `run --staged` 中已经成功完成。

因此，不能先提交再补跑来替代 commit 前验证。

### `pre-push`

`pre-push` 在推送前检查本次待推送提交范围内的 `feat` 提交，并按各提交的准确 tree 核验对应的通过凭证。只要更新中包含 `feat`，最终推送 tip 也必须有通过凭证，即使 tip 是后续的 `fix:` 或 `docs:`；这样验证覆盖的是即将用于 PR 的最终代码树。已有提交如需补验，应先执行：

```bash
python3 scripts/linux_validation.py run --commit COMMIT
```

然后再推送。`pre-push` 的凭证核验防止“本机 commit-msg 未安装或被跳过”成为唯一防线，但它仍是本地门禁，不能替代 GitHub required check。

## 5. SSH 与远端 Python

默认值：

| 项目 | 默认值 | 覆盖方式 |
|---|---|---|
| Linux SSH | `dkc@192.168.3.62` | `DONKEYDRIFT_LINUX_SSH` |
| 远端 Python | `/home/dkc/miniconda3/envs/donkey/bin/python` | `DONKEYDRIFT_LINUX_PYTHON` |

例如只在本次命令中覆盖：

```bash
DONKEYDRIFT_LINUX_SSH=dkc@192.168.3.62 \
DONKEYDRIFT_LINUX_PYTHON=/home/dkc/miniconda3/envs/donkey/bin/python \
python3 scripts/linux_validation.py run --staged
```

运行前由维护者确保 SSH 认证可用、TONY007 在线，并且指定 Python 环境已具备项目测试依赖。验证命令会把该 Python 的 `bin` 目录加入 `PATH`，让 `donkey` 等子命令可执行；同时把 `PYTHONPATH` 指向本次归档目录，避免子命令加载 Linux 工作树中的其他代码，并使用归档内的隔离 `HOME`，防止个人项目配置污染测试结果。不要把密码、私钥或令牌写入仓库、hooks、workflow 或本文。

## 6. GitHub-hosted PR 检查：无需 Admin 的 `linux-validation`

`.github/workflows/linux-validation.yml` 在 GitHub 托管的 `ubuntu-latest` 一次性虚拟机上运行。仓库维护者不需要任何 Admin 操作，PR 一旦打开或更新，该检查就会自动出现在 PR 的 Checks 页面：

- **触发**：`pull_request` 与 `workflow_dispatch`，不再使用 `push` 触发，也没有任何 self-hosted runner。
- **最小权限**：workflow 顶层声明 `permissions: contents: read`；checkout 步骤设置 `persist-credentials: false`，不在 runner 上遗留任何 Git 凭据。
- **准确代码树**：checkout 的 `ref` 为 `${{ github.event.pull_request.head.sha || github.sha }}`——PR 事件检出 PR 分支的准确 head SHA，测试结论绑定该提交；手动触发时回退到触发提交本身。
- **环境与依赖**：Python 3.11；安装 `.[dev]` 与 `web_ui/backend/requirements.txt` 后再安装 gym-donkeycar 1.3.1。PyPI 上的 gym-donkeycar 只发布到 1.0.13，1.3.1 只存在于 upstream git 仓库（其 `gym_donkeycar/version.txt` 为 1.3.1），因此锁定 commit `a1f4ca6` 从 git 安装，与 TONY007 本地 editable 安装同源。
- **gym 韧性补丁**：安装后先用 `python -c 'import gym_donkeycar, pathlib; print(pathlib.Path(gym_donkeycar.__file__).resolve().parent.parent)'` 定位 site-packages（已安装包 `__init__.py` 所在目录的上一级），再用 `patch -p1 -d <site-packages>` 应用 `scripts/patches/gym-donkeycar-linux-resilience.patch`。补丁内路径形如 `a/gym_donkeycar/core/client.py`，`-p1` 去掉第一段 `a/` 后正好落在 `<site-packages>/gym_donkeycar/...` 上。该补丁让模拟器断连时 `observe()`/`wait_until_loaded()` 快速失败，并支持 `observe_timeout` 对“TCP 存活但遥测静默”的连接有界退出，是 dgym 重连测试依赖的行为。
- **测试范围**：与 TONY007 全量验证同一命令面——根目录 `python -m pytest -q` 与 `web_ui/backend` 下的 `python -m pytest tests -q`。

`pull_request` 触发本身是安全默认：GitHub 使用 PR 基准分支上的 workflow 定义运行检查，fork PR 只拿到只读 token、不接触仓库秘密，且 GitHub-hosted runner 是每次销毁的一次性虚拟机。因此这里不需要旧方案中围绕 self-hosted runner 的触发边界管理，也不需要注册任何 runner。

## 7. 边界：PR 检查不等于 TONY007 本地强制验证

- **验证对象不同**：本地强制验证（`scripts/linux_validation.py` + `.githooks`）绑定**准确 Git tree** 的通过凭证，由 commit-msg/pre-push 在提交、推送发生前拦截；GitHub PR 检查绑定 **PR head SHA**，在 PR 更新后于云端独立复跑。本地凭证不能证明 PR 检查已通过，PR 检查通过也不能替代本地门禁对暂存树/提交树的强制核验。
- **当前未配置 required check**：把 `linux-validation` 设为合并前必需状态检查属于分支保护或 rulesets 配置，需要仓库 Admin 权限，本文不包含该步骤。配置完成之前，该检查失败**不会自动阻止合并**，只能作为 PR Checks 页面的人工核对信号。若未来要强制化，由管理员将 `linux-validation` 设为 required check，并用一个故意失败的测试 PR 验证合并确实被阻止。
- **触发行为变化**：原 `push` 触发已移除，同仓库分支推送不再自动产生 check 结果；需要打开 PR 或手动 `workflow_dispatch` 才会运行。手动触发只验证触发时指定的提交。
