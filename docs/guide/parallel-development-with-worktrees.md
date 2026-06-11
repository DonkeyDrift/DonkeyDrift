# 使用 Git Worktree 进行并行开发

本文档描述如何在 DonkeyDrifter 项目中使用 Git Worktree 让两个 Kimi CLI（或任何两个开发者）同时并行开发不同功能模块，避免文件冲突。

---

## 已创建的 Worktree

当前仓库已配置以下两个独立工作区：

```
/home/dkc/projects/DonkeyDrifter                                v1.6.0-UX          [主仓库]
/home/dkc/projects/DonkeyDrifter/.worktrees/ui-enhancements     feature/ui-enhancements
/home/dkc/projects/DonkeyDrifter/.worktrees/connector-features  feature/connector-features
```

---

## CLI A：UI 专属工作区

### 进入目录

```bash
cd /home/dkc/projects/DonkeyDrifter/.worktrees/ui-enhancements
```

### 负责范围

| 目录/文件 | 说明 |
|-----------|------|
| `web_ui/frontend/src/` | React 前端所有页面、组件、样式 |
| `web_ui/frontend/src/pages/` | Drive、Trainer、Arena 等页面 |
| `web_ui/frontend/src/components/` | 可复用组件 |
| `web_ui/frontend/src/services/api.ts` | 前端 API 客户端（只读或协商后修改） |
| `web_ui/frontend/src/App.tsx` | 路由配置 |
| `web_ui/frontend/src/index.css` | 全局样式 |
| `web_ui/backend/routers/` | FastAPI 路由（如需配合前端改接口） |

### 启动提示

启动 Kimi CLI 时，请明确告知其工作目录和分支：

> 你在 `/home/dkc/projects/DonkeyDrifter/.worktrees/ui-enhancements` 目录下工作，分支是 `feature/ui-enhancements`。请专注于修改 `web_ui` 前端相关的代码。不要修改 connector 相关的后端逻辑。

---

## CLI B：Connectors 专属工作区

### 进入目录

```bash
cd /home/dkc/projects/DonkeyDrifter/.worktrees/connector-features
```

### 负责范围

| 目录/文件 | 说明 |
|-----------|------|
| `web_ui/backend/routers/connector.py` | Connector 路由核心 |
| `donkeycar/parts/drive_api_bridge.py` | 车辆端 WebSocket 桥接 |
| `web_ui/backend/main.py` | FastAPI 应用入口（如需注册新路由） |
| `donkeycar/parts/` | 硬件/算法部件（如新增 connector 类型） |
| `web_ui/backend/tests/test_connector.py` | Connector 测试 |

### 启动提示

启动 Kimi CLI 时，请明确告知其工作目录和分支：

> 你在 `/home/dkc/projects/DonkeyDrifter/.worktrees/connector-features` 目录下工作，分支是 `feature/connector-features`。请专注于 Connectors 后端功能和车辆端桥接代码。不要修改前端 UI 组件。

---

## 公共文件（需协商）

如果双方都需要改动以下文件，建议**由一方先改、另一方 rebase 后合并**，避免冲突：

| 文件 | 涉及方 |
|------|--------|
| `web_ui/backend/main.py` | 双方（注册路由） |
| `web_ui/frontend/src/services/api.ts` | 双方（API 接口定义） |
| `web_ui/backend/routers/__init__.py` | 双方（路由导出） |

---

## 日常开发命令

### 查看所有 Worktree

```bash
cd /home/dkc/projects/DonkeyDrifter
git worktree list
```

### 提交更改（在每个工作区独立执行）

```bash
# 在各自的工作目录内
git add .
git commit -m "feat: ..."
```

### 拉取主分支最新更改

```bash
# 在各自的工作目录内
git fetch origin
git rebase origin/v1.6.0-UX
```

---

## 合并与清理流程

开发完成后，回到主仓库依次合并两个分支：

```bash
cd /home/dkc/projects/DonkeyDrifter

# 先合并 UI 分支
git merge feature/ui-enhancements

# 再合并 Connectors 分支
git merge feature/connector-features
```

合并完成后，删除临时工作区：

```bash
# 删除工作区目录并清理 git 记录
git worktree remove .worktrees/ui-enhancements
git worktree remove .worktrees/connector-features

# 删除已合并的分支（可选）
git branch -d feature/ui-enhancements
git branch -d feature/connector-features
```

---

## 注意事项

- `.worktrees/` 目录已加入 `.gitignore`，不会被意外提交。
- 主仓库在创建工作区前有一个未提交的 `SidePanel.tsx` 修改，已被 `git stash` 保存。如需恢复，在主仓库执行 `git stash pop`。
- 如果合并时出现冲突，打开冲突文件手动解决 `<<<<<<< HEAD`、`=======`、`>>>>>>>` 标记后，`git add` 并提交即可。

---

## 快速参考

| 操作 | 命令 |
|------|------|
| 查看 worktree | `git worktree list` |
| 进入 UI 工作区 | `cd .worktrees/ui-enhancements` |
| 进入 Connectors 工作区 | `cd .worktrees/connector-features` |
| 删除 worktree | `git worktree remove <path>` |
| 创建新 worktree | `git worktree add <path> -b <branch>` |
