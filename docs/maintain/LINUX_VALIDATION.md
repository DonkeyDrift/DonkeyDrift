# TONY007 Linux 功能验证运维说明

本文规定 Mac 与 Linux 验证机 TONY007 的使用边界，以及 `feat` 提交在 commit、push 和 PR 合并前的验证流程。

> 本文只说明操作约定和待执行的管理员步骤，不表示 self-hosted runner、GitHub required check 或分支保护已经配置完成。

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

## 6. GitHub self-hosted runner：管理员配置

**权限要求：需要目标仓库的 ADMIN 权限，WRITE 权限不足。** WRITE 不能代替 ADMIN 完成仓库 Actions runner 注册和分支保护/required check 配置。以下步骤必须由管理员执行；本次文档编写没有执行这些步骤。

### 6.1 在 TONY007 注册仓库级 runner

1. 打开目标 GitHub 仓库，进入 **Settings → Actions → Runners**。
2. 点击 **New self-hosted runner**，选择 **Linux**，并选择与 TONY007 实际硬件一致的架构。
3. 按页面显示的内容，在 TONY007 的专用 runner 目录下载并校验 GitHub Actions runner。注册令牌以 GitHub 页面实时生成的值为准，不要保存到仓库。
4. 执行页面给出的配置命令，并明确设置名称和自定义标签。命令形式如下，URL 和令牌必须替换为当前仓库及页面实际值：

   ```bash
   ./config.sh \
     --url https://github.com/<OWNER>/<REPO> \
     --token <REGISTRATION_TOKEN> \
     --name TONY007 \
     --labels tony007 \
     --unattended
   ```

5. 按 GitHub 页面指引启动 runner。回到 **Settings → Actions → Runners**，确认名为 **TONY007** 的 runner 在线，并具有 **`tony007`** 标签。
6. CI 的 Linux 验证 job 应通过 `self-hosted` 与 `tony007` 标签选中该 runner，避免落到其他机器。PR 的 Checks 页面中，对应 check 名称应为 **`linux-validation`**。

runner 会执行仓库工作流中的代码。应使用专用、最小权限的运行环境，不给它配置与验证无关的凭据，也不要把它视为可安全执行任意贡献者代码的隔离沙箱。

### 6.2 将 `linux-validation` 设为 required check

先让相应 workflow 在目标仓库实际运行，使 `linux-validation` 出现在最近的 Checks 中；随后按仓库当前使用的保护机制配置。

使用经典分支保护时：

1. 进入 **Settings → Branches**。
2. 在 **Branch protection rules** 下点击 **Add branch protection rule**，或编辑现有规则。
3. 在 **Branch name pattern** 填写实际受保护分支（例如主分支名，以仓库现状为准）。
4. 勾选 **Require status checks to pass before merging**。
5. 在状态检查搜索框中选择准确的 **`linux-validation`**，不要只选择名称相近的 workflow 或其他 job。
6. 点击 **Create** 或 **Save changes** 保存。

如果仓库使用 rulesets，则走 **Settings → Rules → Rulesets**，新建或编辑 branch ruleset，在目标分支规则中启用 **Require status checks to pass**，通过 **Add checks** 添加 **`linux-validation`**，将 enforcement 设为 **Active** 后保存。经典分支保护与 rulesets 按现有治理方式选择，不要因重复配置而误判哪条规则实际生效。

保存后，用一个同仓库测试 PR 验证：TONY007 被选中、`linux-validation` 真实运行且通过后才允许合并。仅看到绿色本地凭证或本地 hook 成功，不代表 GitHub 门禁已经生效。

## 7. CI 的可信触发与 PUBLIC 仓库风险

TONY007 的 self-hosted workflow 只响应：

- 本仓库收到的 `push`，其代码只能来自具有推送权限的维护者；
- 可信维护者通过 `workflow_dispatch` 手动启动的验证。

工作流**不使用 `pull_request` 或 `pull_request_target` 触发**。同仓库分支推送后，`linux-validation` 会附着到该分支的 head commit，并显示在对应 PR 的 Checks 中，因此仍可把它设为 PR required check。

不能只在 `pull_request` job 上添加 same-repo `if` 就认为这是安全边界：fork 作者可以在 PR 中修改 workflow 定义本身，包括删除条件或修改 runner 标签。审批设置和只读 token 也不能把持久 self-hosted runner 变成安全沙箱。

**PUBLIC 仓库尤其危险**：不受信代码一旦在 TONY007 上运行，就可能读取 runner 可访问的凭据、篡改工作目录、攻击内网或留下持久后门。fork PR 不应触发此 self-hosted workflow；如需支持外部贡献，应另设隔离、临时且不含敏感凭据的验证方案。

因此，必须保留当前的可信触发边界，并在 runner 上坚持最小权限、专用环境和不存放无关秘密。任何管理员配置变更后，都应实际检查 fork PR 不会触发 TONY007 的验证 job。
