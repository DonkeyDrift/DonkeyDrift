# project-context-sync Skill 设计

日期：2026-08-16
状态：已确认设计，待实现

## 1. 目标

设计一个用户范围（跨项目复用）的 Skill，名为 `project-context-sync`。当被调用时，Skill 指示 Agent：

1. 全量扫描当前项目的实际内容与最近变更。
2. 生成或更新仓库根目录下的 `AGENTS.md` 与 `CLAUDE.md`。
3. 主动识别这两份文件中的过时信息和错误内容，并按规则修复。

参考对象是 Kimi Code CLI 的 `/init` 命令：一次性扫描项目并生成 agent 上下文文件；本 Skill 把该能力固化为可重复、可复用的流程，并额外覆盖"变更后同步"与"过时/错误修复"。

## 2. 已确认的决策

| 维度 | 决策 |
|------|------|
| Skill 范围 | 用户范围（`~/.agents/skills/`），跨项目复用 |
| 交付形态 | 纯指令型单文件 `SKILL.md`，无脚本、无依赖（方案 A） |
| 写入方式 | 默认自动修复；关键改动（命令/路径/入口点/依赖）先确认再写 |
| 变更检测 | 每次全量扫描（关键文件 + 最近提交），不维护基线 |

## 3. Skill 元数据

- `name`: `project-context-sync`
- 文件路径: `~/.agents/skills/project-context-sync/SKILL.md`（Windows 本机为 `C:/Users/cross/.agents/skills/project-context-sync/SKILL.md`）
- frontmatter 格式遵循 Kimi Code skill 约定：

```markdown
---
name: project-context-sync
description: "Use when creating or updating AGENTS.md/CLAUDE.md, syncing agent context files with the actual project state, or after significant project changes (new/renamed commands, moved files, changed build/test steps)."
---
```

## 4. 工作流程

Skill 主体按 6 个阶段组织：

### 阶段 1：采集事实（全量扫描）

不依赖历史基线，每次运行都重新读取：

- 项目定位：确认工作目录；列出顶层结构；查找已存在的 `AGENTS.md` / `CLAUDE.md`（含子目录 `AGENTS.md`）、`README*`。
- 命令与入口：
  - `Makefile` targets
  - `setup.cfg` / `pyproject.toml` 的 `console_scripts`、`scripts`、`extras_require`
  - `package.json` 的 `scripts`（Node/前端项目）
  - `.github/workflows/*.yml` 中的构建/测试步骤
  - CLI 子命令（如 `argparse prog=`、命令分发字典）
  - `Dockerfile` / `docker-compose*` 的关键入口
- 目录布局与职责：识别各包目录、`tests/`、`docs/`、`scripts/`、前端/后端子目录等，通过 `__init__.py`、子目录 README 确定职责。
- 依赖：`install_requires`、`extras_require`、`requirements.txt`、前端 `package.json` dependencies、`python_requires` 等版本约束。
- 约定与规范：命名、导入方式、测试命令、语言/风格约定、已有子目录 `AGENTS.md` 的指导。
- 最近变更：`git log --oneline -20`、`git status`、`git diff --stat`（近期提交/与上次 release 的差异）、`CHANGELOG.md` 顶部条目。

### 阶段 2：比对现有文件

- `AGENTS.md` / `CLAUDE.md` 不存在 → 按第 5 节模板生成。
- 已存在 → 逐节比对阶段 1 采集到的事实。

### 阶段 3：检测过时/错误（明确信号）

以下任一信号命中即视为需要修复：

1. 文档中的命令在 `Makefile` / `setup.cfg` / `pyproject.toml` / `package.json` / CLI 分发字典中找不到定义。
2. 文档引用的路径或目录在当前布局中不存在。
3. 文档写的依赖或版本与 manifest 不一致。
4. 文档描述的功能与代码实际行为相反（需读对应模块确认）。
5. `AGENTS.md` 与 `CLAUDE.md` 之间互相矛盾。
6. 文档引用了已删除、已重命名或已废弃的模块、命令、flag。

### 阶段 4：修复规则

- 默认直接编辑修复：纠正命令、路径、依赖、职责描述，补缺失章节，删失效内容。
- 关键改动需确认：凡会改变"如何构建 / 测试 / 运行"的命令、路径、入口点、依赖，先列出"旧值 → 新值"清单，等用户确认后再写。
- 最小 diff：不动与事实无关的措辞、格式、示例。
- 若存在子目录 `AGENTS.md`，一并检查其是否仍准确。
- 两份文件内容重复时，按第 5 节分工消除漂移。

### 阶段 5：模板与分工

- `AGENTS.md`（权威来源）包含：
  - 项目概述
  - 构建 / 测试 / 运行命令
  - 目录布局
  - 关键约定（导入、命名、语言、风格）
  - 依赖与版本约束
  - 已知注意事项
  - 子目录 `AGENTS.md` 指引（若有）
- `CLAUDE.md` 做薄封装：指向 `AGENTS.md` 作为权威来源，并仅增补 Claude 特有内容（若实际需要）；避免两份文件各自维护同一批事实导致漂移。

### 阶段 6：验证清单（写完必做）

- 文档中每个命令都能在项目里找到对应定义。
- 每个路径真实存在（用 `Glob` / `ls` 验证）。
- 依赖 / 版本与 manifest 一致。
- 两份文件之间无矛盾。
- 无占位符、空章节、`TBD`。
- 在安全且快速的前提下，实际跑一次文档中的测试或构建命令，确认可执行。

## 5. 降级策略

非 Python/Node 项目或无法解析 manifest 时：仍扫描目录结构、`git` 记录与 README，只写能确认的事实；无法确认的内容标注"未确认"，不臆造命令或依赖。

## 6. 边界（非目标）

- 不引入脚本或外部依赖。
- 不重构与事实无关的措辞和格式。
- 不自动执行破坏性或耗时的命令（除非验证清单明确要求且安全）。
- 不为单个项目硬编码事实；所有内容都必须从当前项目实际扫描得到。

## 7. Skill 自身的验证方式

在至少一个真实项目（本仓库 DonkeyDrift 即候选）上运行，验证：

1. 能从零生成 `AGENTS.md` / `CLAUDE.md`。
2. 能识别并修复人为植入的过时命令、错误路径、过期依赖。
3. 关键改动确实停下等待确认，而不是直接改写。
4. 完成后验证清单全部通过。

## 8. 下一步

批准本设计后，转入 `writing-plans` 制定实现计划；实现时遵循 `writing-skills` 的要求（确定 Skill 格式与验证方式）。
