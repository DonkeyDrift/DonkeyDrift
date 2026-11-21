# Tony 标准部署命令（deploy_tony）

`scripts/deploy_tony.py` 是把目标部署工作树更新到 `origin/Tony` 并完成前端构建、
车辆模板同步、Web 重启与验收的唯一标准入口。日常开发（Mac）与实机部署（TONY007）
都走同一条命令，保证"更新源码 → 构建 → 同步模板 → 重启 → 验收"顺序一致、可重复。

其他启动链路（`donkey web` / `donkey drive` / launcher / TUI）不更新仓库或车辆模板；
8000 的版本升级统一走本命令，由它完成 fast-forward、车辆模板备份同步和 Web 重启。

---

## 用法

```bash
python3 scripts/deploy_tony.py [--repo PATH] [--car PATH] [--backend-port 8000] [--dry-run]
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--repo` | 脚本所在仓库根 | 要更新到 `origin/Tony` 的部署工作树 |
| `--car` | 当前目录 | 车辆目录（须含 `manage.py`） |
| `--backend-port` | 8000 | Web 后端端口 |
| `--dry-run` | 关 | 只打印部署计划，不执行任何命令 |

用部署工作树当前实际使用的 Python 运行（TONY007 为
`/home/dkc/miniconda3/envs/donkey/bin/python3.11`），这样 `donkey update` 与重启后的
Web 都与刚合并的源码同源；即使通过 SSH 非交互执行，也会正确使用该环境的 `npm`。

## 典型流程（TONY007 实机）

```bash
ssh dkc@192.168.3.103
cd /home/dkc/projects/DonkeyDrift/.worktrees/deploy-simcollect
/home/dkc/miniconda3/envs/donkey/bin/python3.11 scripts/deploy_tony.py --car /home/dkc/projects/mycar
```

部署完成后验收：8000 端口 `HEAD` 为最新 `origin/Tony`、页面可打开、
切换按钮可见、真实 `manage.py drive` 返回在线。

## 部署链（顺序固定，任一步非零立即中止）

1. **预检**（执行任何命令前）：车辆目录须含 `manage.py`；仓库须含 `.git` 与
   `web_ui/frontend/package.json`；缺失即拒绝，exit 非零。
2. **干净工作树保护**：`git status --porcelain` 非空即拒绝，发生在
   fetch/merge 之前。命令只允许 fast-forward，不 reset、不强推、不丢弃修改；
   先提交或 `git stash` 再部署。
3. `git -C <repo> fetch origin Tony`
4. `git -C <repo> merge --ff-only origin/Tony`
5. `npm run build`（cwd=`<repo>/web_ui/frontend`，构建前端生产包）
6. `<python> -m donkeycar.management update`（cwd=`<car>`；原 `manage.py`/
   `config.py` 由 `donkey update` 自动备份，不丢弃用户数据）
7. **重启 Web（只处理目标部署）**：
   - 优先终止 `~/.donkeycar/webui.json` 登记的旧实例（pid 即 `donkey web`
     父进程），SIGTERM 等待退出、超时升级 SIGKILL，并清除旧登记；
   - 无登记时兜底扫描：仅匹配 cwd=`<repo>/web_ui/backend` 且命令行含目标
     端口的 uvicorn 进程（非 Linux 无 `/proc` 时扫描为空）；
   - 以 `<python> -m donkeycar.management web --path <repo>/web_ui
     --backend-port <port> --backend-host 0.0.0.0 --route /drive` 启动，
     独立进程组（deploy 退出后继续存活）。
8. **健康检查**：等待实例登记 `find_live_instance()` 与
   `GET /api/drive/stats` 均就绪（默认 90 秒截止）；超时 exit 非零。
9. **模板校验**：逐字节比较 `<car>/manage.py` 与
   `<repo>/donkeycar/templates/complete.py`；不一致 exit 非零。

## 安全与隐私

- **日志**：Web 子进程 stdout/stderr 写入 `~/.donkeycar/web-deploy.log`，
  权限 `0600`——后端启动时会打印带令牌的局域网入口，收紧权限避免外泄。
- **令牌不回显**：部署自身的输出与错误信息不转发令牌；`token=<值>` 与
  `DRIVE_API_TOKEN` 环境变量值一律打码为 `***`。
- **环境隔离**：Web 子进程继承环境但移除 `PYTHONPATH`，并把部署解释器所在
  `bin` 目录加到 `PATH` 前端。
- **不越界**：不触碰用户在车辆目录的数据/模型；模板同步只经 `donkey update`
  的备份机制。

## dry-run

```bash
python3 scripts/deploy_tony.py --dry-run --car /home/dkc/projects/mycar
```

只打印完整部署计划（含全部命令与路径），不执行任何命令、不重启任何进程。
dry-run 不做拦截性预检：目录不满足条件时会在计划前列出"正式执行将因以下
问题拒绝"的提示，但 exit 仍为 0。

## 故障排查

| 现象 | 处理 |
|------|------|
| `工作树不干净，拒绝 fetch/merge` | `git status` 查看修改，提交或 `git stash` 后重跑 |
| `git fetch` 失败 | 检查网络与 `origin`remote；`git remote -v` |
| `npm run build` 失败 | 确认 `web_ui/frontend/node_modules` 存在（`npm install`）；npm 在 PATH 中 |
| 健康检查超时 | 查 `~/.donkeycar/web-deploy.log`（0600）；确认端口未被占用 |
| `模板校验失败` | `donkey update` 未成功同步模板；对比备份文件后重跑部署 |
