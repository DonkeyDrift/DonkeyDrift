# Tony Deployment Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 提供一条可重复执行的 Tony 标准部署命令，并在 TUI/launcher 启动 Drive 时发现旧 Web 进程、落后 Tony 的源码和车辆模板错配。

**Architecture:** 新增仅依赖标准库的 `donkeycar/deployment.py`，集中读取本地 Git 提交、比较车辆模板并生成中文警告；Web 实例登记增加启动时的 `source_head`，使复用已有 8000 进程时也能识别旧代码。新增 `scripts/deploy_tony.py` 串起 fetch、干净工作树保护、ff-only 更新、前端构建、`donkey update` 备份同步、8000 重启和 HTTP/模板验收。

**Tech Stack:** Python 3.11、标准库、Git、pytest、现有 `donkeycar.webui_instance`、现有 `donkeycar.management` CLI。

## Global Constraints

- 不新增第三方依赖，不在启动检查时访问网络。
- 警告不得暴露 `DRIVE_API_TOKEN` 或完整带令牌 URL。
- 版本不一致时明确警告；保留开发分支/自定义模板的可用性，不擅自覆盖或自动更新。
- 只有标准部署命令可以主动更新、覆盖（经 `donkey update` 自带备份）和重启。
- 部署必须保护脏工作树，只允许 fast-forward，不 reset、不强推、不丢弃用户修改。
- 新功能提交前必须通过 `python3 scripts/linux_validation.py run --staged`，最终按仓库约定提交 PR 并合并到 `Tony`。

---

### Task 1: 部署诊断与 Web 启动提交登记

**Files:**
- Create: `donkeycar/deployment.py`
- Create: `tests/test_deployment.py`
- Modify: `donkeycar/webui_instance.py:66`
- Modify: `donkeycar/management/base.py:1103,1570`
- Test: `tests/test_webui_instance.py`

**Interfaces:**
- Produces: `get_source_head(repo_root=None) -> str | None`，仅本地 `git rev-parse HEAD`，失败返回 `None`。
- Produces: `collect_deployment_warnings(car_path=None, repo_root=None, web_instance=None) -> list[str]`。
- `web_instance` 为现有登记 dict；存在但没有 `source_head` 时提示重启以确认版本。
- `write_instance(..., source_head=None)` 在提供该参数时把其写入登记；缺省保持旧 payload 不变。

- [ ] **Step 1: 写失败测试**

```python
def test_warns_when_running_web_predates_current_source():
    with mock.patch("donkeycar.deployment.get_source_head", return_value="new"), \
         mock.patch("donkeycar.deployment._behind_count", return_value=0):
        warnings = collect_deployment_warnings(
            repo_root="/repo", web_instance={"source_head": "old"})
    assert any("8000" in item and "重启" in item for item in warnings)


def test_warns_when_manage_differs_from_current_template(tmp_path):
    repo = tmp_path / "repo"
    car = tmp_path / "car"
    (repo / "donkeycar/templates").mkdir(parents=True)
    car.mkdir()
    (repo / "donkeycar/templates/complete.py").write_text("new")
    (car / "manage.py").write_text("old")
    with mock.patch("donkeycar.deployment.get_source_head", return_value=None):
        warnings = collect_deployment_warnings(car_path=car, repo_root=repo)
    assert any("manage.py" in item and "donkey update" in item for item in warnings)
```

另测：无 Git 元数据不报警；落后 `origin/Tony` 时显示落后数量；相等且模板一致时返回空列表；`write_instance(source_head="abc")` 可往返读取。

- [ ] **Step 2: 运行测试并确认因接口不存在而失败**

Run: `pytest -q tests/test_deployment.py tests/test_webui_instance.py`
Expected: 新用例 FAIL，原因是 `donkeycar.deployment`/`source_head` 尚不存在。

- [ ] **Step 3: 实现最小诊断与登记改动**

```python
def get_source_head(repo_root=None):
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=3, check=True)
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None
```

`collect_deployment_warnings` 分别检查 `web_instance.source_head`、本地 `HEAD..origin/Tony` 的提交数、`manage.py` 与 `donkeycar/templates/complete.py` 的 bytes；所有 Git 查询设置 3 秒超时且不 fetch。`base.py` 两处成功启动登记均传入 `source_head=get_source_head()`。

- [ ] **Step 4: 回归**

Run: `pytest -q tests/test_deployment.py tests/test_webui_instance.py donkeycar/tests/test_web_command.py`
Expected: 全部通过。

### Task 2: TUI 与 launcher 启动前警告

**Files:**
- Modify: `donkeycar/management/tui.py:1326-1345`
- Modify: `donkeycar/launcher/server.py:219-263,372-379`
- Test: `donkeycar/tests/test_tui_drive.py`
- Test: `tests/test_launcher_drive_launch.py`

**Interfaces:**
- Consumes: `collect_deployment_warnings(car_path=None, repo_root=None, web_instance=None)`。
- TUI 在清理/启动进程前打印所有警告；launcher 将警告合并进现有返回字段 `warning`，同时写安全日志。

- [ ] **Step 1: 写失败测试**

```python
def test_drive_prints_deployment_warnings(monkeypatch, tmp_path):
    (tmp_path / "manage.py").write_text("")
    (tmp_path / "myconfig.py").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tui, "collect_deployment_warnings", lambda **kwargs: ["部署过旧"])
    printed = []
    monkeypatch.setattr(tui.console, "print", lambda value="", **kwargs: printed.append(str(value)))
    monkeypatch.setattr(tui.Prompt, "ask", lambda *args, **kwargs: "")
    monkeypatch.setattr(tui.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    tui.DriveCommand().execute()
    assert any("部署过旧" in value for value in printed)
```

launcher 新用例让 `collect_deployment_warnings` 返回 `["旧后端"]`，断言成功启动结果 `result["warning"]` 包含该文本；既有公共桩默认返回空列表。

- [ ] **Step 2: 确认新测试失败**

Run: `pytest -q donkeycar/tests/test_tui_drive.py tests/test_launcher_drive_launch.py`
Expected: 新用例 FAIL，因为两条启动链尚未调用诊断接口。

- [ ] **Step 3: 接入警告**

TUI 使用 `web_instance=inst`、`car_path=car_path`；无有效项目时车辆参数传 `None`。launcher 在找到项目后计算一次警告，复用/新起 Web 都保留，并用 `"\n".join(...)` 合并到已有 `warning`，不覆盖 Web 就绪警告。

- [ ] **Step 4: 回归**

Run: `pytest -q donkeycar/tests/test_tui_drive.py tests/test_launcher_drive_launch.py`
Expected: 全部通过。

### Task 3: Tony 标准部署命令

**Files:**
- Create: `scripts/deploy_tony.py`
- Create: `tests/test_deploy_tony.py`
- Create: `docs/guide/tony-deployment.md`
- Modify: `CHANGELOG.md`（仅合并所有功能完成后添加一条）

**Interfaces:**
- Produces: `deploy(repo_root, car_path, backend_port=8000, dry_run=False) -> int`。
- CLI：`python3 scripts/deploy_tony.py [--repo PATH] [--car PATH] [--backend-port 8000] [--dry-run]`。
- 默认仓库为脚本所在仓库，默认车辆目录为当前目录；非有效车辆目录在执行前报错。

- [ ] **Step 1: 写失败测试**

```python
def test_dry_run_lists_complete_deployment_without_running(tmp_path, capsys):
    with mock.patch.object(runner.subprocess, "run") as run:
        code = runner.deploy(tmp_path, tmp_path, dry_run=True)
    assert code == 0
    run.assert_not_called()
    output = capsys.readouterr().out
    for text in ("fetch", "ff-only", "npm run build", "donkey update", "重启", "健康检查"):
        assert text in output
```

另测：脏工作树在 fetch/merge 前拒绝；有效工作树按 fetch → merge --ff-only → npm build → management update 排序；任一步非零即停止；8000 未通过 `/api/drive/stats` 健康检查返回非零；更新后 `manage.py` 与模板仍不同则返回非零。

- [ ] **Step 2: 确认测试失败**

Run: `pytest -q tests/test_deploy_tony.py`
Expected: FAIL，原因是 `scripts/deploy_tony.py` 尚不存在。

- [ ] **Step 3: 实现部署链**

使用 `subprocess.run(..., check=True)` 执行：

```text
git -C <repo> status --porcelain
git -C <repo> fetch origin Tony
git -C <repo> merge --ff-only origin/Tony
npm run build                         # cwd=<repo>/web_ui/frontend
<python> -m donkeycar.management update  # cwd=<car>，保留其自动备份
```

重启只处理目标部署：优先终止 `webui.json` 登记的父进程并等待退出；无登记时仅匹配 cwd 为 `<repo>/web_ui/backend` 且命令行含目标端口的 uvicorn。启动使用 `<python> -m donkeycar.management web --path <repo>/web_ui --backend-port <port> --backend-host 0.0.0.0 --route /drive`，继承环境但移除 `PYTHONPATH`，并把 `sys.executable` 所在 bin 加到 PATH 前端。等待 `find_live_instance()` 和 `/api/drive/stats` 均就绪，最后逐字节比较车辆模板。日志文件权限设为 0600，输出不转发令牌。

- [ ] **Step 4: 验证命令**

Run: `pytest -q tests/test_deploy_tony.py`
Expected: 全部通过。

Run on Linux: 使用目标部署工作树执行 `python3 scripts/deploy_tony.py --car /home/dkc/projects/mycar`，随后确认 8000 HEAD 为最新 `origin/Tony`、页面可开、切换按钮可见、真实 `manage.py drive` 返回在线。

### Final integration

- [ ] 合并运行所有相关测试：`pytest -q tests/test_deployment.py tests/test_deploy_tony.py tests/test_webui_instance.py tests/test_launcher_drive_launch.py donkeycar/tests/test_tui_drive.py donkeycar/tests/test_web_command.py`。
- [ ] 更新 `CHANGELOG.md`，说明标准部署命令及三类启动警告。
- [ ] 检查文档与代码行为一致，无过期注释。
- [ ] 运行 Linux staged 验证，提交、创建 PR、合并 Tony，再用合并后的 Tony 做实机部署验收。
