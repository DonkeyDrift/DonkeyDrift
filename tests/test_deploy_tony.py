# -*- coding: utf-8 -*-
"""scripts/deploy_tony.py（Tony 标准部署命令，tony-deployment guardrails Task 3）单元测试。

测试覆盖：
- dry-run：完整列出部署计划（fetch / ff-only / npm run build / donkey update /
  重启 / 健康检查 / 模板校验），绝不执行任何 subprocess 命令
- 预检：非有效车辆目录（缺 manage.py）或仓库布局缺失（缺
  web_ui/frontend/package.json、.git）时在执行任何命令前报错拒绝
- 干净工作树保护：git status --porcelain 非空时在 fetch/merge 之前拒绝
- 命令顺序：fetch → merge --ff-only → npm run build → management update，
  且 npm/update 的 cwd 分别指向前端目录与车辆目录
- 失败即停：链上任一步非零立即中止，后续步骤与 Web 重启不再执行
- 健康检查：/api/drive/stats 未就绪返回非零
- 模板校验：更新后 manage.py 与 donkeycar/templates/complete.py 仍不一致返回非零
- 重启语义：优先终止 webui.json 登记的旧实例并等待退出；无登记时仅匹配
  cwd=<repo>/web_ui/backend 且命令行含目标端口的 uvicorn
- 启动细节：`<python> -m donkeycar.management web --path … --backend-port …
  --backend-host 0.0.0.0 --route /drive`，环境将 PYTHONPATH 重置为目标仓库、把
  sys.executable 所在 bin 加到 PATH 前端，日志文件权限 0600
- 令牌脱敏：任何回显文本中的 token 值一律打码

全部 mock，不执行真实部署、不触碰真实 `~/.donkeycar/webui.json`、
不重启真实服务。
"""

import os
import signal
import stat
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import pytest

from scripts import deploy_tony as runner


# ===========================================================================
# 夹具与桩工具
# ===========================================================================

@pytest.fixture
def repo_and_car(tmp_path):
    """构造一个最小但布局完整的仓库与车辆目录（模板与 manage.py 一致）。"""
    repo = tmp_path / "repo"
    car = tmp_path / "car"
    (repo / ".git").mkdir(parents=True)
    (repo / "web_ui" / "frontend").mkdir(parents=True)
    (repo / "web_ui" / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    (repo / "donkeycar" / "templates").mkdir(parents=True)
    (repo / "donkeycar" / "templates" / "complete.py").write_text("TEMPLATE\n", encoding="utf-8")
    car.mkdir()
    (car / "manage.py").write_text("TEMPLATE\n", encoding="utf-8")
    return repo, car


def _fake_run(calls, status_stdout="", fail_when=None):
    """subprocess.run 桩：记录每次调用，status 步骤可注入 stdout，其余成功。

    fail_when(joined_cmd) 返回 True 时以非零码抛 CalledProcessError，
    模拟生产代码 `subprocess.run(..., check=True)` 的真实语义。
    """

    def fake_run(cmd, **kwargs):
        cmd = [str(part) for part in cmd]
        joined = " ".join(cmd)
        calls.append((cmd, kwargs))
        stdout = status_stdout if ("--porcelain" in cmd and "status" in cmd) else ""
        if fail_when and fail_when(joined):
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    return fake_run


def _live_instance(port=8000):
    return {"pid": 11111, "backend_port": port, "frontend_port": port,
            "started_at": 1.0}


def _patch_web_ready(port=8000, stats_ok=True):
    """把 Web 重启与健康检查阶段全部指到 mock：登记无旧实例、实例即时就绪。"""
    patches = [
        mock.patch.object(runner.subprocess, "Popen"),
        mock.patch.object(runner.wui, "read_instance", return_value=None),
        mock.patch.object(runner.wui, "find_live_instance",
                          return_value=_live_instance(port)),
        mock.patch.object(runner, "_probe_stats", return_value=stats_ok),
        mock.patch.object(runner, "WAIT_READY_TIMEOUT_S", 0.3),
        mock.patch.object(runner, "POLL_INTERVAL_S", 0.05),
    ]
    return patches


def _start_all(patches):
    stack = ExitStack()
    for patch in patches:
        stack.enter_context(patch)
    return stack


# ===========================================================================
# dry-run：只列计划，不执行
# ===========================================================================

def test_dry_run_lists_complete_deployment_without_running(tmp_path, capsys):
    with mock.patch.object(runner.subprocess, "run") as run:
        code = runner.deploy(tmp_path, tmp_path, dry_run=True)
    assert code == 0
    run.assert_not_called()
    output = capsys.readouterr().out
    for text in ("fetch", "ff-only", "npm run build", "donkey update", "重启", "健康检查"):
        assert text in output


def test_dry_run_never_spawns_web_process(tmp_path):
    with mock.patch.object(runner.subprocess, "Popen") as popen, \
         mock.patch.object(runner.subprocess, "run") as run:
        code = runner.deploy(tmp_path, tmp_path, backend_port=8123, dry_run=True)
    assert code == 0
    run.assert_not_called()
    popen.assert_not_called()


def test_dry_run_reports_preflight_problems_as_notes(tmp_path, capsys):
    """dry-run 不做拦截性预检（brief 用例对裸 tmp_path 返回 0），
    但要如实提示正式执行会因哪些问题被拒绝。"""
    code = runner.deploy(tmp_path, tmp_path, dry_run=True)
    assert code == 0
    assert "manage.py" in capsys.readouterr().out


# ===========================================================================
# 预检：执行前拒绝无效目录
# ===========================================================================

def test_invalid_car_dir_rejected_before_any_command(tmp_path, capsys):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "web_ui" / "frontend").mkdir(parents=True)
    (repo / "web_ui" / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    car = tmp_path / "not-a-car"  # 缺 manage.py
    car.mkdir()
    with mock.patch.object(runner.subprocess, "run") as run:
        code = runner.deploy(repo, car)
    assert code != 0
    run.assert_not_called()
    assert "manage.py" in capsys.readouterr().err


def test_repo_layout_missing_rejected_before_any_command(repo_and_car, capsys):
    repo, car = repo_and_car
    (repo / "web_ui" / "frontend" / "package.json").unlink()
    with mock.patch.object(runner.subprocess, "run") as run:
        code = runner.deploy(repo, car)
    assert code != 0
    run.assert_not_called()
    assert "npm run build" in capsys.readouterr().err


# ===========================================================================
# 干净工作树保护
# ===========================================================================

def test_dirty_worktree_refused_before_fetch(repo_and_car, capsys):
    repo, car = repo_and_car
    calls = []
    with mock.patch.object(runner.subprocess, "run",
                           side_effect=_fake_run(calls, status_stdout=" M dirty.py\n")), \
         _start_all(_patch_web_ready()):
        code = runner.deploy(repo, car)
    assert code != 0
    joined = [" ".join(cmd) for cmd, _ in calls]
    assert any("status" in cmd and "--porcelain" in cmd for cmd in joined)
    assert not any("fetch" in cmd for cmd in joined)
    assert not any("merge" in cmd for cmd in joined)
    err = capsys.readouterr().err
    assert "脏" in err or "干净" in err


def test_clean_worktree_runs_fetch_then_ff_only_merge(repo_and_car):
    repo, car = repo_and_car
    calls = []
    with mock.patch.object(runner.subprocess, "run",
                           side_effect=_fake_run(calls)), \
         _start_all(_patch_web_ready()):
        code = runner.deploy(repo, car)
    assert code == 0
    fetches = [" ".join(cmd) for cmd, _ in calls if "fetch" in cmd]
    merges = [" ".join(cmd) for cmd, _ in calls if "merge" in cmd]
    assert any("origin" in cmd and "Tony" in cmd for cmd in fetches)
    assert any("--ff-only" in cmd and "origin/Tony" in cmd for cmd in merges)
    fetch_idx = next(i for i, (cmd, _) in enumerate(calls) if "fetch" in cmd)
    merge_idx = next(i for i, (cmd, _) in enumerate(calls) if "merge" in cmd)
    assert fetch_idx < merge_idx


# ===========================================================================
# 链式步骤：顺序、cwd、失败即停
# ===========================================================================

def test_deployment_chain_order_and_cwd(repo_and_car):
    repo, car = repo_and_car
    calls = []
    with mock.patch.object(runner.subprocess, "run",
                           side_effect=_fake_run(calls)), \
         _start_all(_patch_web_ready()):
        code = runner.deploy(repo, car)
    assert code == 0
    steps = [" ".join(cmd) for cmd, _ in calls]
    fetch_idx = next(i for i, s in enumerate(steps) if "fetch" in s)
    merge_idx = next(i for i, s in enumerate(steps) if "merge" in s)
    npm_idx = next(i for i, s in enumerate(steps) if "npm" in s)
    update_idx = next(i for i, s in enumerate(steps) if "management" in s and "update" in s)
    assert fetch_idx < merge_idx < npm_idx < update_idx
    # npm run build 在前端目录执行；donkey update 在车辆目录执行
    npm_kwargs = calls[npm_idx][1]
    update_kwargs = calls[update_idx][1]
    assert Path(npm_kwargs["cwd"]) == repo / "web_ui" / "frontend"
    assert Path(update_kwargs["cwd"]) == car
    # update 通过 `-m donkeycar.management update` 调用（保留其自动备份）
    assert "donkeycar.management" in steps[update_idx] and " update" in steps[update_idx]


@pytest.mark.parametrize("fail_step", ["fetch", "merge", "npm run build", "management update"])
def test_any_step_failure_stops_the_chain(repo_and_car, fail_step):
    repo, car = repo_and_car
    calls = []

    def fail_when(joined):
        return fail_step in joined

    patches = _patch_web_ready()
    patches.insert(0, mock.patch.object(runner.subprocess, "run",
                                        side_effect=_fake_run(calls, fail_when=fail_when)))
    with _start_all(patches):
        code = runner.deploy(repo, car)
    assert code != 0
    steps = [" ".join(cmd) for cmd, _ in calls]
    # 失败步骤之后的链式命令一律不再执行
    order = ["fetch", "merge", "npm", "management update"]
    keys = {"fetch": "fetch", "merge": "merge", "npm run build": "npm",
            "management update": "management update"}
    failed_idx = order.index(keys[fail_step])
    for later in order[failed_idx + 1:]:
        assert not any(later in step for step in steps), (fail_step, later)


def test_chain_failure_prevents_web_restart(repo_and_car):
    repo, car = repo_and_car
    calls = []
    with mock.patch.object(runner.subprocess, "run",
                           side_effect=_fake_run(calls, fail_when=lambda s: "merge" in s)), \
         mock.patch.object(runner.subprocess, "Popen") as popen:
        code = runner.deploy(repo, car)
    assert code != 0
    popen.assert_not_called()


# ===========================================================================
# 健康检查与模板校验
# ===========================================================================

def test_stats_health_check_failure_returns_nonzero(repo_and_car, capsys):
    repo, car = repo_and_car
    patches = _patch_web_ready(stats_ok=False)
    patches.insert(0, mock.patch.object(runner.subprocess, "run",
                                        side_effect=_fake_run([])))
    with _start_all(patches):
        code = runner.deploy(repo, car, backend_port=8000)
    assert code != 0
    assert "健康检查" in capsys.readouterr().err


def test_template_mismatch_after_update_returns_nonzero(tmp_path, repo_and_car, capsys):
    repo, car = repo_and_car
    (car / "manage.py").write_text("OUTDATED\n", encoding="utf-8")  # update 未同步
    patches = _patch_web_ready()
    patches.insert(0, mock.patch.object(runner.subprocess, "run",
                                        side_effect=_fake_run([])))
    with _start_all(patches):
        code = runner.deploy(repo, car)
    assert code != 0
    err = capsys.readouterr().err
    assert "manage.py" in err and "donkey update" in err


def test_template_match_returns_zero(repo_and_car):
    repo, car = repo_and_car
    patches = _patch_web_ready()
    patches.insert(0, mock.patch.object(runner.subprocess, "run",
                                        side_effect=_fake_run([])))
    with _start_all(patches):
        code = runner.deploy(repo, car, backend_port=8000)
    assert code == 0


# ===========================================================================
# Web 重启语义
# ===========================================================================

def test_registered_pid_is_terminated_and_registration_cleared(repo_and_car, tmp_path):
    repo, car = repo_and_car
    instance_file = tmp_path / "webui.json"
    runner.wui.write_instance(8000, 8000, pid=4242, instance_file=instance_file)
    killed = []

    def fake_kill(pid, sig):
        killed.append((pid, sig))

    def fake_alive(pid):
        return (pid, signal.SIGTERM) not in killed

    patches = [
        mock.patch.object(runner.subprocess, "run", side_effect=_fake_run([])),
        mock.patch.object(runner.subprocess, "Popen"),
        mock.patch.object(runner.wui, "WEBUI_INSTANCE_FILE", instance_file),
        mock.patch.object(runner.wui, "find_live_instance",
                          return_value=_live_instance(8000)),
        mock.patch.object(runner, "_probe_stats", return_value=True),
        mock.patch.object(runner, "WAIT_READY_TIMEOUT_S", 0.3),
        mock.patch.object(runner, "POLL_INTERVAL_S", 0.05),
        mock.patch.object(runner.wui, "_pid_alive", side_effect=fake_alive),
    ]
    stray_finder = mock.MagicMock(return_value=[])
    patches.append(mock.patch.object(runner, "_find_stray_uvicorn_pids", stray_finder))
    with _start_all(patches), mock.patch.object(runner.os, "kill", side_effect=fake_kill):
        code = runner.deploy(repo, car)
        # 登记命中后不再走兜底扫描（只处理目标部署）
        assert stray_finder.call_count == 0
    assert code == 0
    assert (4242, signal.SIGTERM) in killed
    assert not instance_file.exists()  # 旧登记已清除


def test_stray_uvicorn_matched_only_by_backend_cwd_and_port(repo_and_car, tmp_path):
    repo, car = repo_and_car
    backend_dir = repo / "web_ui" / "backend"
    backend_dir.mkdir(parents=True)
    proc_dir = tmp_path / "proc"
    proc_dir.mkdir()
    cmdline_template = "python\0-m\0uvicorn\0main:app\0--host\00.0.0.0\0--port\0{port}\0--log-level\0warning\0"

    def make_pid(pid, port, cwd):
        d = proc_dir / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(cmdline_template.format(port=port).encode("utf-8"))
        os.symlink(str(cwd), str(d / "cwd"))

    (tmp_path / "elsewhere").mkdir()
    make_pid(123, 8000, backend_dir)              # 命中：cwd=后端目录 + 端口 8000
    make_pid(456, 8000, tmp_path / "elsewhere")   # cwd 不符
    make_pid(789, 9000, backend_dir)              # 端口不符
    (proc_dir / "notapid").mkdir()                # 非数字目录名，跳过

    with mock.patch.object(runner.os, "kill") as kill:
        pids = runner._find_stray_uvicorn_pids(repo, 8000, proc_dir=str(proc_dir))
        assert pids == [123]
        # 自身进程不杀；_terminate_pids 负责发信号，这里只验证扫描结果
        kill.assert_not_called()

    with mock.patch.object(runner.os, "kill") as kill, \
         mock.patch.object(runner.wui, "_pid_alive", return_value=False), \
         mock.patch.object(runner, "STOP_WAIT_S", 0.1), \
         mock.patch.object(runner, "POLL_INTERVAL_S", 0.02):
        runner._terminate_pids([123])
        kill.assert_any_call(123, signal.SIGTERM)


def test_web_start_command_env_and_log_permissions(repo_and_car, tmp_path):
    repo, car = repo_and_car
    log_file = tmp_path / "logs" / "web-deploy.log"
    popen_kwargs = {}
    fake_proc = mock.Mock(pid=98765)

    def fake_popen(cmd, **kwargs):
        popen_kwargs["cmd"] = [str(part) for part in cmd]
        popen_kwargs.update(kwargs)
        return fake_proc

    patches = _patch_web_ready()
    patches += [
        mock.patch.object(runner, "WEB_LOG_FILE", log_file),
        mock.patch.object(runner.subprocess, "Popen", side_effect=fake_popen),
    ]
    with _start_all(patches), \
         mock.patch.object(runner.subprocess, "run", side_effect=_fake_run([])):
        code = runner.deploy(repo, car, backend_port=8000)
    assert code == 0
    cmd = popen_kwargs["cmd"]
    assert cmd[:3] == [sys.executable, "-m", "donkeycar.management"]
    assert "web" in cmd
    for key, value in (("--path", str(repo / "web_ui")),
                       ("--backend-port", "8000"),
                       ("--backend-host", "0.0.0.0"),
                       ("--route", "/drive")):
        idx = cmd.index(key)
        assert cmd[idx + 1] == value, (key, cmd)
    env = popen_kwargs["env"]
    assert env["PYTHONPATH"] == str(repo)
    venv_bin = str(Path(sys.executable).parent)
    assert env["PATH"].startswith(venv_bin + runner.os.pathsep)
    assert popen_kwargs["start_new_session"] is True
    # 日志文件权限 0600
    assert log_file.is_file()
    assert stat.S_IMODE(log_file.stat().st_mode) == 0o600


def test_registered_instance_on_other_port_is_not_stopped():
    inst = _live_instance(9000)
    with mock.patch.object(runner.wui, "read_instance", return_value=inst), \
         mock.patch.object(runner, "_terminate_pids") as terminate, \
         mock.patch.object(runner.wui, "remove_instance") as remove:
        assert runner._stop_registered_web(8000) is False
    terminate.assert_not_called()
    remove.assert_not_called()


def test_dead_registration_is_removed_and_allows_stray_cleanup():
    inst = _live_instance(8000)
    with mock.patch.object(runner.wui, "read_instance", return_value=inst), \
         mock.patch.object(runner.wui, "_pid_alive", return_value=False), \
         mock.patch.object(runner, "_terminate_pids") as terminate, \
         mock.patch.object(runner.wui, "remove_instance") as remove:
        assert runner._stop_registered_web(8000) is False
    terminate.assert_not_called()
    remove.assert_called_once_with(only_pid=inst["pid"])


def test_npm_and_car_update_use_isolated_conda_path(repo_and_car):
    repo, car = repo_and_car
    calls = []
    with mock.patch.object(runner.subprocess, "run",
                           side_effect=_fake_run(calls)), \
         mock.patch.dict(runner.os.environ, {"PYTHONPATH": "/wrong/repo"}, clear=False), \
         _start_all(_patch_web_ready()):
        assert runner.deploy(repo, car) == 0
    for cmd, kwargs in calls:
        if "npm" in cmd or "update" in cmd:
            assert kwargs["env"]["PYTHONPATH"] == str(repo)
            expected = str(Path(sys.executable).parent) + os.pathsep
            assert kwargs["env"]["PATH"].startswith(expected)


# ===========================================================================
# CLI 与令牌脱敏
# ===========================================================================

def test_main_cli_parses_args_and_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with mock.patch.object(runner, "deploy") as deploy:
        runner.main(["--repo", "/tmp/r", "--car", "/tmp/c", "--backend-port", "9001"])
        assert deploy.call_count == 1
        args, kwargs = deploy.call_args
        assert args[0] == Path("/tmp/r") or str(args[0]) == "/tmp/r"
        assert str(args[1]) == "/tmp/c"
        assert kwargs["backend_port"] == 9001
        assert kwargs["dry_run"] is False
    with mock.patch.object(runner, "deploy") as deploy:
        runner.main(["--dry-run"])
        args, kwargs = deploy.call_args
        assert str(args[0]) == str(runner.REPO_ROOT)  # 默认仓库=脚本所在仓库
        assert str(args[1]) == str(Path.cwd())        # 默认车辆目录=当前目录
        assert kwargs["backend_port"] == 8000
        assert kwargs["dry_run"] is True


def test_redact_masks_token_values(monkeypatch):
    monkeypatch.setenv("DRIVE_API_TOKEN", "supersecret123")
    text = "局域网入口: http://192.168.3.9:8000/?token=abcd1234&e=1 token=xyz DRIVE_API_TOKEN=supersecret123"
    redacted = runner._redact(text)
    assert "abcd1234" not in redacted
    assert "xyz" not in redacted or "token=***" in redacted
    assert "supersecret123" not in redacted
