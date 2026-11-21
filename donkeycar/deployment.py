#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部署诊断（Tony 部署守护）。

集中三类 Drive 启动前检查，生成中文警告，供 TUI（tui.py）与
launcher（server.py）在清理/启动进程前提示；base.py 启动 Web 时登记源码提交：

1. 运行中的 Web 进程（~/.donkeycar/webui.json 登记）由旧源码启动 →
   提示重启以对齐版本；
2. 本地源码落后 ``origin/Tony`` → 显示落后数量，提示走标准部署命令；
3. 车辆 ``manage.py`` 与仓库模板 ``complete.py`` 不一致 → 提示
   ``donkey update`` 同步（自带备份）。

仅依赖标准库；HEAD 读取直接解析本地 ``.git`` 元数据（等价
``git rev-parse HEAD``，不创建子进程、不依赖 git 可执行文件）；落后
计数用本地 ``git rev-list``（只读、3 秒超时、不 fetch）。任何查询
失败一律静默降级（None/跳过该项检查），绝不阻塞启动，也不覆盖或
自动更新任何文件。
"""

import subprocess
from pathlib import Path

# 本地 Git 查询超时（秒）：仅读本地元数据，正常毫秒级
GIT_TIMEOUT_S = 3

# 部署基准分支：Tony 标准部署链路的 ff-only 目标
BASE_BRANCH = "origin/Tony"

# 仓库根目录缺省值（本模块位于 <repo>/donkeycar/ 下）
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _resolve_repo_root(repo_root):
    """显式 repo_root 优先，缺省用本模块所在仓库根。"""
    return Path(repo_root) if repo_root else _REPO_ROOT


def _resolve_git_dir(root):
    """``root`` 的 Git 元数据目录；无 Git 元数据返回 None。

    普通仓库即 ``.git/``；链接 worktree/子模块的 ``.git`` 是文件，内容
    ``gitdir: <path>``（相对路径相对 root 解析），指向真实元数据目录
    （内含本 worktree 的 HEAD）。
    """
    dot_git = root / ".git"
    if dot_git.is_dir():
        return dot_git
    if dot_git.is_file():
        try:
            text = dot_git.read_text(encoding="utf-8",
                                     errors="replace").strip()
        except OSError:
            return None
        if text.startswith("gitdir:"):
            gitdir = Path(text.split(":", 1)[1].strip())
            if not gitdir.is_absolute():
                gitdir = (root / gitdir).resolve()
            if gitdir.is_dir():
                return gitdir
    return None


def _resolve_common_dir(gitdir):
    """Git 公共目录（链接 worktree 共享 refs/heads 等；普通仓库即 gitdir）。"""
    commondir_file = gitdir / "commondir"
    try:
        text = commondir_file.read_text(encoding="utf-8",
                                        errors="replace").strip()
    except OSError:
        return gitdir
    if not text:
        return gitdir
    common = Path(text)
    if not common.is_absolute():
        common = (gitdir / common).resolve()
    return common if common.is_dir() else gitdir


def _resolve_ref(ref, gitdir, common_dir):
    """ref 全名 → 目标内容：worktree 私有 loose → 公共 loose → packed-refs。

    git 语义：packed-refs 里同 ref 取最后一个匹配（后写覆盖先写）；
    返回 None 表示本地无法解析该 ref。
    """
    for base in (gitdir, common_dir):
        try:
            value = (base / ref).read_text(encoding="utf-8",
                                           errors="replace").strip()
        except OSError:
            continue
        if value:
            return value
    try:
        lines = (common_dir / "packed-refs").read_text(
            encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    result = None
    for line in lines:
        line = line.strip()
        if not line or line.startswith(("#", "^")):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip() == ref:
            result = parts[0]
    return result


def get_source_head(repo_root=None):
    """当前源码的本地 Git 提交号（等价 ``git rev-parse HEAD``）。

    直接解析本地 ``.git`` 元数据：结果同本地 ``git rev-parse HEAD``，
    但不依赖 git 可执行文件/PATH、不创建子进程；支持普通仓库、链接
    worktree、子模块、detached HEAD 与 packed-refs。任何失败（无 Git
    元数据等）返回 None，绝不阻塞启动。
    """
    gitdir = _resolve_git_dir(_resolve_repo_root(repo_root))
    if gitdir is None:
        return None
    common_dir = _resolve_common_dir(gitdir)
    try:
        head = (gitdir / "HEAD").read_text(
            encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    # HEAD 是符号引用链（HEAD → ref → ref…）时逐级解析，5 层封顶防死循环
    for _ in range(5):
        if not head:
            return None
        if not head.startswith("ref: "):
            return head
        head = _resolve_ref(head[len("ref: "):].strip(), gitdir, common_dir)
    return None


def _behind_count(repo_root=None):
    """本地 HEAD 落后 BASE_BRANCH 的提交数（``git rev-list --count``）。

    不 fetch——只比较本地已有的 origin/Tony 引用；取不到（从未 fetch、
    非 Git 仓库等）返回 None，表示无法判断，调用方不告警。
    """
    root = _resolve_repo_root(repo_root)
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-list", "--count",
             f"HEAD..{BASE_BRANCH}"],
            capture_output=True, text=True, timeout=GIT_TIMEOUT_S, check=True,
        )
        return int(result.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _manage_py_matches_template(car_path, repo_root=None):
    """车辆 ``manage.py`` 与仓库模板 ``complete.py`` 是否逐字节一致。

    任一文件缺失/不可读返回 None（无法比较，不告警）。
    """
    template = _resolve_repo_root(repo_root) / "donkeycar" / "templates" \
        / "complete.py"
    manage_py = Path(car_path) / "manage.py"
    try:
        return manage_py.read_bytes() == template.read_bytes()
    except OSError:
        return None


def collect_deployment_warnings(car_path=None, repo_root=None, web_instance=None):
    """收集 Drive 启动前的部署警告（中文，每条一句；无警告返回 []）。

    - ``web_instance``（webui.json 登记 dict）存在但缺 ``source_head``：
      提示重启以确认版本；登记版本与当前源码不一致：提示重启。
    - 本地源码落后 ``origin/Tony``：显示落后数量。
    - ``car_path`` 下 ``manage.py`` 与仓库模板不一致：提示 ``donkey update``。

    无 Git 元数据（HEAD 取不到）时不做源码版本类告警，避免误报。
    """
    warnings = []
    head = get_source_head(repo_root)

    if web_instance is not None:
        port = web_instance.get("backend_port") or 8000
        registered = web_instance.get("source_head")
        if not registered:
            warnings.append(
                f"端口 {port} 的 Web 进程登记缺少版本信息（由旧版本代码启动），"
                "建议重启 Web UI 以确认与当前源码一致")
        elif head is not None and registered != head:
            warnings.append(
                f"端口 {port} 的 Web 进程由旧源码启动"
                f"（登记 {str(registered)[:12]}，当前 {head[:12]}），"
                "重启 Web UI 后即可与新代码一致")

    if head is not None:
        behind = _behind_count(repo_root)
        if behind:
            warnings.append(
                f"本地源码落后 {BASE_BRANCH} {behind} 个提交，"
                "请先运行标准部署命令更新源码再启动"
                "（scripts/deploy_tony.py）")

    if car_path is not None:
        matches = _manage_py_matches_template(car_path, repo_root)
        if matches is False:
            warnings.append(
                "车辆 manage.py 与当前源码模板（complete.py）不一致，"
                "行为可能与最新代码不符；请在车辆目录运行 `donkey update`"
                " 同步（自带备份）")

    return warnings
