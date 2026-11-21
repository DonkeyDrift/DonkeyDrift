#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tony 标准部署命令（tony-deployment guardrails Task 3）。

一条可重复执行的部署链，把目标部署工作树更新到 ``origin/Tony`` 并完成
前端构建、车辆模板同步、Web 重启与验收：

1. 预检：车辆目录须含 ``manage.py``；仓库须含 ``.git`` 与
   ``web_ui/frontend/package.json``；任一缺失在执行任何命令前拒绝。
2. 干净工作树保护：``git status --porcelain`` 非空即拒绝 fetch/merge
   （只在干净工作树上 fast-forward，不 reset、不强推、不丢弃修改）。
3. ``git -C <repo> fetch origin Tony`` → ``git -C <repo> merge --ff-only
   origin/Tony`` → ``npm run build``（cwd=web_ui/frontend）→
   ``<python> -m donkeycar.management update``（cwd=<car>，保留其自动备份）。
   任一步非零（``check=True``）立即中止，后续步骤不再执行。
4. 重启只处理目标部署：优先终止 ``webui.json`` 登记的旧实例并等待退出；
   无登记时仅匹配 cwd=<repo>/web_ui/backend 且命令行含目标端口的 uvicorn。
5. 以 ``<python> -m donkeycar.management web --path <repo>/web_ui
   --backend-port <port> --backend-host 0.0.0.0 --route /drive`` 启动：
   继承环境但移除 ``PYTHONPATH``，并把 ``sys.executable`` 所在 bin 加到
   PATH 前端。子进程输出写入日志文件（权限 0600，后端打印的带令牌
   局域网入口因此不外泄）；部署自身的输出不回显任何令牌（``_redact``）。
6. 健康检查：等待 ``find_live_instance()`` 与 ``GET /api/drive/stats``
   均就绪；最后逐字节比较车辆 ``manage.py`` 与
   ``donkeycar/templates/complete.py``，不一致返回非零。

用法::

    python3 scripts/deploy_tony.py [--repo PATH] [--car PATH] \
        [--backend-port 8000] [--dry-run]

默认仓库为脚本所在仓库，默认车辆目录为当前目录。``--dry-run`` 只打印
部署计划（预检问题作为提示列出，不做拦截），不执行任何命令。
"""

import argparse
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 直接运行脚本时 sys.path[0] 是 scripts/，把仓库根加进来才能 import donkeycar
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from donkeycar import webui_instance as wui  # noqa: E402  仅依赖标准库的实例登记/探测接口

# Web 子进程日志：放在 ~/.donkeycar 运行时目录，避免弄脏部署工作树的
# git status；后端会打印带令牌的局域网入口，故权限收紧到 0600
WEB_LOG_FILE = Path.home() / ".donkeycar" / "web-deploy.log"

# 就绪等待：登记 find_live_instance() + /api/drive/stats 双就绪的截止时间
WAIT_READY_TIMEOUT_S = 90.0
POLL_INTERVAL_S = 0.5
# 终止旧实例：SIGTERM 宽限期，超时升级 SIGKILL
STOP_WAIT_S = 10.0
# /api/drive/stats 单次探测超时（仅本机回环）
PROBE_TIMEOUT_S = 2.0
# 各链式步骤超时（秒）
GIT_TIMEOUT_S = 120
BUILD_TIMEOUT_S = 1800
UPDATE_TIMEOUT_S = 600

# token=<值>（含 DRIVE_API_TOKEN=）一律打码，不回显完整令牌
_TOKEN_RE = re.compile(r"(?i)(token[=:]\s*)([A-Za-z0-9._~+/-]{3,})")


class DeployError(RuntimeError):
    """部署守卫失败（未执行任何破坏性命令即中止）。"""


def _redact(text):
    """抹掉文本中的令牌值：token=*** 与 DRIVE_API_TOKEN 环境变量值。"""
    if not text:
        return ""
    text = _TOKEN_RE.sub(r"\1***", text)
    secret = os.environ.get("DRIVE_API_TOKEN", "").strip()
    if secret:
        text = text.replace(secret, "***")
    return text


# ── 预检与计划 ──────────────────────────────────────────────────────

def _preflight(repo, car):
    """执行前预检：返回问题列表（空列表表示通过）。"""
    problems = []
    if not (car / "manage.py").is_file():
        problems.append(f"车辆目录缺少 manage.py，不是有效的车辆目录：{car}"
                        "（先在车辆目录运行 donkey createcar）")
    if not (repo / ".git").exists():
        problems.append(f"仓库路径缺少 .git，不是 Git 工作树：{repo}")
    if not (repo / "web_ui" / "frontend" / "package.json").is_file():
        problems.append(f"仓库缺少 web_ui/frontend/package.json，"
                        f"无法执行 npm run build：{repo}")
    return problems


def _print_plan(repo, car, port):
    print("== Tony 标准部署计划（dry-run，仅列步骤，不执行任何命令） ==")
    print(f"仓库：{repo}")
    print(f"车辆目录：{car}")
    print(f"后端端口：{port}")
    print("0. 预检：车辆目录须含 manage.py；仓库须含 web_ui/frontend 与 .git；"
          "git status --porcelain 须为空（脏工作树在 fetch/merge 前拒绝）")
    print(f"1. git -C {repo} fetch origin Tony")
    print(f"2. git -C {repo} merge --ff-only origin/Tony（只允许 fast-forward）")
    print(f"3. npm run build（cwd={repo / 'web_ui' / 'frontend'}，构建前端生产包）")
    print(f"4. {sys.executable} -m donkeycar.management update"
          f"（cwd={car}，donkey update 自带备份，不丢弃用户数据）")
    print(f"5. 重启 Web：终止 webui.json 登记的旧实例（兜底：仅匹配 "
          f"cwd={repo / 'web_ui' / 'backend'} 且命令行含端口 {port} 的 uvicorn）；"
          f"再以 {sys.executable} -m donkeycar.management web --path {repo / 'web_ui'} "
          f"--backend-port {port} --backend-host 0.0.0.0 --route /drive 启动"
          f"（继承环境但移除 PYTHONPATH；日志 {WEB_LOG_FILE}，权限 0600）")
    print("6. 健康检查：等待实例登记 find_live_instance() 与 GET /api/drive/stats 就绪")
    print(f"7. 模板校验：逐字节比较 {car / 'manage.py'} 与 "
          f"{repo / 'donkeycar' / 'templates' / 'complete.py'}")


# ── 链式步骤（fetch → ff-only merge → 构建 → 模板同步） ─────────────

def _assert_clean_worktree(repo):
    result = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True, text=True, timeout=GIT_TIMEOUT_S, check=False,
    )
    if result.returncode != 0:
        raise DeployError(
            f"git status 失败（{repo} 是否为有效的 Git 仓库？）："
            f"{_redact(result.stderr.strip())}")
    dirty = result.stdout.strip()
    if dirty:
        preview = "\n".join(dirty.splitlines()[:10])
        raise DeployError(
            "工作树不干净，拒绝 fetch/merge（只在干净工作树上 fast-forward，"
            "不 reset、不强推、不丢弃修改）。请先提交或 stash 以下修改：\n"
            f"{_redact(preview)}")


def _run_step(cmd, timeout, cwd=None, env=None):
    cmd = [str(part) for part in cmd]
    suffix = f"（cwd={cwd}）" if cwd else ""
    print(f"执行：{' '.join(cmd)}{suffix}")
    subprocess.run(cmd, check=True, timeout=timeout,
                   cwd=str(cwd) if cwd else None, env=env)


# ── Web 重启（只处理目标部署） ──────────────────────────────────────

def _read_cmdline(pid, proc_dir):
    try:
        with open(os.path.join(str(proc_dir), str(pid), "cmdline"), "rb") as f:
            raw = f.read()
    except OSError:
        return None
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def _find_stray_uvicorn_pids(repo, port, proc_dir="/proc"):
    """无登记时的兜底扫描：仅匹配 cwd=<repo>/web_ui/backend 且命令行含
    目标端口的 uvicorn 进程。非 Linux（无 /proc）返回 []。"""
    backend_dir = os.path.realpath(str(Path(repo) / "web_ui" / "backend"))
    port_token = str(int(port))
    pids = []
    try:
        entries = os.listdir(proc_dir)
    except OSError:
        return pids
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == os.getpid():
            continue
        cmdline = _read_cmdline(pid, proc_dir)
        if not cmdline or "uvicorn" not in cmdline or port_token not in cmdline:
            continue
        try:
            cwd = os.readlink(os.path.join(proc_dir, entry, "cwd"))
        except OSError:
            continue
        if os.path.realpath(cwd) != backend_dir:
            continue
        pids.append(pid)
    return pids


def _terminate_pids(pids):
    """SIGTERM → 等待退出 → 存活者 SIGKILL。"""
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + STOP_WAIT_S
    while time.monotonic() < deadline and any(wui._pid_alive(p) for p in pids):
        time.sleep(POLL_INTERVAL_S)
    for pid in pids:
        if wui._pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def _stop_registered_web(port):
    """终止目标端口的存活登记实例；无登记或登记失效时返回 False。"""
    inst = wui.read_instance()
    if not inst or int(inst["backend_port"]) != int(port):
        return False
    pid = int(inst["pid"])
    if not wui._pid_alive(pid):
        wui.remove_instance(only_pid=pid)
        return False
    print(f"发现实例登记（pid={pid} backend=:{inst['backend_port']}），停止旧 Web …")
    _terminate_pids([pid])
    wui.remove_instance(only_pid=pid)
    return True


def _open_deploy_log():
    """以 0600 权限打开 Web 子进程日志（后端会打印带令牌的局域网入口）。"""
    WEB_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(WEB_LOG_FILE, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.fchmod(fd, 0o600)
    return fd


def _web_env():
    """Web 子进程环境：继承但移除 PYTHONPATH，并把 sys.executable 所在
    bin 加到 PATH 前端（保证 uvicorn/npm 等与部署解释器同源）。"""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    venv_bin = os.path.dirname(sys.executable)
    if venv_bin:
        env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
    return env


def _restart_web(repo, port):
    print("重启 Web UI：优先终止 webui.json 登记的旧实例 …")
    if not _stop_registered_web(port):
        strays = _find_stray_uvicorn_pids(repo, port)
        if strays:
            print(f"无实例登记，按 cwd+端口 匹配到旧 uvicorn 进程 {strays}，停止中 …")
            _terminate_pids(strays)
    cmd = [sys.executable, "-m", "donkeycar.management", "web",
           "--path", str(repo / "web_ui"),
           "--backend-port", str(port),
           "--backend-host", "0.0.0.0",
           "--route", "/drive"]
    print(f"启动 Web：{' '.join(cmd)}（日志 {WEB_LOG_FILE}，权限 0600；"
          "PYTHONPATH 已移除）")
    log_fd = _open_deploy_log()
    try:
        # start_new_session：deploy 退出后 Web 进程组独立存活，不随终端挂断
        subprocess.Popen(cmd, cwd=str(repo), env=_web_env(),
                         stdin=subprocess.DEVNULL, stdout=log_fd,
                         stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        os.close(log_fd)


# ── 验收：健康检查 + 模板逐字节比较 ─────────────────────────────────

def _probe_stats(port, timeout=PROBE_TIMEOUT_S):
    """GET http://127.0.0.1:<port>/api/drive/stats 是否 2xx。"""
    url = f"http://127.0.0.1:{int(port)}/api/drive/stats"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


def _wait_web_ready(port):
    deadline = time.monotonic() + WAIT_READY_TIMEOUT_S
    while time.monotonic() < deadline:
        inst = wui.find_live_instance()
        if (inst and int(inst.get("backend_port", 0)) == int(port)
                and _probe_stats(port)):
            return True
        time.sleep(POLL_INTERVAL_S)
    return False


def _verify_car_template(repo, car):
    """逐字节比较车辆 manage.py 与仓库模板；一致返回 None，否则返回原因。"""
    template = repo / "donkeycar" / "templates" / "complete.py"
    manage = car / "manage.py"
    if not template.is_file():
        return f"仓库缺少 {template}，无法做模板校验"
    if not manage.is_file():
        return f"车辆目录缺少 {manage}"
    if template.read_bytes() != manage.read_bytes():
        return (f"更新后 {manage} 与 {template} 仍不一致；"
                "请检查 donkey update 是否成功（原 manage.py 已由其自动备份）")
    return None


# ── 主流程 ──────────────────────────────────────────────────────────

def _exit_code_of(exc):
    code = getattr(exc, "returncode", None)
    return code if isinstance(code, int) and code != 0 else 1


def deploy(repo_root, car_path, backend_port=8000, dry_run=False):
    """Tony 标准部署。返回 0 成功，非零失败（未执行或验收未过）。"""
    repo = Path(repo_root).expanduser().resolve()
    car = Path(car_path).expanduser().resolve()
    port = int(backend_port)

    problems = _preflight(repo, car)
    if problems:
        if dry_run:
            print("== dry-run 预检提示（不拦截；正式执行将因以下问题拒绝） ==")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print("预检失败，未执行任何命令：", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1

    if dry_run:
        _print_plan(repo, car, port)
        return 0

    print(f"== Tony 标准部署：repo={repo} car={car} backend=:{port} ==")
    try:
        _assert_clean_worktree(repo)
        _run_step(["git", "-C", str(repo), "fetch", "origin", "Tony"],
                  GIT_TIMEOUT_S)
        _run_step(["git", "-C", str(repo), "merge", "--ff-only", "origin/Tony"],
                  GIT_TIMEOUT_S)
        print("已 fast-forward 到 origin/Tony")
        _run_step(["npm", "run", "build"], BUILD_TIMEOUT_S,
                  cwd=repo / "web_ui" / "frontend", env=_web_env())
        print("前端生产包构建完成")
        _run_step([sys.executable, "-m", "donkeycar.management", "update"],
                  UPDATE_TIMEOUT_S, cwd=car, env=_web_env())
        print("donkey update 完成（模板已同步，原文件由其自动备份）")
    except (DeployError, subprocess.SubprocessError, OSError) as exc:
        print(f"部署中止：{_redact(str(exc))}", file=sys.stderr)
        return _exit_code_of(exc)

    try:
        _restart_web(repo, port)
        if not _wait_web_ready(port):
            print(f"健康检查失败：实例登记 find_live_instance() 与 "
                  f"GET /api/drive/stats 在 {WAIT_READY_TIMEOUT_S:.0f}s 内"
                  f"未就绪；详见日志 {WEB_LOG_FILE}", file=sys.stderr)
            return 1
        mismatch = _verify_car_template(repo, car)
        if mismatch:
            print(f"模板校验失败：{mismatch}", file=sys.stderr)
            return 1
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"Web 重启失败：{_redact(str(exc))}", file=sys.stderr)
        return 1

    print(f"部署完成：Web UI http://localhost:{port}/#/drive "
          f"（{repo} 已是 origin/Tony，车辆模板一致）")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="deploy_tony",
        description="Tony 标准部署命令：fetch/ff-only 更新仓库 → 构建前端 → "
                    "donkey update 同步车辆模板 → 重启 Web 并健康检查。")
    parser.add_argument("--repo", default=None,
                        help="仓库路径（默认：脚本所在仓库）")
    parser.add_argument("--car", default=None,
                        help="车辆目录（默认：当前目录）")
    parser.add_argument("--backend-port", type=int, default=8000,
                        help="Web 后端端口（默认：8000）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印部署计划，不执行任何命令")
    args = parser.parse_args(argv)
    repo = Path(args.repo) if args.repo else REPO_ROOT
    car = Path(args.car) if args.car else Path.cwd()
    return deploy(repo, car, backend_port=args.backend_port,
                  dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
