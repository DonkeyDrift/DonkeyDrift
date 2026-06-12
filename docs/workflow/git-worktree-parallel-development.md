# Git Worktree 并行开发工作流

本文档提供一套基于 Git Worktree 的通用并行开发方案，适用于多人或多会话（如多个 Kimi CLI）同时在一个代码库上开发不同功能模块的场景。

核心思路：**分支隔离 + 文件系统隔离 + 模块分工**，从物理层面避免互相干扰。

---

## 适用场景

- 两个（或多个）开发者/AI 会话需要同时修改同一仓库的不同功能
- 需要同时运行多套服务或测试环境（每个工作区可独立启动）
- 希望避免临时切换分支导致的环境污染或构建缓存冲突

---

## 前置准备

### 1. 确保主仓库干净

创建工作区前，主仓库应处于干净状态，避免未提交修改被遗漏：

```bash
git status
```

如有未提交修改，先 `git commit` 或 `git stash`。

### 2. 配置 Worktree 目录忽略

Worktree 目录**必须**被 `.gitignore` 忽略，否则另一个工作区的文件会被 git 误认为待提交内容：

```bash
# 检查是否已忽略
git check-ignore -q .worktrees 2>/dev/null && echo "已忽略" || echo "未忽略"
```

如未忽略，执行：

```bash
echo ".worktrees/" >> .gitignore
git add .gitignore
git commit -m "chore: ignore worktree directories"
```

> **建议**：统一使用 `.worktrees/` 作为项目级 worktree 根目录（隐藏目录，不污染文件列表）。

---

## 创建工作区

### 步骤 1：为每个任务创建独立分支 + Worktree

假设需要并行开发两个功能模块：**模块 A** 和 **模块 B**。

```bash
cd /path/to/your-repo

# 模块 A 的工作区
git worktree add .worktrees/feature-a -b feature/a-module

# 模块 B 的工作区
git worktree add .worktrees/feature-b -b feature/b-module
```

验证创建结果：

```bash
git worktree list
```

输出示例：

```
/path/to/your-repo                       main         [主仓库]
/path/to/your-repo/.worktrees/feature-a  feature/a-module
/path/to/your-repo/.worktrees/feature-b  feature/b-module
```

### 步骤 2：各会话进入对应目录启动

**会话 A** 在以下目录工作：

```bash
cd /path/to/your-repo/.worktrees/feature-a
```

**会话 B** 在以下目录工作：

```bash
cd /path/to/your-repo/.worktrees/feature-b
```

> ⚠️ **关键**：每个会话必须在**自己的工作目录**中启动，所有文件操作仅影响该目录。

---

## 模块分工原则

### 按文件/目录划分责任边界

| 会话 | 负责范围 | 避免触碰 |
|------|----------|----------|
| A | `src/frontend/pages/`、`src/frontend/components/` | B 的后端路由、数据库模型 |
| B | `src/backend/routers/`、`src/backend/models/` | A 的前端组件、样式文件 |

### 启动提示模板

给每个会话明确的上下文约束：

> 你在 `/path/to/your-repo/.worktrees/feature-a` 目录下工作，分支是 `feature/a-module`。请专注于 **[具体模块]** 的开发。不要修改 **[另一模块]** 相关的代码。

---

## 公共文件协商策略

以下类型的文件容易被多个模块同时修改，建议**事先约定分工**，或由一方统一维护：

| 文件类型 | 示例 | 协商策略 |
|----------|------|----------|
| API 接口定义 | `services/api.ts`、`openapi.yaml` | 一方定义，另一方只调用 |
| 路由注册 | `main.py`、`App.tsx` | 按路由前缀划分，或统一由后端会话维护 |
| 类型定义 | `types.ts`、`models/__init__.py` | 新增字段时提前同步 |
| 全局配置 | `config.py`、`vite.config.ts` | 只添加自己的配置项，不改已有配置 |

**如果双方都需要修改同一文件**：

1. 由一方先完成修改并提交
2. 另一方 `git fetch` + `git rebase origin/main` 后再修改
3. 或合并时解决冲突

---

## 日常开发命令

### 查看所有 Worktree

```bash
git worktree list
```

### 在各自工作区提交更改

```bash
# 在 .worktrees/feature-a 或 .worktrees/feature-b 目录内执行
git add .
git commit -m "feat: ..."
```

### 同步主分支最新代码

```bash
# 在各工作区内执行
git fetch origin
git rebase origin/main
```

> 将 `main` 替换为你的主分支名称（如 `master`、`develop`、`v1.6.0-UX`）。

---

## 合并与清理流程

### 步骤 1：回到主仓库合并分支

```bash
cd /path/to/your-repo

# 依次合并（顺序通常不影响结果，除非有依赖关系）
git merge feature/a-module
git merge feature/b-module
```

### 步骤 2：解决冲突（如有）

如果提示冲突：

```bash
# 查看冲突文件
git status

# 编辑冲突文件，解决 <<<<<<< / ======= / >>>>>>> 标记
git add <resolved-file>
git commit
```

### 步骤 3：清理或复用 Worktree（可选）

合并完成后，你可以选择**删除**临时工作区，也可以**保留**以便复用。

#### 何时保留 Worktree

对于环境配置较复杂的项目（例如需要安装大量 Python/Node 依赖、编译原生扩展、下载模型权重、配置硬件驱动等），重新搭建开发环境可能耗时较长。此时建议保留 Worktree，待下一次开发同类型任务时直接复用，避免重复配置。

保留时只需保持工作区目录和对应分支即可，后续可直接 `cd` 进入继续开发。

#### 何时删除 Worktree

如果出现以下情况，再考虑删除：

- 该任务已彻底结束，且后续很长一段时间不会再修改相关模块；
- 工作区占用磁盘空间过大，且环境可以方便地重新搭建；
- 需要清理历史分支，保持 `git worktree list` 简洁。

#### 删除前请确认

删除 Worktree 会同时移除工作区内的未提交修改（即使这些修改尚未被 git 追踪）。**执行删除前，请与相关会话/开发者确认该工作区内没有需要保留的改动或环境配置。**

确认无误后，再执行删除：

```bash
# 删除工作区目录并解除 git 追踪（请谨慎操作）
git worktree remove .worktrees/feature-a
git worktree remove .worktrees/feature-b

# 删除已合并的远程/本地分支（可选）
git branch -d feature/a-module
git branch -d feature/b-module
```

> 如果不确定是否要删除，建议先保留 Worktree，仅删除已合并的分支即可。

---

## 最佳实践

1. **一个任务一个 Worktree**：不要把多个不相关的任务塞进同一个工作区。
2. **分支名语义化**：`feature/ui-dashboard`、`fix/api-timeout`、`refactor/db-models`。
3. **及时提交**：在每个工作区频繁小步提交，降低合并冲突的概率。
4. **不要在工作区内创建嵌套 Worktree**：`git worktree list` 可以帮你检测是否已处于 worktree 中。
5. **CI/测试独立**：每个工作区可以独立运行测试，互不干扰构建缓存。
6. **谨慎删除，优先复用**：对于环境配置复杂的项目，合并完成后不必立即删除 Worktree。保留工作区可让后续同模块迭代直接复用已配置的环境，节省重建成本。删除前务必确认工作区内没有未提交的改动或需要保留的环境配置。

---

## 快速参考表

| 操作 | 命令 |
|------|------|
| 查看所有 worktree | `git worktree list` |
| 创建 worktree + 分支 | `git worktree add <path> -b <branch>` |
| 删除 worktree | `git worktree remove <path>` |
| 检查目录是否被忽略 | `git check-ignore -q <dir>` |
| 进入工作区 A | `cd .worktrees/feature-a` |
| 进入工作区 B | `cd .worktrees/feature-b` |
| 主仓库合并分支 | `git merge <branch>` |
| 工作区同步主分支 | `git rebase origin/main` |

---

## 示例：DonkeyDrifter 项目

以下是在 DonkeyDrifter 仓库中的实际应用：

```bash
# 创建两个工作区
git worktree add .worktrees/ui-enhancements     -b feature/ui-enhancements
git worktree add .worktrees/connector-features  -b feature/connector-features
```

| 会话 | 工作目录 | 负责范围 |
|------|----------|----------|
| UI | `.worktrees/ui-enhancements` | `web_ui/frontend/src/` |
| Connectors | `.worktrees/connector-features` | `web_ui/backend/routers/connector.py`、`donkeycar/parts/drive_api_bridge.py` |

详细操作见：`docs/guide/parallel-development-with-worktrees.md`
